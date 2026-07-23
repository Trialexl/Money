from django.test import SimpleTestCase

from mcp_gateway.api_proxy import validate_api_path, validate_query


class ApiProxyValidationTests(SimpleTestCase):
    def test_allows_financial_routes(self):
        self.assertEqual(
            validate_api_path('/api/v1/investment/portfolios/123/overview/'),
            '/api/v1/investment/portfolios/123/overview/',
        )

    def test_rejects_non_financial_routes(self):
        for path in [
            '/api/v1/auth/token/',
            '/api/v1/users/',
            '/api/v1/ai/execute/',
            '/api/v1/technical-health/',
            '/api/v1/onec-sync/outbox/',
        ]:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    validate_api_path(path)

    def test_rejects_absolute_encoded_and_traversal_paths(self):
        for path in [
            'https://example.com/api/v1/wallets/',
            '/api/v1/wallets/%2e%2e/users/',
            '/api/v1/wallets/../users/',
            '/api/v1/wallets/?page=1',
        ]:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    validate_api_path(path)

    def test_query_accepts_scalars_and_rejects_nested_objects(self):
        self.assertEqual(
            validate_query({'page': 2, 'status': ['open', 'closed']}),
            {'page': 2, 'status': ['open', 'closed']},
        )
        with self.assertRaises(ValueError):
            validate_query({'filter': {'unsafe': True}})
