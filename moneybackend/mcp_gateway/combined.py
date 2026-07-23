from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from lk.asgi import application as django_application

from .server import app as mcp_application


MCP_PATHS = {
    '/authorize',
    '/token',
    '/register',
    '/revoke',
    '/.well-known/oauth-authorization-server',
    '/.well-known/oauth-protected-resource/mcp',
}


class CombinedAsgiApplication:
    """Dispatch OAuth/MCP traffic to FastMCP and everything else to Django."""

    def __init__(
        self,
        *,
        django_app: Callable[..., Awaitable[Any]],
        mcp_app: Callable[..., Awaitable[Any]],
    ):
        self.django_app = django_app
        self.mcp_app = mcp_app

    @staticmethod
    def is_mcp_path(path: str) -> bool:
        return path == '/mcp' or path.startswith('/mcp/') or path in MCP_PATHS

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            await self.mcp_app(scope, receive, send)
            return

        if scope['type'] == 'http' and self.is_mcp_path(scope.get('path', '')):
            await self.mcp_app(scope, receive, send)
            return

        await self.django_app(scope, receive, send)


application = CombinedAsgiApplication(
    django_app=django_application,
    mcp_app=mcp_application,
)
