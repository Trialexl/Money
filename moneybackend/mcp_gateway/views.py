from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from django.conf import settings
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from users.authentication import CookieJWTAuthentication

from .oauth_provider import (
    approve_authorization_request,
    deny_authorization_request,
    get_authorization_request,
)

CONSENT_CSP = (
    "default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
    "style-src 'self' 'unsafe-inline'; form-action 'self' {redirect_origin}"
)


def _append_query(url: str, **values: str | None) -> str:
    parsed = urlsplit(url)
    query = list(parse_qsl(parsed.query, keep_blank_values=True))
    query.extend((key, value) for key, value in values.items() if value is not None)
    return urlunsplit(parsed._replace(query=urlencode(query)))


def _redirect_origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('OAuth redirect URI is invalid.')

    display_host = f'[{parsed.hostname}]' if ':' in parsed.hostname else parsed.hostname
    port = f':{parsed.port}' if parsed.port is not None else ''
    return f'{parsed.scheme}://{display_host}{port}'


def _authenticated_user(request):
    try:
        result = CookieJWTAuthentication().authenticate(request)
    except (InvalidToken, TokenError):
        return None
    return result[0] if result else None


def _login_redirect(request):
    return_to = request.get_full_path()
    return redirect(f'/auth/login?{urlencode({"return_to": return_to})}')


@csrf_protect
@require_http_methods(['GET', 'POST'])
def oauth_consent(request):
    user = _authenticated_user(request)
    if user is None:
        return _login_redirect(request)

    request_id = request.POST.get('request') or request.GET.get('request')
    pending = get_authorization_request(request_id or '')
    if pending is None:
        return HttpResponseBadRequest('OAuth authorization request is invalid or expired.')

    if request.method == 'POST':
        try:
            if request.POST.get('action') == 'approve':
                code, redirect_uri, state = approve_authorization_request(request_id, str(user.pk))
                return redirect(_append_query(redirect_uri, code=code, state=state))

            redirect_uri, state = deny_authorization_request(request_id, str(user.pk))
            return redirect(
                _append_query(
                    redirect_uri,
                    error='access_denied',
                    error_description='The user denied the FrontMoney authorization request.',
                    state=state,
                )
            )
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))

    scope_labels = {
        'frontmoney.read': 'Просмотр бюджетов, операций, кошельков и портфелей',
        'frontmoney.write': 'Создание, изменение и удаление финансовых записей',
    }
    client_name = pending.client.metadata.get('client_name') or 'Codex MCP client'
    response = render(
        request,
        'mcp_gateway/consent.html',
        {
            'client_name': client_name,
            'request_id': pending.pk,
            'scopes': [scope_labels.get(scope, scope) for scope in pending.scopes],
            'username': user.get_username(),
            'resource': settings.MCP_PUBLIC_URL,
        },
    )
    try:
        redirect_origin = _redirect_origin(pending.redirect_uri)
    except ValueError:
        return HttpResponseBadRequest('OAuth redirect URI is invalid.')
    response['Content-Security-Policy'] = CONSENT_CSP.format(redirect_origin=redirect_origin)
    return response
