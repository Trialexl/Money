from __future__ import annotations

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lk.settings')

import django

django.setup()

from django.conf import settings
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .domain_tools import register_domain_tools
from .oauth_provider import (
    READ_SCOPE,
    VALID_SCOPES,
    FrontMoneyOAuthProvider,
)


provider = FrontMoneyOAuthProvider()
mcp = FastMCP(
    name='FrontMoney',
    instructions=(
        'Read and update the authenticated user’s FrontMoney data. '
        'Use the typed finance tools; never construct API paths or HTTP requests.'
    ),
    auth_server_provider=provider,
    auth=AuthSettings(
        issuer_url=settings.MCP_ISSUER_URL,
        resource_server_url=settings.MCP_PUBLIC_URL,
        required_scopes=[READ_SCOPE],
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=VALID_SCOPES,
            default_scopes=VALID_SCOPES,
        ),
        revocation_options=RevocationOptions(enabled=True),
    ),
    streamable_http_path='/mcp',
    stateless_http=True,
    json_response=True,
)


register_domain_tools(mcp)


async def oauth_metadata(request: Request) -> Response:
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-store',
    }
    if request.method == 'OPTIONS':
        return Response(status_code=204, headers=headers)
    issuer = settings.MCP_ISSUER_URL
    return JSONResponse(
        {
            'issuer': issuer,
            'authorization_endpoint': f'{issuer}/authorize',
            'token_endpoint': f'{issuer}/token',
            'registration_endpoint': f'{issuer}/register',
            'revocation_endpoint': f'{issuer}/revoke',
            'scopes_supported': VALID_SCOPES,
            'response_types_supported': ['code'],
            'grant_types_supported': ['authorization_code', 'refresh_token'],
            'token_endpoint_auth_methods_supported': ['none'],
            'revocation_endpoint_auth_methods_supported': ['none'],
            'code_challenge_methods_supported': ['S256'],
        },
        headers=headers,
    )


def create_app():
    application = mcp.streamable_http_app()
    metadata_path = '/.well-known/oauth-authorization-server'
    for index, route in enumerate(application.routes):
        if getattr(route, 'path', None) == metadata_path:
            application.routes[index] = Route(
                metadata_path,
                endpoint=oauth_metadata,
                methods=['GET', 'OPTIONS'],
            )
            break
    return application


app = create_app()
