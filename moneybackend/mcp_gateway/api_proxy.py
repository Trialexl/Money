from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from mcp.server.auth.middleware.auth_context import get_access_token
from rest_framework_simplejwt.tokens import AccessToken as JwtAccessToken

from .oauth_provider import FrontMoneyAccessToken, READ_SCOPE, WRITE_SCOPE


ALLOWED_API_ROOTS = {
    'auto-payment-graphics',
    'auto-payments',
    'budget-expense',
    'budget-graphics',
    'budget-income',
    'budgets',
    'cash-flow-items',
    'dashboard',
    'expenditure-graphics',
    'expenditures',
    'flow-of-funds',
    'investment',
    'projects',
    'receipts',
    'reports',
    'transfer-graphics',
    'transfers',
    'wallets',
}


def validate_api_path(path: str) -> str:
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('Use a relative API path and pass filters in query.')
    if not parsed.path.startswith('/api/v1/') or '%' in parsed.path:
        raise ValueError('API path must begin with /api/v1/ and must not be encoded.')
    parts = parsed.path.removeprefix('/api/v1/').split('/')
    if not parts[0] or parts[0] not in ALLOWED_API_ROOTS:
        raise ValueError('This API route is not available through the FrontMoney MCP server.')
    if any(part in {'.', '..'} for part in parts):
        raise ValueError('API path traversal is not allowed.')
    return parsed.path


def validate_query(query: dict[str, Any] | None) -> dict[str, Any]:
    if query is None:
        return {}
    result: dict[str, Any] = {}
    for key, value in query.items():
        if not isinstance(key, str) or not key:
            raise ValueError('Query parameter names must be non-empty strings.')
        values = value if isinstance(value, list) else [value]
        if not all(item is None or isinstance(item, (str, int, float, bool)) for item in values):
            raise ValueError(f'Query parameter {key!r} must contain scalar values.')
        result[key] = value
    return result


def _load_active_user(user_id: str):
    return get_user_model().objects.get(pk=user_id, is_active=True)


def _current_oauth_token(required_scope: str) -> FrontMoneyAccessToken:
    token = get_access_token()
    if not isinstance(token, FrontMoneyAccessToken):
        raise ValueError('FrontMoney OAuth context is missing.')
    if required_scope not in token.scopes:
        raise ValueError(f'OAuth scope {required_scope} is required for this operation.')
    if token.resource != settings.MCP_PUBLIC_URL:
        raise ValueError('OAuth token is bound to a different MCP resource.')
    return token


async def _delegated_jwt(oauth_token: FrontMoneyAccessToken) -> str:
    try:
        user = await sync_to_async(_load_active_user, thread_sensitive=True)(oauth_token.user_id)
    except get_user_model().DoesNotExist as exc:
        raise ValueError('The FrontMoney user is inactive or no longer exists.') from exc

    token = JwtAccessToken.for_user(user)
    token.set_exp(lifetime=timedelta(seconds=settings.MCP_DELEGATED_JWT_SECONDS))
    token['mcp_client_id'] = oauth_token.client_id
    token['mcp_scopes'] = oauth_token.scopes
    return str(token)


async def proxy_api_request(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    required_scope = READ_SCOPE if method == 'GET' else WRITE_SCOPE
    oauth_token = _current_oauth_token(required_scope)
    safe_path = validate_api_path(path)
    safe_query = validate_query(query)
    delegated_token = await _delegated_jwt(oauth_token)

    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {delegated_token}',
        'Host': urlsplit(settings.MCP_ISSUER_URL).netloc,
        'X-FrontMoney-MCP-Client': oauth_token.client_id,
    }
    async with httpx.AsyncClient(
        base_url=settings.MCP_BACKEND_URL,
        follow_redirects=False,
        timeout=30.0,
    ) as client:
        response = await client.request(
            method,
            safe_path,
            params=safe_query,
            json=payload,
            headers=headers,
        )

    if len(response.content) > 2_000_000:
        raise ValueError('FrontMoney response exceeded the MCP response size limit.')
    try:
        data: Any = response.json() if response.content else None
    except ValueError:
        data = response.text[:4000]

    return {
        'status': response.status_code,
        'data': data,
    }
