from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Literal
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .api_proxy import proxy_api_request


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)

TransactionKind = Literal['income', 'expense', 'transfer']
CatalogKind = Literal['wallet', 'cash_flow_item', 'project']
InvestmentEntity = Literal['portfolio', 'account', 'instrument', 'target_allocation']
MarketDataKind = Literal['price', 'fx_rate']

TRANSACTION_PATHS = {
    'income': '/api/v1/receipts/',
    'expense': '/api/v1/expenditures/',
    'transfer': '/api/v1/transfers/',
}
CATALOG_PATHS = {
    'wallet': '/api/v1/wallets/',
    'cash_flow_item': '/api/v1/cash-flow-items/',
    'project': '/api/v1/projects/',
}
INVESTMENT_PATHS = {
    'portfolio': '/api/v1/investment/portfolios/',
    'account': '/api/v1/investment/accounts/',
    'instrument': '/api/v1/investment/instruments/',
    'target_allocation': '/api/v1/investment/target-allocations/',
}
MARKET_DATA_PATHS = {
    'price': '/api/v1/investment/prices/',
    'fx_rate': '/api/v1/investment/fx-rates/',
}

_agent_api_executor = ContextVar('frontmoney_agent_api_executor', default=None)


def set_agent_api_executor(executor):
    return _agent_api_executor.set(executor)


def reset_agent_api_executor(token):
    _agent_api_executor.reset(token)


def _without_none(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _uuid(value: str, field_name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f'{field_name} must be a valid UUID.') from exc


def _detail_path(collection_path: str, record_id: str, field_name: str = 'record_id') -> str:
    return f'{collection_path}{_uuid(record_id, field_name)}/'


def _require_data(data: dict[str, Any]) -> dict[str, Any]:
    if not data:
        raise ValueError('Provide at least one field.')
    return data


async def _call(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    executor = _agent_api_executor.get()
    if executor is None:
        response = await proxy_api_request(method, path, query=query, payload=payload)
    else:
        response = await executor(method, path, query=query, payload=payload)
    status = response['status']
    if 200 <= status < 300:
        return response['data']
    raise ValueError(f'FrontMoney rejected the operation (status {status}): {response["data"]}')


def register_domain_tools(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def list_wallets() -> Any:
        """List the user's visible wallets with names and UUIDs."""
        return await _call('GET', '/api/v1/wallets/')

    @mcp.tool(annotations=READ_ONLY)
    async def get_wallet(
        wallet_id: str,
        view: Literal['details', 'balance', 'summary'] = 'summary',
        as_of: str | None = None,
    ) -> Any:
        """Get wallet details, its balance as of an ISO date, or its operation summary."""
        base = _detail_path('/api/v1/wallets/', wallet_id, 'wallet_id')
        if view == 'details':
            if as_of is not None:
                raise ValueError('as_of is supported only for view="balance".')
            return await _call('GET', base)
        if view == 'balance':
            return await _call('GET', f'{base}balance/', query=_without_none(date=as_of))
        if as_of is not None:
            raise ValueError('as_of is supported only for view="balance".')
        return await _call('GET', f'{base}summary/')

    @mcp.tool(annotations=READ_ONLY)
    async def get_all_wallet_balances(as_of: str | None = None) -> Any:
        """Get non-zero wallet balances in RUB as of an ISO date; defaults to now."""
        return await _call(
            'GET',
            '/api/v1/wallets/balances/',
            query=_without_none(date=as_of),
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_cash_flow_items(
        view: Literal['flat', 'hierarchy', 'summary'] = 'flat',
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> Any:
        """List cash-flow categories, their hierarchy, or totals for an ISO-date period."""
        if view != 'summary' and (date_from is not None or date_to is not None):
            raise ValueError('Date filters are supported only for view="summary".')
        path = {
            'flat': '/api/v1/cash-flow-items/',
            'hierarchy': '/api/v1/cash-flow-items/hierarchy/',
            'summary': '/api/v1/cash-flow-items/summary/',
        }[view]
        return await _call(
            'GET',
            path,
            query=_without_none(date_from=date_from, date_to=date_to),
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_transactions(
        kind: TransactionKind,
        search: str | None = None,
        wallet_id: str | None = None,
        cash_flow_item_id: str | None = None,
        wallet_from_id: str | None = None,
        wallet_to_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        amount_min: str | None = None,
        amount_max: str | None = None,
        include_in_budget: bool | None = None,
    ) -> Any:
        """List income, expense, or transfer documents using financial filters."""
        if kind == 'transfer':
            if wallet_id is not None or cash_flow_item_id is not None or include_in_budget is not None:
                raise ValueError('For transfers use wallet_from_id and wallet_to_id.')
            query = _without_none(
                search=search,
                wallet_from=_uuid(wallet_from_id, 'wallet_from_id') if wallet_from_id else None,
                wallet_to=_uuid(wallet_to_id, 'wallet_to_id') if wallet_to_id else None,
                date_from=date_from,
                date_to=date_to,
                amount_min=amount_min,
                amount_max=amount_max,
            )
        else:
            if wallet_from_id is not None or wallet_to_id is not None:
                raise ValueError('wallet_from_id and wallet_to_id apply only to transfers.')
            if kind == 'income' and include_in_budget is not None:
                raise ValueError('include_in_budget applies only to expenses.')
            query = _without_none(
                search=search,
                wallet=_uuid(wallet_id, 'wallet_id') if wallet_id else None,
                cash_flow_item=_uuid(cash_flow_item_id, 'cash_flow_item_id')
                if cash_flow_item_id
                else None,
                date_from=date_from,
                date_to=date_to,
                amount_min=amount_min,
                amount_max=amount_max,
                include_in_budget=include_in_budget,
            )
        return await _call('GET', TRANSACTION_PATHS[kind], query=query)

    @mcp.tool(annotations=READ_ONLY)
    async def get_transaction(kind: TransactionKind, transaction_id: str) -> Any:
        """Get one income, expense, or transfer document by UUID."""
        return await _call(
            'GET',
            _detail_path(TRANSACTION_PATHS[kind], transaction_id, 'transaction_id'),
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_budgets(
        budget_type: Literal['income', 'expense'] | None = None,
        budget_id: str | None = None,
    ) -> Any:
        """List budgets by type or retrieve one budget document."""
        if budget_id:
            return await _call('GET', _detail_path('/api/v1/budgets/', budget_id, 'budget_id'))
        return await _call('GET', '/api/v1/budgets/', query=_without_none(type=budget_type))

    @mcp.tool(annotations=READ_ONLY)
    async def list_auto_payments(
        is_transfer: bool | None = None,
        auto_payment_id: str | None = None,
    ) -> Any:
        """List recurring payments/transfers or retrieve one recurring document."""
        if auto_payment_id:
            return await _call(
                'GET',
                _detail_path('/api/v1/auto-payments/', auto_payment_id, 'auto_payment_id'),
            )
        return await _call(
            'GET',
            '/api/v1/auto-payments/',
            query=_without_none(is_transfer=is_transfer),
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_projects(project_id: str | None = None) -> Any:
        """List budgeting projects or retrieve one project by UUID."""
        path = (
            _detail_path('/api/v1/projects/', project_id, 'project_id')
            if project_id
            else '/api/v1/projects/'
        )
        return await _call('GET', path)

    @mcp.tool(annotations=READ_ONLY)
    async def get_dashboard(
        section: Literal['overview', 'recent_activity', 'budget_expense_breakdown'] = 'overview',
        date: str | None = None,
        hide_hidden_wallets: bool = True,
        limit: int = 20,
        cash_flow_item_id: str | None = None,
    ) -> Any:
        """Get dashboard totals, recent activity, or an expense-category breakdown."""
        if section == 'overview':
            path = '/api/v1/dashboard/overview/'
            query = _without_none(date=date, hide_hidden_wallets=hide_hidden_wallets)
        elif section == 'recent_activity':
            path = '/api/v1/dashboard/recent-activity/'
            query = _without_none(
                date=date,
                hide_hidden_wallets=hide_hidden_wallets,
                limit=limit,
            )
        else:
            if not cash_flow_item_id:
                raise ValueError('cash_flow_item_id is required for this section.')
            path = '/api/v1/dashboard/budget-expense-breakdown/'
            query = _without_none(
                date=date,
                cash_flow_item=_uuid(cash_flow_item_id, 'cash_flow_item_id'),
            )
        return await _call('GET', path, query=query)

    @mcp.tool(annotations=READ_ONLY)
    async def get_financial_report(
        report: Literal['cash_flow', 'budget_income', 'budget_expense'],
        date_from: str | None = None,
        date_to: str | None = None,
        wallet_id: str | None = None,
        project_id: str | None = None,
        cash_flow_item_id: str | None = None,
        limit_by_today: bool = False,
        month_day_limit: int | None = None,
    ) -> Any:
        """Build a cash-flow, income-budget, or expense-budget report."""
        if report == 'cash_flow':
            if project_id is not None:
                raise ValueError('project_id applies only to budget reports.')
            path = '/api/v1/reports/cash-flow/'
        else:
            if wallet_id is not None or month_day_limit is not None:
                raise ValueError('wallet_id and month_day_limit apply only to cash-flow reports.')
            path = f'/api/v1/reports/{report.replace("_", "-")}/'
        return await _call(
            'GET',
            path,
            query=_without_none(
                date_from=date_from,
                date_to=date_to,
                wallet=_uuid(wallet_id, 'wallet_id') if wallet_id else None,
                project=_uuid(project_id, 'project_id') if project_id else None,
                cash_flow_item=_uuid(cash_flow_item_id, 'cash_flow_item_id')
                if cash_flow_item_id
                else None,
                limit_by_today=limit_by_today,
                month_day_limit=month_day_limit,
            ),
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_financial_register(
        register: Literal['cash_flow', 'budget_income', 'budget_expense'],
        summary: bool = True,
        wallet_id: str | None = None,
        project_id: str | None = None,
        cash_flow_item_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> Any:
        """Read an accounting register or its aggregate summary."""
        root = {
            'cash_flow': 'flow-of-funds',
            'budget_income': 'budget-income',
            'budget_expense': 'budget-expense',
        }[register]
        if register == 'cash_flow' and project_id is not None:
            raise ValueError('project_id applies only to budget registers.')
        if register != 'cash_flow' and wallet_id is not None:
            raise ValueError('wallet_id applies only to the cash-flow register.')
        suffix = 'summary/' if summary else ''
        return await _call(
            'GET',
            f'/api/v1/{root}/{suffix}',
            query=_without_none(
                wallet=_uuid(wallet_id, 'wallet_id') if wallet_id else None,
                project=_uuid(project_id, 'project_id') if project_id else None,
                cash_flow_item=_uuid(cash_flow_item_id, 'cash_flow_item_id')
                if cash_flow_item_id
                else None,
                date_from=date_from,
                date_to=date_to,
            ),
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_investment_records(
        entity: InvestmentEntity,
        record_id: str | None = None,
        portfolio_id: str | None = None,
        instrument_id: str | None = None,
        instrument_type: Literal['crypto', 'stock', 'bond'] | None = None,
        is_active: bool | None = None,
        hidden: bool | None = None,
        search: str | None = None,
    ) -> Any:
        """List or retrieve portfolios, accounts, instruments, or target allocations."""
        path = INVESTMENT_PATHS[entity]
        if record_id:
            return await _call('GET', _detail_path(path, record_id))
        return await _call(
            'GET',
            path,
            query=_without_none(
                portfolio=_uuid(portfolio_id, 'portfolio_id') if portfolio_id else None,
                instrument=_uuid(instrument_id, 'instrument_id') if instrument_id else None,
                type=instrument_type,
                is_active=is_active,
                hidden=hidden,
                search=search,
            ),
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_investment_operations(
        operation_id: str | None = None,
        portfolio_id: str | None = None,
        account_id: str | None = None,
        instrument_id: str | None = None,
        operation_type: Literal[
            'buy', 'sell', 'transfer_instrument', 'correction', 'dividend', 'split'
        ]
        | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        display_currency: Literal['USD', 'EUR', 'RUB'] = 'USD',
        include_deleted: bool = False,
    ) -> Any:
        """List investment operations with filters or retrieve one operation."""
        path = '/api/v1/investment/operations/'
        if operation_id:
            return await _call('GET', _detail_path(path, operation_id, 'operation_id'))
        return await _call(
            'GET',
            path,
            query=_without_none(
                portfolio=_uuid(portfolio_id, 'portfolio_id') if portfolio_id else None,
                account=_uuid(account_id, 'account_id') if account_id else None,
                instrument=_uuid(instrument_id, 'instrument_id') if instrument_id else None,
                operation_type=operation_type,
                date_from=date_from,
                date_to=date_to,
                display_currency=display_currency,
                deleted=True if include_deleted else None,
            ),
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_portfolio_analysis(
        view: Literal['overview', 'positions', 'performance', 'rebalance'] = 'overview',
        portfolio_id: str | None = None,
        display_currency: Literal['USD', 'EUR', 'RUB'] = 'USD',
        date_from: str | None = None,
        date_to: str | None = None,
        group_by: Literal['day', 'month'] = 'month',
        scope: Literal['portfolio', 'instrument', 'all'] = 'portfolio',
        instrument_id: str | None = None,
    ) -> Any:
        """Get portfolio valuation, positions, performance, or rebalancing status."""
        if view == 'overview' and portfolio_id is None:
            return await _call(
                'GET',
                '/api/v1/investment/portfolio-overview/',
                query={'display_currency': display_currency},
            )
        if portfolio_id is None:
            raise ValueError('portfolio_id is required for this view.')
        base = _detail_path('/api/v1/investment/portfolios/', portfolio_id, 'portfolio_id')
        query = {'display_currency': display_currency}
        if view == 'performance':
            query.update(
                _without_none(
                    date_from=date_from,
                    date_to=date_to,
                    group_by=group_by,
                    scope=scope,
                    instrument=_uuid(instrument_id, 'instrument_id') if instrument_id else None,
                )
            )
        elif date_from or date_to or instrument_id or scope != 'portfolio':
            raise ValueError('Date, scope, and instrument filters apply only to performance.')
        return await _call('GET', f'{base}{view}/', query=query)

    @mcp.tool(annotations=READ_ONLY)
    async def list_market_data(
        kind: MarketDataKind,
        record_id: str | None = None,
        instrument_id: str | None = None,
        base_currency: str | None = None,
        quote_currency: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        source: str | None = None,
    ) -> Any:
        """List or retrieve instrument-price or FX-rate snapshots."""
        path = MARKET_DATA_PATHS[kind]
        if record_id:
            return await _call('GET', _detail_path(path, record_id))
        if kind == 'price' and (base_currency or quote_currency):
            raise ValueError('Currency filters apply only to FX rates.')
        if kind == 'fx_rate' and instrument_id:
            raise ValueError('instrument_id applies only to prices.')
        return await _call(
            'GET',
            path,
            query=_without_none(
                instrument=_uuid(instrument_id, 'instrument_id') if instrument_id else None,
                base_currency=base_currency,
                quote_currency=quote_currency,
                date_from=date_from,
                date_to=date_to,
                source=source,
            ),
        )

    @mcp.tool(annotations=READ_ONLY)
    async def lookup_instrument_price(instrument_id: str, date: str) -> Any:
        """Find the exact or nearest previous instrument price for an ISO date."""
        return await _call(
            'GET',
            '/api/v1/investment/prices/lookup/',
            query={'instrument': _uuid(instrument_id, 'instrument_id'), 'date': date},
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_market_data_health(max_age_days: int = 2) -> Any:
        """Check freshness of portfolio price and FX snapshots."""
        return await _call(
            'GET',
            '/api/v1/investment/market-health/',
            query={'max_age_days': max_age_days},
        )

    @mcp.tool(annotations=WRITE)
    async def create_finance_catalog_record(
        kind: CatalogKind,
        name: str,
        hidden: bool | None = None,
        include_in_budget: bool | None = None,
        parent_id: str | None = None,
    ) -> Any:
        """Create a wallet, cash-flow category, or project."""
        if kind != 'wallet' and hidden is not None:
            raise ValueError('hidden applies only to wallets.')
        if kind != 'cash_flow_item' and (include_in_budget is not None or parent_id):
            raise ValueError('include_in_budget and parent_id apply only to categories.')
        return await _call(
            'POST',
            CATALOG_PATHS[kind],
            payload=_without_none(
                name=name,
                hidden=hidden,
                include_in_budget=include_in_budget,
                parent=_uuid(parent_id, 'parent_id') if parent_id else None,
            ),
        )

    @mcp.tool(annotations=WRITE)
    async def update_finance_catalog_record(
        kind: CatalogKind,
        record_id: str,
        name: str | None = None,
        hidden: bool | None = None,
        include_in_budget: bool | None = None,
        parent_id: str | None = None,
        clear_parent: bool = False,
    ) -> Any:
        """Partially update a wallet, cash-flow category, or project."""
        if kind != 'wallet' and hidden is not None:
            raise ValueError('hidden applies only to wallets.')
        if kind != 'cash_flow_item' and (include_in_budget is not None or parent_id or clear_parent):
            raise ValueError('Category hierarchy fields apply only to categories.')
        if parent_id and clear_parent:
            raise ValueError('Use either parent_id or clear_parent.')
        changes = _without_none(
            name=name,
            hidden=hidden,
            include_in_budget=include_in_budget,
            parent=_uuid(parent_id, 'parent_id') if parent_id else None,
        )
        if clear_parent:
            changes['parent'] = None
        return await _call(
            'PATCH',
            _detail_path(CATALOG_PATHS[kind], record_id),
            payload=_require_data(changes),
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def delete_finance_catalog_record(kind: CatalogKind, record_id: str) -> Any:
        """Delete a wallet, cash-flow category, or project after confirmation."""
        return await _call('DELETE', _detail_path(CATALOG_PATHS[kind], record_id))

    @mcp.tool(annotations=WRITE)
    async def create_transaction(
        kind: TransactionKind,
        amount: str,
        date: str,
        comment: str = '',
        wallet_id: str | None = None,
        cash_flow_item_id: str | None = None,
        wallet_from_id: str | None = None,
        wallet_to_id: str | None = None,
        include_in_budget: bool | None = None,
        posted: bool = True,
    ) -> Any:
        """Create income, expense, or a transfer using a decimal-string amount."""
        data = _without_none(amount=amount, date=date, comment=comment, posted=posted)
        if kind == 'transfer':
            if not wallet_from_id or not wallet_to_id:
                raise ValueError('wallet_from_id and wallet_to_id are required.')
            if wallet_id:
                raise ValueError('wallet_id is not used for transfers.')
            data.update(
                _without_none(
                    wallet_out=_uuid(wallet_from_id, 'wallet_from_id'),
                    wallet_in=_uuid(wallet_to_id, 'wallet_to_id'),
                    cash_flow_item=_uuid(cash_flow_item_id, 'cash_flow_item_id')
                    if cash_flow_item_id
                    else None,
                    include_in_budget=include_in_budget,
                )
            )
        else:
            if not wallet_id or not cash_flow_item_id:
                raise ValueError('wallet_id and cash_flow_item_id are required.')
            if wallet_from_id or wallet_to_id:
                raise ValueError('wallet_from_id and wallet_to_id apply only to transfers.')
            if kind == 'income' and include_in_budget is not None:
                raise ValueError('include_in_budget applies only to expenses and transfers.')
            data.update(
                _without_none(
                    wallet=_uuid(wallet_id, 'wallet_id'),
                    cash_flow_item=_uuid(cash_flow_item_id, 'cash_flow_item_id'),
                    include_in_budget=include_in_budget,
                )
            )
        return await _call('POST', TRANSACTION_PATHS[kind], payload=data)

    @mcp.tool(annotations=WRITE)
    async def update_transaction(
        kind: TransactionKind,
        transaction_id: str,
        changes: dict[str, Any],
    ) -> Any:
        """Partially update a transaction. Common fields: amount, date, comment, posted; income/expense: wallet, cash_flow_item; expense/transfer: include_in_budget; transfer: wallet_out, wallet_in."""
        return await _call(
            'PATCH',
            _detail_path(TRANSACTION_PATHS[kind], transaction_id, 'transaction_id'),
            payload=_require_data(changes),
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def delete_transaction(kind: TransactionKind, transaction_id: str) -> Any:
        """Soft-delete one income, expense, or transfer after confirmation."""
        return await _call(
            'DELETE',
            _detail_path(TRANSACTION_PATHS[kind], transaction_id, 'transaction_id'),
        )

    @mcp.tool(annotations=WRITE)
    async def create_budget(
        budget_type: Literal['income', 'expense'],
        amount: str,
        date_start: str,
        cash_flow_item_id: str,
        months: int = 12,
        project_id: str | None = None,
        date: str | None = None,
        comment: str = '',
        posted: bool = True,
    ) -> Any:
        """Create an income or expense budget document."""
        return await _call(
            'POST',
            '/api/v1/budgets/',
            payload=_without_none(
                type_of_budget=budget_type == 'income',
                amount=amount,
                date_start=date_start,
                amount_month=months,
                cash_flow_item=_uuid(cash_flow_item_id, 'cash_flow_item_id'),
                project=_uuid(project_id, 'project_id') if project_id else None,
                date=date,
                comment=comment,
                posted=posted,
            ),
        )

    @mcp.tool(annotations=WRITE)
    async def update_budget(budget_id: str, changes: dict[str, Any]) -> Any:
        """Partially update a budget. Fields: type_of_budget, amount, date_start, amount_month, cash_flow_item, project, date, comment, posted."""
        return await _call(
            'PATCH',
            _detail_path('/api/v1/budgets/', budget_id, 'budget_id'),
            payload=_require_data(changes),
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def delete_budget(budget_id: str) -> Any:
        """Soft-delete one budget after confirmation."""
        return await _call('DELETE', _detail_path('/api/v1/budgets/', budget_id, 'budget_id'))

    @mcp.tool(annotations=WRITE)
    async def create_auto_payment(
        amount: str,
        date_start: str,
        wallet_from_id: str,
        months: int = 12,
        is_transfer: bool = False,
        wallet_to_id: str | None = None,
        cash_flow_item_id: str | None = None,
        comment: str = '',
    ) -> Any:
        """Create a recurring expense or recurring wallet transfer."""
        if is_transfer and not wallet_to_id:
            raise ValueError('wallet_to_id is required for a recurring transfer.')
        if not is_transfer and not cash_flow_item_id:
            raise ValueError('cash_flow_item_id is required for a recurring expense.')
        return await _call(
            'POST',
            '/api/v1/auto-payments/',
            payload=_without_none(
                amount=amount,
                date_start=date_start,
                amount_month=months,
                wallet_out=_uuid(wallet_from_id, 'wallet_from_id'),
                wallet_in=_uuid(wallet_to_id, 'wallet_to_id') if wallet_to_id else None,
                cash_flow_item=_uuid(cash_flow_item_id, 'cash_flow_item_id')
                if cash_flow_item_id
                else None,
                is_transfer=is_transfer,
                comment=comment,
            ),
        )

    @mcp.tool(annotations=WRITE)
    async def update_auto_payment(auto_payment_id: str, changes: dict[str, Any]) -> Any:
        """Partially update a recurring payment. Fields: amount, date_start, amount_month, wallet_out, wallet_in, cash_flow_item, is_transfer, date, comment, posted."""
        return await _call(
            'PATCH',
            _detail_path('/api/v1/auto-payments/', auto_payment_id, 'auto_payment_id'),
            payload=_require_data(changes),
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def delete_auto_payment(auto_payment_id: str) -> Any:
        """Soft-delete one recurring payment after confirmation."""
        return await _call(
            'DELETE',
            _detail_path('/api/v1/auto-payments/', auto_payment_id, 'auto_payment_id'),
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def generate_planning_schedule(
        document: Literal['budget', 'auto_payment'],
        record_id: str,
        amount: str | None = None,
        months: int | None = None,
        date_start: str | None = None,
        monthly_amount: str | None = None,
        without_rounding: bool = False,
    ) -> Any:
        """Regenerate every schedule row for a budget or recurring payment."""
        root = 'budgets' if document == 'budget' else 'auto-payments'
        return await _call(
            'POST',
            f'/api/v1/{root}/{_uuid(record_id, "record_id")}/generate-graphics/',
            payload=_without_none(
                amount=amount,
                amount_month=months,
                date_start=date_start,
                monthly_amount=monthly_amount,
                without_rounding=without_rounding,
            ),
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def replace_financial_schedule(
        document: Literal['expense', 'transfer', 'budget', 'auto_payment'],
        record_id: str,
        rows: list[dict[str, str]],
    ) -> Any:
        """Replace every schedule row; each row needs date_start and decimal-string amount."""
        root = {
            'expense': 'expenditures',
            'transfer': 'transfers',
            'budget': 'budgets',
            'auto_payment': 'auto-payments',
        }[document]
        for index, row in enumerate(rows):
            if set(row) != {'date_start', 'amount'}:
                raise ValueError(f'rows[{index}] must contain only date_start and amount.')
        return await _call(
            'PUT',
            f'/api/v1/{root}/{_uuid(record_id, "record_id")}/replace-graphics/',
            payload={'rows': rows},
        )

    @mcp.tool(annotations=WRITE)
    async def create_investment_record(
        entity: InvestmentEntity,
        data: dict[str, Any],
    ) -> Any:
        """Create an investment entity. Portfolio fields: name, project, is_default. Account: portfolio, name, type, currency, hidden. Instrument: type, ticker, name, provider_symbol, quote_currency, precision, is_active. Target allocation: portfolio, instrument, target_percent, tolerance_percent."""
        return await _call(
            'POST',
            INVESTMENT_PATHS[entity],
            payload=_require_data(data),
        )

    @mcp.tool(annotations=WRITE)
    async def update_investment_record(
        entity: InvestmentEntity,
        record_id: str,
        changes: dict[str, Any],
    ) -> Any:
        """Partially update a portfolio, account, instrument, or target allocation."""
        return await _call(
            'PATCH',
            _detail_path(INVESTMENT_PATHS[entity], record_id),
            payload=_require_data(changes),
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def delete_investment_record(
        entity: InvestmentEntity,
        record_id: str,
    ) -> Any:
        """Delete a portfolio, account, instrument, or target allocation after confirmation."""
        return await _call('DELETE', _detail_path(INVESTMENT_PATHS[entity], record_id))

    @mcp.tool(annotations=WRITE)
    async def create_investment_operation(
        portfolio_id: str,
        account_id: str,
        instrument_id: str,
        operation_type: Literal[
            'buy', 'sell', 'transfer_instrument', 'correction', 'dividend', 'split'
        ],
        date: str,
        quantity: str,
        amount_usd: str,
        price_usd: str | None = None,
        fee_usd: str = '0.00',
        account_to_id: str | None = None,
        comment: str = '',
    ) -> Any:
        """Create one investment operation using decimal strings for numeric values."""
        return await _call(
            'POST',
            '/api/v1/investment/operations/',
            payload=_without_none(
                portfolio=_uuid(portfolio_id, 'portfolio_id'),
                account=_uuid(account_id, 'account_id'),
                account_to=_uuid(account_to_id, 'account_to_id') if account_to_id else None,
                instrument=_uuid(instrument_id, 'instrument_id'),
                operation_type=operation_type,
                date=date,
                quantity=quantity,
                price_usd=price_usd,
                amount_usd=amount_usd,
                fee_usd=fee_usd,
                comment=comment,
            ),
        )

    @mcp.tool(annotations=WRITE)
    async def update_investment_operation(
        operation_id: str,
        changes: dict[str, Any],
    ) -> Any:
        """Partially update an operation. Fields: portfolio, account, account_to, instrument, operation_type, date, quantity, price_usd, amount_usd, fee_usd, comment, posted."""
        return await _call(
            'PATCH',
            _detail_path('/api/v1/investment/operations/', operation_id, 'operation_id'),
            payload=_require_data(changes),
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def delete_investment_operation(operation_id: str) -> Any:
        """Delete one investment operation after confirmation."""
        return await _call(
            'DELETE',
            _detail_path('/api/v1/investment/operations/', operation_id, 'operation_id'),
        )

    @mcp.tool(annotations=WRITE)
    async def record_market_data(kind: MarketDataKind, data: dict[str, Any]) -> Any:
        """Record market data. Price fields: instrument, captured_at, price, price_currency, fx_rate_to_usd, source. FX fields: captured_at, base_currency, quote_currency, rate, source."""
        return await _call(
            'POST',
            MARKET_DATA_PATHS[kind],
            payload=_require_data(data),
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def refresh_market_data(kind: MarketDataKind) -> Any:
        """Refresh current instrument prices or FX rates from configured providers."""
        return await _call('POST', f'{MARKET_DATA_PATHS[kind]}refresh/')

    @mcp.tool(annotations=DESTRUCTIVE)
    async def backfill_market_data(
        kind: MarketDataKind,
        date_from: str,
        date_to: str,
    ) -> Any:
        """Backfill daily price or FX snapshots for an inclusive ISO-date range."""
        return await _call(
            'POST',
            f'{MARKET_DATA_PATHS[kind]}backfill/',
            payload={'date_from': date_from, 'date_to': date_to},
        )
