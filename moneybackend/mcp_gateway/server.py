from __future__ import annotations

import os
from urllib.parse import urlparse

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lk.settings')

import django

django.setup()

from django.conf import settings
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
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
public_host = urlparse(settings.MCP_ISSUER_URL).netloc
public_origin = settings.MCP_ISSUER_URL
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
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            public_host,
            'localhost:*',
            '127.0.0.1:*',
            '[::1]:*',
        ],
        allowed_origins=[
            public_origin,
            'http://localhost:*',
            'http://127.0.0.1:*',
            'http://[::1]:*',
        ],
    ),
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


async def protected_resource_metadata(request: Request) -> Response:
    """Keep the advertised authorization server byte-for-byte equal to its issuer."""
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-store',
    }
    if request.method == 'OPTIONS':
        return Response(status_code=204, headers=headers)
    return JSONResponse(
        {
            'resource': settings.MCP_PUBLIC_URL,
            'authorization_servers': [settings.MCP_ISSUER_URL],
            'scopes_supported': [READ_SCOPE],
            'bearer_methods_supported': ['header'],
        },
        headers=headers,
    )


def create_app():
    application = mcp.streamable_http_app()
    metadata_routes = {
        '/.well-known/oauth-authorization-server': oauth_metadata,
        '/.well-known/oauth-protected-resource/mcp': protected_resource_metadata,
    }
    for index, route in enumerate(application.routes):
        path = getattr(route, 'path', None)
        endpoint = metadata_routes.get(path)
        if endpoint is not None:
            application.routes[index] = Route(
                path,
                endpoint=endpoint,
                methods=['GET', 'OPTIONS'],
            )
    return application


app = create_app()
