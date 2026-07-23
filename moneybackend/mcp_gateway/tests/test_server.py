from django.test import SimpleTestCase, TransactionTestCase
from starlette.testclient import TestClient

from mcp_gateway.combined import application as app
from mcp_gateway.server import mcp


class McpServerMetadataTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client_context = TestClient(app)
        cls.mcp_client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        super().tearDownClass()

    def test_oauth_metadata_advertises_public_pkce(self):
        response = self.mcp_client.get('/.well-known/oauth-authorization-server')
        self.assertEqual(response.status_code, 200)
        metadata = response.json()
        self.assertEqual(metadata['token_endpoint_auth_methods_supported'], ['none'])
        self.assertEqual(metadata['code_challenge_methods_supported'], ['S256'])
        self.assertIn('frontmoney.read', metadata['scopes_supported'])

    def test_mcp_endpoint_requires_bearer_token(self):
        response = self.mcp_client.post('/mcp', json={})
        self.assertEqual(response.status_code, 401)
        self.assertIn('resource_metadata=', response.headers['www-authenticate'])

    def test_django_health_endpoint_uses_same_asgi_process(self):
        response = self.mcp_client.get('/api/v1/health/', headers={'Host': 'localhost'})
        self.assertEqual(response.status_code, 200)


class McpDomainToolContractTests(SimpleTestCase):
    def test_server_exposes_domain_tools_instead_of_http_proxy_tools(self):
        tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}

        self.assertNotIn('frontmoney_read', tools)
        self.assertNotIn('frontmoney_write', tools)
        self.assertGreaterEqual(len(tools), 30)
        self.assertIn('list_wallets', tools)
        self.assertIn('list_transactions', tools)
        self.assertIn('get_financial_report', tools)
        self.assertIn('get_portfolio_analysis', tools)
        self.assertIn('create_transaction', tools)

        for tool in tools.values():
            properties = tool.parameters.get('properties', {})
            self.assertNotIn('path', properties, tool.name)
            self.assertNotIn('method', properties, tool.name)

    def test_tool_annotations_separate_reads_from_destructive_changes(self):
        read_tool = mcp._tool_manager.get_tool('get_portfolio_analysis')
        delete_tool = mcp._tool_manager.get_tool('delete_transaction')

        self.assertTrue(read_tool.annotations.readOnlyHint)
        self.assertFalse(read_tool.annotations.destructiveHint)
        self.assertFalse(delete_tool.annotations.readOnlyHint)
        self.assertTrue(delete_tool.annotations.destructiveHint)
