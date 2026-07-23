from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .models import (
    McpOAuthAuthorizationCode,
    McpOAuthAuthorizationRequest,
    McpOAuthClient,
    McpOAuthToken,
)


READ_SCOPE = 'frontmoney.read'
WRITE_SCOPE = 'frontmoney.write'
VALID_SCOPES = [READ_SCOPE, WRITE_SCOPE]


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(48)


def _origin(parsed) -> str:
    host = parsed.hostname or ''
    display_host = f'[{host}]' if ':' in host else host
    port = f':{parsed.port}' if parsed.port is not None else ''
    return f'{parsed.scheme}://{display_host}{port}'


def validate_redirect_uri(value: str) -> None:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.hostname:
        raise RegistrationError('invalid_redirect_uri', 'Redirect URI must be absolute.')
    if parsed.username or parsed.password or parsed.fragment:
        raise RegistrationError('invalid_redirect_uri', 'Redirect URI contains unsafe components.')

    if parsed.hostname in {'localhost', '127.0.0.1', '::1'}:
        if parsed.scheme not in {'http', 'https'}:
            raise RegistrationError(
                'invalid_redirect_uri',
                'Loopback redirect URIs must use HTTP or HTTPS.',
            )
        return

    allowed_origins = set(settings.MCP_OAUTH_ALLOWED_REDIRECT_ORIGINS)
    if parsed.scheme != 'https' or _origin(parsed) not in allowed_origins:
        raise RegistrationError(
            'invalid_redirect_uri',
            'Non-loopback redirect URI origin is not allowed.',
        )


class FrontMoneyAuthorizationCode(AuthorizationCode):
    record_id: int
    user_id: str


class FrontMoneyRefreshToken(RefreshToken):
    record_id: int
    user_id: str
    resource: str


class FrontMoneyAccessToken(AccessToken):
    record_id: int
    user_id: str


def _client_from_row(row: McpOAuthClient) -> OAuthClientInformationFull:
    return OAuthClientInformationFull.model_validate(row.metadata)


def _load_client(client_id: str) -> OAuthClientInformationFull | None:
    try:
        row = McpOAuthClient.objects.get(client_id=client_id, is_active=True)
    except McpOAuthClient.DoesNotExist:
        return None
    return _client_from_row(row)


def _register_client(client_info: OAuthClientInformationFull) -> None:
    if not client_info.client_id:
        raise RegistrationError('invalid_client_metadata', 'Client ID is required.')
    if client_info.token_endpoint_auth_method != 'none' or client_info.client_secret:
        raise RegistrationError(
            'invalid_client_metadata',
            'FrontMoney accepts public PKCE clients only; use token_endpoint_auth_method=none.',
        )
    if not client_info.redirect_uris:
        raise RegistrationError('invalid_redirect_uri', 'At least one redirect URI is required.')
    for redirect_uri in client_info.redirect_uris:
        validate_redirect_uri(str(redirect_uri))

    metadata = client_info.model_dump(mode='json')
    try:
        McpOAuthClient.objects.create(client_id=client_info.client_id, metadata=metadata)
    except IntegrityError as exc:
        raise RegistrationError('invalid_client_metadata', 'Client ID already exists.') from exc


def _create_authorization_request(
    client_id: str,
    params: AuthorizationParams,
    scopes: list[str],
) -> str:
    expires_at = timezone.now() + timedelta(seconds=settings.MCP_OAUTH_REQUEST_SECONDS)
    row = McpOAuthAuthorizationRequest.objects.create(
        client_id=client_id,
        redirect_uri=str(params.redirect_uri),
        redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
        state=params.state,
        scopes=scopes,
        code_challenge=params.code_challenge,
        resource=params.resource,
        expires_at=expires_at,
    )
    return str(row.pk)


def approve_authorization_request(request_id: str, user_id: str) -> tuple[str, str, str | None]:
    now = timezone.now()
    with transaction.atomic():
        try:
            pending = (
                McpOAuthAuthorizationRequest.objects.select_for_update()
                .select_related('client')
                .get(pk=request_id)
            )
        except (McpOAuthAuthorizationRequest.DoesNotExist, ValueError) as exc:
            raise ValueError('Authorization request was not found.') from exc
        if pending.completed_at is not None or pending.expires_at <= now:
            raise ValueError('Authorization request has expired or was already used.')

        raw_code = new_token()
        McpOAuthAuthorizationCode.objects.create(
            code_hash=hash_token(raw_code),
            client=pending.client,
            user_id=user_id,
            redirect_uri=pending.redirect_uri,
            redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
            scopes=pending.scopes,
            code_challenge=pending.code_challenge,
            resource=pending.resource,
            expires_at=now + timedelta(seconds=settings.MCP_OAUTH_AUTH_CODE_SECONDS),
        )
        pending.user_id = user_id
        pending.completed_at = now
        pending.save(update_fields=['user', 'completed_at'])
        return raw_code, pending.redirect_uri, pending.state


def deny_authorization_request(request_id: str, user_id: str) -> tuple[str, str | None]:
    now = timezone.now()
    with transaction.atomic():
        try:
            pending = McpOAuthAuthorizationRequest.objects.select_for_update().get(pk=request_id)
        except (McpOAuthAuthorizationRequest.DoesNotExist, ValueError) as exc:
            raise ValueError('Authorization request was not found.') from exc
        if pending.completed_at is not None or pending.expires_at <= now:
            raise ValueError('Authorization request has expired or was already used.')
        pending.user_id = user_id
        pending.completed_at = now
        pending.save(update_fields=['user', 'completed_at'])
        return pending.redirect_uri, pending.state


def get_authorization_request(request_id: str) -> McpOAuthAuthorizationRequest | None:
    try:
        pending = McpOAuthAuthorizationRequest.objects.select_related('client').get(pk=request_id)
    except (McpOAuthAuthorizationRequest.DoesNotExist, ValueError):
        return None
    if pending.completed_at is not None or pending.expires_at <= timezone.now():
        return None
    return pending


def _load_authorization_code(
    client_id: str,
    raw_code: str,
) -> FrontMoneyAuthorizationCode | None:
    try:
        row = McpOAuthAuthorizationCode.objects.get(
            code_hash=hash_token(raw_code),
            client_id=client_id,
            consumed_at__isnull=True,
        )
    except McpOAuthAuthorizationCode.DoesNotExist:
        return None
    return FrontMoneyAuthorizationCode(
        code=raw_code,
        scopes=row.scopes,
        expires_at=row.expires_at.timestamp(),
        client_id=row.client_id,
        code_challenge=row.code_challenge,
        redirect_uri=row.redirect_uri,
        redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
        resource=row.resource,
        record_id=row.pk,
        user_id=str(row.user_id),
    )


def _create_token_row(client_id: str, user_id: str, scopes: list[str], resource: str) -> tuple[McpOAuthToken, str, str]:
    raw_access_token = new_token()
    raw_refresh_token = new_token()
    now = timezone.now()
    row = McpOAuthToken.objects.create(
        access_token_hash=hash_token(raw_access_token),
        refresh_token_hash=hash_token(raw_refresh_token),
        client_id=client_id,
        user_id=user_id,
        scopes=scopes,
        resource=resource,
        access_expires_at=now + timedelta(seconds=settings.MCP_OAUTH_ACCESS_TOKEN_SECONDS),
        refresh_expires_at=now + timedelta(seconds=settings.MCP_OAUTH_REFRESH_TOKEN_SECONDS),
    )
    return row, raw_access_token, raw_refresh_token


def _oauth_token(access_token: str, refresh_token: str, scopes: list[str]) -> OAuthToken:
    return OAuthToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.MCP_OAUTH_ACCESS_TOKEN_SECONDS,
        scope=' '.join(scopes),
    )


def _exchange_authorization_code(
    client_id: str,
    authorization_code: FrontMoneyAuthorizationCode,
) -> OAuthToken:
    now = timezone.now()
    with transaction.atomic():
        try:
            row = McpOAuthAuthorizationCode.objects.select_for_update().get(
                pk=authorization_code.record_id,
                client_id=client_id,
                consumed_at__isnull=True,
            )
        except McpOAuthAuthorizationCode.DoesNotExist as exc:
            raise TokenError('invalid_grant', 'Authorization code was already used.') from exc
        if row.expires_at <= now:
            raise TokenError('invalid_grant', 'Authorization code has expired.')
        if row.resource != settings.MCP_PUBLIC_URL:
            raise TokenError('invalid_grant', 'Authorization code has the wrong resource.')

        row.consumed_at = now
        row.save(update_fields=['consumed_at'])
        _, access_token, refresh_token = _create_token_row(
            client_id=row.client_id,
            user_id=str(row.user_id),
            scopes=row.scopes,
            resource=row.resource,
        )
        return _oauth_token(access_token, refresh_token, row.scopes)


def _load_refresh_token(client_id: str, raw_token: str) -> FrontMoneyRefreshToken | None:
    try:
        row = McpOAuthToken.objects.get(
            refresh_token_hash=hash_token(raw_token),
            client_id=client_id,
            revoked_at__isnull=True,
        )
    except McpOAuthToken.DoesNotExist:
        return None
    return FrontMoneyRefreshToken(
        token=raw_token,
        client_id=row.client_id,
        scopes=row.scopes,
        expires_at=int(row.refresh_expires_at.timestamp()),
        record_id=row.pk,
        user_id=str(row.user_id),
        resource=row.resource,
    )


def _exchange_refresh_token(
    client_id: str,
    refresh_token: FrontMoneyRefreshToken,
    scopes: list[str],
) -> OAuthToken:
    now = timezone.now()
    with transaction.atomic():
        try:
            row = McpOAuthToken.objects.select_for_update().get(
                pk=refresh_token.record_id,
                client_id=client_id,
                revoked_at__isnull=True,
            )
        except McpOAuthToken.DoesNotExist as exc:
            raise TokenError('invalid_grant', 'Refresh token was already used or revoked.') from exc
        if row.refresh_expires_at <= now:
            raise TokenError('invalid_grant', 'Refresh token has expired.')
        if row.resource != settings.MCP_PUBLIC_URL:
            raise TokenError('invalid_grant', 'Refresh token has the wrong resource.')
        if not set(scopes).issubset(set(row.scopes)):
            raise TokenError('invalid_scope', 'Requested scope exceeds the original grant.')

        row.revoked_at = now
        row.save(update_fields=['revoked_at'])
        _, access_token, new_refresh_token = _create_token_row(
            client_id=row.client_id,
            user_id=str(row.user_id),
            scopes=scopes,
            resource=row.resource,
        )
        return _oauth_token(access_token, new_refresh_token, scopes)


def _load_access_token(raw_token: str) -> FrontMoneyAccessToken | None:
    try:
        row = McpOAuthToken.objects.get(
            access_token_hash=hash_token(raw_token),
            revoked_at__isnull=True,
            access_expires_at__gt=timezone.now(),
            resource=settings.MCP_PUBLIC_URL,
        )
    except McpOAuthToken.DoesNotExist:
        return None
    return FrontMoneyAccessToken(
        token=raw_token,
        client_id=row.client_id,
        scopes=row.scopes,
        expires_at=int(row.access_expires_at.timestamp()),
        resource=row.resource,
        record_id=row.pk,
        user_id=str(row.user_id),
    )


def _revoke_token(record_id: int) -> None:
    McpOAuthToken.objects.filter(pk=record_id, revoked_at__isnull=True).update(revoked_at=timezone.now())


class FrontMoneyOAuthProvider(
    OAuthAuthorizationServerProvider[
        FrontMoneyAuthorizationCode,
        FrontMoneyRefreshToken,
        FrontMoneyAccessToken,
    ]
):
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return await sync_to_async(_load_client, thread_sensitive=True)(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await sync_to_async(_register_client, thread_sensitive=True)(client_info)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if not client.client_id:
            raise AuthorizeError('invalid_request', 'Client ID is missing.')
        if params.resource != settings.MCP_PUBLIC_URL:
            raise AuthorizeError('invalid_request', 'The OAuth resource must match the FrontMoney MCP URL.')

        scopes = params.scopes or VALID_SCOPES
        if READ_SCOPE not in scopes or not set(scopes).issubset(set(VALID_SCOPES)):
            raise AuthorizeError('invalid_scope', 'A valid FrontMoney read scope is required.')

        request_id = await sync_to_async(_create_authorization_request, thread_sensitive=True)(
            client.client_id,
            params,
            scopes,
        )
        return (
            f'{settings.MCP_ISSUER_URL}/api/v1/mcp/oauth/consent/?'
            f'{urlencode({"request": request_id})}'
        )

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> FrontMoneyAuthorizationCode | None:
        return await sync_to_async(_load_authorization_code, thread_sensitive=True)(
            client.client_id,
            authorization_code,
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: FrontMoneyAuthorizationCode,
    ) -> OAuthToken:
        return await sync_to_async(_exchange_authorization_code, thread_sensitive=True)(
            client.client_id,
            authorization_code,
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> FrontMoneyRefreshToken | None:
        return await sync_to_async(_load_refresh_token, thread_sensitive=True)(
            client.client_id,
            refresh_token,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: FrontMoneyRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        return await sync_to_async(_exchange_refresh_token, thread_sensitive=True)(
            client.client_id,
            refresh_token,
            scopes,
        )

    async def load_access_token(self, token: str) -> FrontMoneyAccessToken | None:
        return await sync_to_async(_load_access_token, thread_sensitive=True)(token)

    async def revoke_token(
        self,
        token: FrontMoneyAccessToken | FrontMoneyRefreshToken,
    ) -> None:
        await sync_to_async(_revoke_token, thread_sensitive=True)(token.record_id)
