"""Security middleware: auth and security headers."""
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Add standard security headers to every response."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"x-frame-options", b"DENY"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                ])
                if not scope["path"].startswith("/static"):
                    headers.extend([
                        (b"cache-control", b"no-store, no-cache, must-revalidate"),
                        (b"pragma", b"no-cache"),
                        (b"vary", b"Cookie"),
                    ])
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


_AUTH_EXEMPT = {"/health", "/", "/login/google", "/auth/callback"}


class AuthMiddleware:
    """Redirect unauthenticated requests to the landing page."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if path in _AUTH_EXEMPT or path.startswith("/static"):
            await self.app(scope, receive, send)
            return

        session = scope.get("session", {})
        if not session.get("user"):
            response = RedirectResponse("/", status_code=302)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
