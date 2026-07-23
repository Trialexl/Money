import asyncio
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from mcp_gateway.server import mcp


class McpDomainToolRoutingTests(SimpleTestCase):
    @patch('mcp_gateway.domain_tools.proxy_api_request', new_callable=AsyncMock)
    def test_expense_list_maps_domain_filters_internally(self, proxy):
        proxy.return_value = {'status': 200, 'data': {'results': []}}
        tool = mcp._tool_manager.get_tool('list_transactions')

        result = asyncio.run(
            tool.fn(
                kind='expense',
                wallet_id='11111111-1111-1111-1111-111111111111',
                date_from='2026-07-01',
                date_to='2026-07-31',
                include_in_budget=True,
            )
        )

        self.assertEqual(result, {'results': []})
        proxy.assert_awaited_once_with(
            'GET',
            '/api/v1/expenditures/',
            query={
                'wallet': '11111111-1111-1111-1111-111111111111',
                'date_from': '2026-07-01',
                'date_to': '2026-07-31',
                'include_in_budget': True,
            },
            payload=None,
        )

    @patch('mcp_gateway.domain_tools.proxy_api_request', new_callable=AsyncMock)
    def test_transfer_tool_maps_wallet_roles_internally(self, proxy):
        proxy.return_value = {'status': 201, 'data': {'id': 'created'}}
        tool = mcp._tool_manager.get_tool('create_transaction')

        result = asyncio.run(
            tool.fn(
                kind='transfer',
                amount='2500.00',
                date='2026-07-23T12:00:00+03:00',
                wallet_from_id='11111111-1111-1111-1111-111111111111',
                wallet_to_id='22222222-2222-2222-2222-222222222222',
            )
        )

        self.assertEqual(result, {'id': 'created'})
        proxy.assert_awaited_once_with(
            'POST',
            '/api/v1/transfers/',
            query=None,
            payload={
                'amount': '2500.00',
                'date': '2026-07-23T12:00:00+03:00',
                'comment': '',
                'posted': True,
                'wallet_out': '11111111-1111-1111-1111-111111111111',
                'wallet_in': '22222222-2222-2222-2222-222222222222',
            },
        )
