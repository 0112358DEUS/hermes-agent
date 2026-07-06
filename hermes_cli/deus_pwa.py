"""DEUS PWA overlay — keep additive for upstream merges.

Everything PWA-specific for the browser dashboard lives in this NEW module so
the only upstream-file footprint is a three-line, clearly-marked injection
point in :func:`hermes_cli.web_server.mount_spa`.

What this overlay provides
--------------------------
* :func:`deus_pwa_head_html` — the ``<head>`` fragment injected into the
  serve-time-generated ``index.html``: manifest link, iOS standalone /
  status-bar meta, apple-touch-icon, and a service-worker registration
  script that only runs in secure contexts (``window.isSecureContext``).
* :func:`deus_register_pwa_routes` — a dedicated ``GET /deus-sw.js`` route
  that serves the worker with ``Service-Worker-Allowed: /`` (root scope even
  if a future dist nests the file) and ``Cache-Control: no-store`` (browsers
  must always revalidate the worker so policy updates land immediately).

The worker itself (``web/public/deus-sw.js``) caches ONLY static shell
assets. It never touches ``/api/*``, WebSockets, auth endpoints, or the
token-injected ``index.html`` — navigations stay network-only.

Static PWA files (manifest, icons, the worker source) live in
``web/public/`` so the Vite build copies them into the dist root; the
existing SPA catch-all serves the manifest and icons untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

__all__ = ["deus_pwa_head_html", "deus_register_pwa_routes"]

_SW_FILENAME = "deus-sw.js"
_MANIFEST_FILENAME = "manifest.webmanifest"


def deus_pwa_head_html(prefix: str = "") -> str:
    """Head fragment for the served ``index.html``.

    ``prefix`` is the already-normalised ``X-Forwarded-Prefix`` (e.g.
    ``/hermes``) or ``""`` at root, exactly as passed to ``_serve_index`` —
    all URLs are built with it so the PWA works behind a path-prefix proxy
    without rebuilding the bundle. The manifest itself uses relative
    ``start_url``/``scope``/icons, so it inherits the prefix from its own URL.

    The service worker is registered only when ``window.isSecureContext``
    (HTTPS or localhost) — elsewhere the dashboard degrades gracefully to a
    plain web page, and iOS Safari would refuse the registration anyway.

    ``crossorigin="use-credentials"`` on the manifest link is load-bearing:
    browsers fetch manifests with ``credentials: omit`` by default, so on
    OAuth-gated deployments (``app.state.auth_required``) the cookie-less
    fetch would 302 to ``/login`` and break install. With it, the session
    cookie rides along and the gate passes the request through.
    """
    return (
        f'<link rel="manifest" href="{prefix}/manifest.webmanifest" crossorigin="use-credentials">'
        f'<meta name="theme-color" content="#050506">'
        f'<meta name="apple-mobile-web-app-capable" content="yes">'
        f'<meta name="mobile-web-app-capable" content="yes">'
        f'<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
        f'<meta name="apple-mobile-web-app-title" content="Deus Ex">'
        f'<link rel="apple-touch-icon" sizes="180x180" href="{prefix}/deus-icon-180.png">'
        f"<script>"
        f"if(window.isSecureContext&&'serviceWorker' in navigator){{"
        f"navigator.serviceWorker.register('{prefix}/{_SW_FILENAME}',"
        f"{{scope:'{prefix}/'}}).catch(function(){{}});"
        f"}}"
        f"</script>"
    )


def _find_static(filename: str) -> Optional[Path]:
    """Locate a PWA static file: built dist first, repo source as fallback.

    The Vite build copies ``web/public/*`` into the dist root, so after any
    rebuild the file sits in ``WEB_DIST``. The repo-source fallback keeps
    the routes working against a dist that predates this overlay.
    """
    # Imported lazily to avoid a circular import: web_server imports this
    # module (inside mount_spa), never the other way around at module scope.
    from hermes_cli.web_server import WEB_DIST

    candidates = [
        WEB_DIST / filename,
        Path(__file__).resolve().parent.parent / "web" / "public" / filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def deus_register_pwa_routes(application) -> None:
    """Register ``/deus-sw.js`` and ``/manifest.webmanifest`` routes.

    Must be called before the SPA catch-all route is added (route matching
    is registration-ordered), which ``mount_spa`` guarantees by invoking
    this at its top. Dedicated routes (rather than the catch-all's plain
    ``FileResponse``) are required for the load-bearing headers:

    * ``Service-Worker-Allowed: /`` — permits root scope for the worker.
    * ``Cache-Control: no-store`` — the browser refetches the worker on
      every registration check, so cache-policy fixes deploy instantly.
    * ``application/manifest+json`` — Python's ``mimetypes`` doesn't know
      ``.webmanifest`` and would fall back to ``application/octet-stream``.
    """
    from fastapi.responses import JSONResponse, Response

    @application.get(f"/{_SW_FILENAME}", include_in_schema=False)
    async def deus_service_worker():
        sw_path = _find_static(_SW_FILENAME)
        if sw_path is None:
            return JSONResponse({"error": "service worker not built"}, status_code=404)
        return Response(
            content=sw_path.read_text(encoding="utf-8"),
            media_type="text/javascript; charset=utf-8",
            headers={
                "Service-Worker-Allowed": "/",
                "Cache-Control": "no-store, no-cache, must-revalidate",
            },
        )

    @application.get(f"/{_MANIFEST_FILENAME}", include_in_schema=False)
    async def deus_manifest():
        manifest_path = _find_static(_MANIFEST_FILENAME)
        if manifest_path is None:
            return JSONResponse({"error": "manifest not built"}, status_code=404)
        return Response(
            content=manifest_path.read_text(encoding="utf-8"),
            media_type="application/manifest+json",
        )
