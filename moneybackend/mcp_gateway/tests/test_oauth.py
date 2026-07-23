from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from mcp.server.auth.provider import (
    AuthorizationParams,
    AuthorizeError,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull

from mcp_gateway.models import McpOAuthAuthorizationRequest, McpOAuthToken
from mcp_gateway.oauth_provider import (
    READ_SCOPE,
    VALID_SCOPES,
    WRITE_SCOPE,
    FrontMoneyOAuthProvider,
    approve_authorization_request,
    hash_token,
    validate_redirect_uri,
)


@override_settings(
    MCP_ISSUER_URL='https://money.example.test',
    MCP_PUBLIC_URL='https://money.example.test/mcp',
    MCP_OAUTH_ALLOWED_REDIRECT_ORIGINS=[],
    MCP_OAUTH_ACCESS_TOKEN_SECONDS=900,
    MCP_OAUTH_REFRESH_TOKEN_SECONDS=3600,
    MCP_OAUTH_AUTH_CODE_SECONDS=300,
    MCP_OAUTH_REQUEST_SECONDS=600,
)
class OAuthProviderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='alex', password='secret')
        self.provider = FrontMoneyOAuthProvider()
        self.client = OAuthClientInformationFull(
            client_id='codex-test',
            client_id_issued_at=1,
            redirect_uris=['http://127.0.0.1:49152/callback'],
            token_endpoint_auth_method='none',
            grant_types=['authorization_code', 'refresh_token'],
            response_types=['code'],
            scope=' '.join(VALID_SCOPES),
            client_name='Codex test',
        )
        async_to_sync(self.provider.register_client)(self.client)

    def _authorization_code(self):
        redirect = async_to_sync(self.provider.authorize)(
            self.client,
            AuthorizationParams(
                state='state-123',
                scopes=VALID_SCOPES,
                code_challenge='challenge',
                redirect_uri='http://127.0.0.1:49152/callback',
                redirect_uri_provided_explicitly=True,
                resource='https://money.example.test/mcp',
            ),
        )
        self.assertIn('/api/v1/mcp/oauth/consent/', redirect)
        pending = McpOAuthAuthorizationRequest.objects.get()
        raw_code, redirect_uri, state = approve_authorization_request(
            str(pending.pk),
            str(self.user.pk),
        )
        self.assertEqual(redirect_uri, 'http://127.0.0.1:49152/callback')
        self.assertEqual(state, 'state-123')
        return raw_code

    def test_authorization_code_exchange_and_refresh_rotation(self):
        raw_code = self._authorization_code()
        code = async_to_sync(self.provider.load_authorization_code)(self.client, raw_code)
        self.assertIsNotNone(code)

        issued = async_to_sync(self.provider.exchange_authorization_code)(self.client, code)
        self.assertEqual(issued.scope, f'{READ_SCOPE} {WRITE_SCOPE}')
        self.assertIsNotNone(issued.refresh_token)
        self.assertFalse(McpOAuthToken.objects.filter(access_token_hash=issued.access_token).exists())
        self.assertTrue(McpOAuthToken.objects.filter(access_token_hash=hash_token(issued.access_token)).exists())

        access = async_to_sync(self.provider.load_access_token)(issued.access_token)
        self.assertEqual(access.user_id, str(self.user.pk))
        self.assertEqual(access.resource, 'https://money.example.test/mcp')

        refresh = async_to_sync(self.provider.load_refresh_token)(self.client, issued.refresh_token)
        rotated = async_to_sync(self.provider.exchange_refresh_token)(
            self.client,
            refresh,
            [READ_SCOPE],
        )
        self.assertNotEqual(rotated.access_token, issued.access_token)
        self.assertIsNone(async_to_sync(self.provider.load_refresh_token)(self.client, issued.refresh_token))

    def test_authorization_code_is_single_use(self):
        raw_code = self._authorization_code()
        code = async_to_sync(self.provider.load_authorization_code)(self.client, raw_code)
        async_to_sync(self.provider.exchange_authorization_code)(self.client, code)
        with self.assertRaises(TokenError):
            async_to_sync(self.provider.exchange_authorization_code)(self.client, code)

    def test_rejects_wrong_resource(self):
        with self.assertRaises(AuthorizeError) as raised:
            async_to_sync(self.provider.authorize)(
                self.client,
                AuthorizationParams(
                    state=None,
                    scopes=[READ_SCOPE],
                    code_challenge='challenge',
                    redirect_uri='http://127.0.0.1:49152/callback',
                    redirect_uri_provided_explicitly=True,
                    resource='https://attacker.example/mcp',
                ),
            )
        self.assertIn('resource', str(raised.exception).lower())

    def test_redirect_uri_policy(self):
        validate_redirect_uri('http://localhost:54321/callback')
        validate_redirect_uri('http://[::1]:54321/callback')
        with self.assertRaises(RegistrationError):
            validate_redirect_uri('https://attacker.example/callback')
