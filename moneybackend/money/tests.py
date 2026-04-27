import json
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import Mock, patch

from django.forms import inlineformset_factory, modelform_factory
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import CustomUser

from . import ai_service
from .admin import ExpenditureGraphicAdminForm, ExpenditureGraphicInlineFormSet
from .models import (
    AutoPayment,
    AutoPaymentGraphic,
    Budget,
    BudgetExpense,
    BudgetGraphic,
    BudgetIncome,
    CashFlowItem,
    CashFlowItemAlias,
    AiAuditLog,
    AiProcessedInput,
    AiPendingConfirmation,
    Expenditure,
    ExpenditureGraphic,
    FlowOfFunds,
    OneCSyncOutbox,
    Project,
    Receipt,
    Transfer,
    TransferGraphic,
    TelegramUserBinding,
    TelegramLinkToken,
    Wallet,
    WalletAlias,
    sync_document_registers,
)


class MoneyRegisterParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.wallet_main = Wallet.objects.create(name='Основной кошелек')
        cls.wallet_reserve = Wallet.objects.create(name='Резервный кошелек')
        cls.item = CashFlowItem.objects.create(
            name='Аренда',
            include_in_budget=True,
        )

    def make_dt(self, day):
        return timezone.make_aware(datetime(2024, 1, day, 10, 0, 0))

    def test_expenditure_uses_graphics_for_budget_when_rows_cover_amount(self):
        expenditure = Expenditure.objects.create(
            amount=Decimal('1000.00'),
            wallet=self.wallet_main,
            cash_flow_item=self.item,
            include_in_budget=True,
            date=self.make_dt(10),
        )

        ExpenditureGraphic.objects.create(
            document=expenditure,
            date_start=self.make_dt(15),
            amount=Decimal('400.00'),
        )
        ExpenditureGraphic.objects.create(
            document=expenditure,
            date_start=self.make_dt(20),
            amount=Decimal('600.00'),
        )

        sync_document_registers(expenditure)

        budget_rows = list(
            BudgetExpense.objects.filter(document_id=expenditure.id).order_by('period').values_list('period', 'amount')
        )
        flow_rows = list(
            FlowOfFunds.objects.filter(document_id=expenditure.id).values_list('period', 'amount')
        )

        self.assertEqual(
            budget_rows,
            [
                (self.make_dt(15), Decimal('400.00')),
                (self.make_dt(20), Decimal('600.00')),
            ],
        )
        self.assertEqual(flow_rows, [(self.make_dt(10), Decimal('-1000.00'))])

    def test_transfer_uses_graphics_and_remainder_for_budget(self):
        transfer = Transfer.objects.create(
            amount=Decimal('1000.00'),
            wallet_in=self.wallet_reserve,
            wallet_out=self.wallet_main,
            cash_flow_item=self.item,
            include_in_budget=True,
            date=self.make_dt(5),
        )

        TransferGraphic.objects.create(
            document=transfer,
            date_start=self.make_dt(12),
            amount=Decimal('200.00'),
        )
        TransferGraphic.objects.create(
            document=transfer,
            date_start=self.make_dt(19),
            amount=Decimal('300.00'),
        )

        sync_document_registers(transfer)

        budget_rows = list(
            BudgetExpense.objects.filter(document_id=transfer.id).order_by('period', 'amount').values_list('period', 'amount')
        )
        flow_rows = list(
            FlowOfFunds.objects.filter(document_id=transfer.id).order_by('amount').values_list('period', 'amount')
        )

        self.assertEqual(
            budget_rows,
            [
                (self.make_dt(5), Decimal('500.00')),
                (self.make_dt(12), Decimal('200.00')),
                (self.make_dt(19), Decimal('300.00')),
            ],
        )
        self.assertEqual(
            flow_rows,
            [
                (self.make_dt(5), Decimal('-1000.00')),
                (self.make_dt(5), Decimal('1000.00')),
            ],
        )

    def test_budget_uses_budget_graphics_for_registers(self):
        budget = Budget.objects.create(
            amount=Decimal('900.00'),
            amount_month=3,
            date=self.make_dt(1),
            date_start=self.make_dt(7),
            cash_flow_item=self.item,
            type_of_budget=False,
        )

        BudgetGraphic.objects.create(
            document=budget,
            date_start=self.make_dt(8),
            amount=Decimal('300.00'),
        )
        BudgetGraphic.objects.create(
            document=budget,
            date_start=self.make_dt(9),
            amount=Decimal('600.00'),
        )

        sync_document_registers(budget)

        budget_rows = list(
            BudgetExpense.objects.filter(document_id=budget.id).order_by('period').values_list('period', 'amount')
        )

        self.assertEqual(
            budget_rows,
            [
                (self.make_dt(8), Decimal('300.00')),
                (self.make_dt(9), Decimal('600.00')),
            ],
        )

    def test_autopayment_transfer_uses_graphics_for_flow_and_skips_budget(self):
        autopayment = AutoPayment.objects.create(
            amount=Decimal('1000.00'),
            amount_month=2,
            date=self.make_dt(1),
            date_start=self.make_dt(3),
            wallet_in=self.wallet_reserve,
            wallet_out=self.wallet_main,
            cash_flow_item=self.item,
            is_transfer=True,
        )

        AutoPaymentGraphic.objects.create(
            document=autopayment,
            date_start=self.make_dt(11),
            amount=Decimal('400.00'),
        )
        AutoPaymentGraphic.objects.create(
            document=autopayment,
            date_start=self.make_dt(21),
            amount=Decimal('600.00'),
        )

        sync_document_registers(autopayment)

        flow_rows = list(
            FlowOfFunds.objects.filter(document_id=autopayment.id).order_by('period', 'amount').values_list('period', 'amount')
        )
        budget_rows = BudgetExpense.objects.filter(document_id=autopayment.id).count()

        self.assertEqual(
            flow_rows,
            [
                (self.make_dt(11), Decimal('-400.00')),
                (self.make_dt(11), Decimal('400.00')),
                (self.make_dt(21), Decimal('-600.00')),
                (self.make_dt(21), Decimal('600.00')),
            ],
        )
        self.assertEqual(budget_rows, 0)

    def test_unposted_expenditure_does_not_create_register_rows(self):
        expenditure = Expenditure.objects.create(
            amount=Decimal('1000.00'),
            wallet=self.wallet_main,
            cash_flow_item=self.item,
            include_in_budget=True,
            date=self.make_dt(10),
            posted=False,
        )

        self.assertFalse(
            FlowOfFunds.objects.filter(document_id=expenditure.id, type_of_document=expenditure.get_document_type()).exists()
        )
        self.assertFalse(
            BudgetExpense.objects.filter(document_id=expenditure.id, type_of_document=expenditure.get_document_type()).exists()
        )

    def test_unposting_existing_document_clears_register_rows(self):
        expenditure = Expenditure.objects.create(
            amount=Decimal('1000.00'),
            wallet=self.wallet_main,
            cash_flow_item=self.item,
            include_in_budget=True,
            date=self.make_dt(10),
        )

        self.assertTrue(
            FlowOfFunds.objects.filter(document_id=expenditure.id, type_of_document=expenditure.get_document_type()).exists()
        )
        self.assertTrue(
            BudgetExpense.objects.filter(document_id=expenditure.id, type_of_document=expenditure.get_document_type()).exists()
        )

        expenditure.posted = False
        expenditure.save()

        self.assertFalse(
            FlowOfFunds.objects.filter(document_id=expenditure.id, type_of_document=expenditure.get_document_type()).exists()
        )
        self.assertFalse(
            BudgetExpense.objects.filter(document_id=expenditure.id, type_of_document=expenditure.get_document_type()).exists()
        )


class OneCSyncApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='extension-admin',
            email='extension-admin@example.com',
            password='adminpass123',
        )
        cls.token = Token.objects.create(user=cls.admin_user)
        cls.wallet = Wallet.objects.create(name='Основной кошелек')
        cls.item = CashFlowItem.objects.create(name='Аренда', include_in_budget=True)

    def setUp(self):
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {self.token.key}',
            HTTP_X_ONEC_SYNC='1',
        )

    def make_dt(self, day):
        return timezone.make_aware(datetime(2024, 1, day, 10, 0, 0))

    def test_onec_sync_can_restore_soft_deleted_expenditure_before_replacing_graphics(self):
        expenditure = Expenditure.objects.create(
            amount=Decimal('1000.00'),
            wallet=self.wallet,
            cash_flow_item=self.item,
            include_in_budget=True,
            date=self.make_dt(5),
            deleted=True,
        )
        ExpenditureGraphic.objects.create(
            document=expenditure,
            date_start=self.make_dt(15),
            amount=Decimal('1000.00'),
        )

        detail_url = f'/api/v1/expenditures/{expenditure.id}/'
        replace_url = f'/api/v1/expenditures/{expenditure.id}/replace-graphics/'

        head_response = self.client.head(detail_url)
        patch_response = self.client.patch(
            detail_url,
            {
                'amount': '1000.00',
                'date': self.make_dt(5).isoformat(),
                'wallet': str(self.wallet.id),
                'cash_flow_item': str(self.item.id),
                'include_in_budget': True,
                'deleted': False,
            },
            format='json',
        )
        replace_response = self.client.put(
            replace_url,
            {
                'rows': [
                    {
                        'date_start': self.make_dt(10).isoformat(),
                        'amount': '400.00',
                    },
                    {
                        'date_start': self.make_dt(20).isoformat(),
                        'amount': '600.00',
                    },
                ]
            },
            format='json',
        )

        self.assertEqual(head_response.status_code, 200)
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(replace_response.status_code, 200)

        expenditure.refresh_from_db()
        self.assertFalse(expenditure.deleted)
        self.assertEqual(Expenditure.objects.filter(pk=expenditure.id).count(), 1)
        self.assertEqual(
            list(
                expenditure.items.order_by('date_start').values_list('date_start', 'amount')
            ),
            [
                (self.make_dt(10), Decimal('400.00')),
                (self.make_dt(20), Decimal('600.00')),
            ],
        )

    def test_onec_sync_can_replace_transfer_graphics_via_document_endpoint(self):
        transfer = Transfer.objects.create(
            amount=Decimal('1000.00'),
            wallet_in=self.wallet,
            wallet_out=Wallet.objects.create(name='Резервный кошелек'),
            cash_flow_item=self.item,
            include_in_budget=True,
            date=self.make_dt(5),
        )
        TransferGraphic.objects.create(
            document=transfer,
            date_start=self.make_dt(12),
            amount=Decimal('1000.00'),
        )

        replace_response = self.client.put(
            f'/api/v1/transfers/{transfer.id}/replace-graphics/',
            {
                'rows': [
                    {
                        'date_start': self.make_dt(10).isoformat(),
                        'amount': '400.00',
                    },
                    {
                        'date_start': self.make_dt(20).isoformat(),
                        'amount': '600.00',
                    },
                ]
            },
            format='json',
        )

        self.assertEqual(replace_response.status_code, 200)
        self.assertEqual(
            list(
                transfer.items.order_by('date_start').values_list('date_start', 'amount')
            ),
            [
                (self.make_dt(10), Decimal('400.00')),
                (self.make_dt(20), Decimal('600.00')),
            ],
        )
        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=transfer.id)
                .order_by('period')
                .values_list('period', 'amount')
            ),
            [
                (self.make_dt(10), Decimal('400.00')),
                (self.make_dt(20), Decimal('600.00')),
            ],
        )

    def test_onec_sync_can_clear_budget_graphics_via_empty_replace_payload(self):
        budget = Budget.objects.create(
            amount=Decimal('900.00'),
            amount_month=3,
            date=self.make_dt(1),
            date_start=self.make_dt(7),
            cash_flow_item=self.item,
            type_of_budget=False,
        )
        BudgetGraphic.objects.create(
            document=budget,
            date_start=self.make_dt(10),
            amount=Decimal('300.00'),
        )
        BudgetGraphic.objects.create(
            document=budget,
            date_start=self.make_dt(20),
            amount=Decimal('600.00'),
        )
        sync_document_registers(budget)

        replace_response = self.client.put(
            f'/api/v1/budgets/{budget.id}/replace-graphics/',
            {
                'rows': []
            },
            format='json',
        )

        self.assertEqual(replace_response.status_code, 200)
        budget.refresh_from_db()
        self.assertEqual(budget.items.count(), 0)
        self.assertEqual(budget.amount, Decimal('900.00'))
        self.assertEqual(budget.amount_month, 3)
        self.assertEqual(budget.date_start, self.make_dt(7))
        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=budget.id)
                .order_by('period')
                .values_list('period', 'amount')
            ),
            [(self.make_dt(7), Decimal('900.00'))],
        )

    def test_onec_sync_can_replace_autopayment_graphics_via_document_endpoint(self):
        autopayment = AutoPayment.objects.create(
            amount=Decimal('1000.00'),
            amount_month=2,
            date=self.make_dt(1),
            date_start=self.make_dt(3),
            wallet_out=self.wallet,
            cash_flow_item=self.item,
            is_transfer=False,
        )
        AutoPaymentGraphic.objects.create(
            document=autopayment,
            date_start=self.make_dt(15),
            amount=Decimal('1000.00'),
        )

        replace_response = self.client.put(
            f'/api/v1/auto-payments/{autopayment.id}/replace-graphics/',
            {
                'rows': [
                    {
                        'date_start': self.make_dt(11).isoformat(),
                        'amount': '400.00',
                    },
                    {
                        'date_start': self.make_dt(21).isoformat(),
                        'amount': '600.00',
                    },
                ]
            },
            format='json',
        )

        self.assertEqual(replace_response.status_code, 200)
        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=autopayment.id)
                .order_by('period')
                .values_list('period', 'amount')
            ),
            [
                (self.make_dt(11), Decimal('400.00')),
                (self.make_dt(21), Decimal('600.00')),
            ],
        )


class OneCOutboundSyncTests(TransactionTestCase):
    def setUp(self):
        self.admin_user = CustomUser.objects.create_superuser(
            username='outbox-admin',
            email='outbox-admin@example.com',
            password='adminpass123',
        )
        self.token = Token.objects.create(user=self.admin_user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        OneCSyncOutbox.objects.all().delete()

    def make_dt(self, day):
        return timezone.make_aware(datetime(2024, 1, day, 10, 0, 0))

    def test_wallet_save_creates_and_updates_single_outbox_record(self):
        wallet = Wallet.objects.create(name='Кошелек A')

        queue_item = OneCSyncOutbox.objects.get(entity_type='wallet', object_id=wallet.id)
        self.assertEqual(queue_item.route, 'wallets')
        self.assertEqual(queue_item.operation, OneCSyncOutbox.UPSERT)
        self.assertEqual(queue_item.payload['name'], 'Кошелек A')

        first_changed_at = queue_item.changed_at
        wallet.name = 'Кошелек B'
        wallet.save()

        queue_item.refresh_from_db()
        self.assertEqual(OneCSyncOutbox.objects.filter(entity_type='wallet', object_id=wallet.id).count(), 1)
        self.assertEqual(queue_item.payload['name'], 'Кошелек B')
        self.assertGreaterEqual(queue_item.changed_at, first_changed_at)

    def test_graphic_change_queues_parent_document_with_nested_graphics(self):
        wallet = Wallet.objects.create(name='Основной кошелек')
        item = CashFlowItem.objects.create(name='Аренда', include_in_budget=True)
        expenditure = Expenditure.objects.create(
            amount=Decimal('1000.00'),
            wallet=wallet,
            cash_flow_item=item,
            include_in_budget=True,
            date=self.make_dt(5),
        )
        OneCSyncOutbox.objects.all().delete()

        ExpenditureGraphic.objects.create(
            document=expenditure,
            date_start=self.make_dt(10),
            amount=Decimal('1000.00'),
        )

        queue_item = OneCSyncOutbox.objects.get(entity_type='expenditure', object_id=expenditure.id)
        self.assertEqual(queue_item.route, 'expenditures')
        self.assertEqual(queue_item.clear_type, 'ExpenditureGraphics')
        self.assertEqual(queue_item.graphics_route, 'expenditure-graphics')
        self.assertEqual(
            queue_item.payload['graphics'],
            [
                {
                    'date_start': self.make_dt(10).isoformat(),
                    'amount': '1000.00',
                }
            ],
        )
        self.assertTrue(queue_item.payload['posted'])

    def test_document_outbox_payload_reflects_posted_flag(self):
        receipt = Receipt.objects.create(
            amount=Decimal('1000.00'),
            wallet=Wallet.objects.create(name='Кошелек для receipt'),
            cash_flow_item=CashFlowItem.objects.create(name='ЗП для receipt', include_in_budget=True),
            date=self.make_dt(5),
            posted=False,
        )

        queue_item = OneCSyncOutbox.objects.get(entity_type='receipt', object_id=receipt.id)
        self.assertFalse(queue_item.payload['posted'])

    def test_outbox_ack_deletes_records_from_queue(self):
        project = Project.objects.create(name='Проект outbox')
        queue_item = OneCSyncOutbox.objects.get(entity_type='project', object_id=project.id)

        ack_response = self.client.post(
            '/api/v1/onec-sync/outbox/ack/',
            {'ids': [str(queue_item.id)]},
            format='json',
        )
        self.assertEqual(ack_response.status_code, 200)
        self.assertEqual(ack_response.data['deleted_count'], 1)
        self.assertFalse(OneCSyncOutbox.objects.filter(pk=queue_item.pk).exists())

        default_list_response = self.client.get('/api/v1/onec-sync/outbox/')
        self.assertEqual(default_list_response.status_code, 200)
        self.assertEqual(default_list_response.data['count'], 0)

    def test_outbox_limit_query_parameter_limits_results_only(self):
        Project.objects.create(name='Project 1')
        Project.objects.create(name='Project 2')
        Project.objects.create(name='Project 3')

        response = self.client.get('/api/v1/onec-sync/outbox/', {'limit': 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 3)
        self.assertEqual(len(response.data['results']), 2)

    def test_hard_delete_creates_delete_operation_in_outbox(self):
        project = Project.objects.create(name='Удаляемый проект')
        OneCSyncOutbox.objects.all().delete()
        project_id = project.id

        project.delete()

        queue_item = OneCSyncOutbox.objects.get(entity_type='project', object_id=project_id)
        self.assertEqual(queue_item.operation, OneCSyncOutbox.DELETE)
        self.assertEqual(
            queue_item.payload,
            {
                'id': str(project_id),
                'deleted': True,
            },
        )

    def test_onec_header_suppresses_outbox_for_api_writes(self):
        response = self.client.post(
            '/api/v1/wallets/',
            {'name': 'Кошелек из 1С'},
            format='json',
            HTTP_X_ONEC_SYNC='1',
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Wallet.objects.filter(pk=response.data['id']).exists())
        self.assertEqual(OneCSyncOutbox.objects.count(), 0)

    def test_openapi_schema_contains_outbox_endpoints(self):
        response = self.client.get('/api/schema/')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('/api/v1/onec-sync/outbox/', content)
        self.assertIn('/api/v1/onec-sync/outbox/ack/', content)


class OneCScenarioRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.wallet_main = Wallet.objects.create(name='Основной кошелек')
        cls.wallet_reserve = Wallet.objects.create(name='Резервный кошелек')
        cls.project = Project.objects.create(name='Проект 1С')
        cls.income_item = CashFlowItem.objects.create(name='Зарплата', include_in_budget=True)
        cls.expense_item = CashFlowItem.objects.create(name='Аренда', include_in_budget=True)

    def make_dt(self, month, day):
        return timezone.make_aware(datetime(2024, month, day, 10, 0, 0))

    def test_receipt_scenario_creates_one_flow_and_one_budget_income(self):
        receipt = Receipt.objects.create(
            amount=Decimal('5000.00'),
            date=self.make_dt(1, 5),
            wallet=self.wallet_main,
            cash_flow_item=self.income_item,
        )

        self.assertEqual(
            list(
                FlowOfFunds.objects.filter(document_id=receipt.id).values_list('period', 'amount')
            ),
            [(self.make_dt(1, 5), Decimal('5000.00'))],
        )
        self.assertEqual(
            list(
                BudgetIncome.objects.filter(document_id=receipt.id).values_list('period', 'amount')
            ),
            [(self.make_dt(1, 5), Decimal('5000.00'))],
        )

    def test_expenditure_without_distribution_uses_document_date(self):
        expenditure = Expenditure.objects.create(
            amount=Decimal('1200.00'),
            date=self.make_dt(1, 7),
            wallet=self.wallet_main,
            cash_flow_item=self.expense_item,
            include_in_budget=True,
        )

        self.assertEqual(
            list(
                FlowOfFunds.objects.filter(document_id=expenditure.id).values_list('period', 'amount')
            ),
            [(self.make_dt(1, 7), Decimal('-1200.00'))],
        )
        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=expenditure.id).values_list('period', 'amount')
            ),
            [(self.make_dt(1, 7), Decimal('1200.00'))],
        )

    def test_expenditure_with_distribution_uses_graphic_rows(self):
        expenditure = Expenditure.objects.create(
            amount=Decimal('1200.00'),
            date=self.make_dt(1, 7),
            wallet=self.wallet_main,
            cash_flow_item=self.expense_item,
            include_in_budget=True,
        )
        ExpenditureGraphic.objects.create(
            document=expenditure,
            date_start=self.make_dt(1, 15),
            amount=Decimal('700.00'),
        )
        ExpenditureGraphic.objects.create(
            document=expenditure,
            date_start=self.make_dt(2, 15),
            amount=Decimal('500.00'),
        )
        sync_document_registers(expenditure)

        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=expenditure.id).order_by('period').values_list('period', 'amount')
            ),
            [
                (self.make_dt(1, 15), Decimal('700.00')),
                (self.make_dt(2, 15), Decimal('500.00')),
            ],
        )

    def test_transfer_without_budget_creates_only_two_flow_rows(self):
        transfer = Transfer.objects.create(
            amount=Decimal('800.00'),
            date=self.make_dt(1, 9),
            wallet_in=self.wallet_reserve,
            wallet_out=self.wallet_main,
            cash_flow_item=self.expense_item,
            include_in_budget=False,
        )

        self.assertEqual(
            list(
                FlowOfFunds.objects.filter(document_id=transfer.id).order_by('amount').values_list('period', 'amount')
            ),
            [
                (self.make_dt(1, 9), Decimal('-800.00')),
                (self.make_dt(1, 9), Decimal('800.00')),
            ],
        )
        self.assertEqual(BudgetExpense.objects.filter(document_id=transfer.id).count(), 0)

    def test_transfer_with_budget_distribution_uses_rows_and_remainder(self):
        transfer = Transfer.objects.create(
            amount=Decimal('1000.00'),
            date=self.make_dt(1, 9),
            wallet_in=self.wallet_reserve,
            wallet_out=self.wallet_main,
            cash_flow_item=self.expense_item,
            include_in_budget=True,
        )
        TransferGraphic.objects.create(
            document=transfer,
            date_start=self.make_dt(1, 20),
            amount=Decimal('400.00'),
        )
        TransferGraphic.objects.create(
            document=transfer,
            date_start=self.make_dt(2, 20),
            amount=Decimal('100.00'),
        )
        sync_document_registers(transfer)

        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=transfer.id).order_by('period', 'amount').values_list('period', 'amount')
            ),
            [
                (self.make_dt(1, 9), Decimal('500.00')),
                (self.make_dt(1, 20), Decimal('400.00')),
                (self.make_dt(2, 20), Decimal('100.00')),
            ],
        )

    def test_budget_income_and_expense_multi_month_scenarios(self):
        expense_budget = Budget.objects.create(
            amount=Decimal('900.00'),
            amount_month=3,
            date=self.make_dt(1, 1),
            date_start=self.make_dt(1, 5),
            cash_flow_item=self.expense_item,
            project=self.project,
            type_of_budget=False,
        )
        BudgetGraphic.objects.create(document=expense_budget, date_start=self.make_dt(1, 5), amount=Decimal('300.00'))
        BudgetGraphic.objects.create(document=expense_budget, date_start=self.make_dt(2, 5), amount=Decimal('300.00'))
        BudgetGraphic.objects.create(document=expense_budget, date_start=self.make_dt(3, 5), amount=Decimal('300.00'))

        income_budget = Budget.objects.create(
            amount=Decimal('1200.00'),
            amount_month=2,
            date=self.make_dt(1, 1),
            date_start=self.make_dt(1, 10),
            cash_flow_item=self.income_item,
            project=self.project,
            type_of_budget=True,
        )
        BudgetGraphic.objects.create(document=income_budget, date_start=self.make_dt(1, 10), amount=Decimal('600.00'))
        BudgetGraphic.objects.create(document=income_budget, date_start=self.make_dt(2, 10), amount=Decimal('600.00'))
        sync_document_registers(expense_budget)
        sync_document_registers(income_budget)

        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=expense_budget.id).order_by('period').values_list('period', 'amount')
            ),
            [
                (self.make_dt(1, 5), Decimal('300.00')),
                (self.make_dt(2, 5), Decimal('300.00')),
                (self.make_dt(3, 5), Decimal('300.00')),
            ],
        )
        self.assertEqual(
            list(
                BudgetIncome.objects.filter(document_id=income_budget.id).order_by('period').values_list('period', 'amount')
            ),
            [
                (self.make_dt(1, 10), Decimal('600.00')),
                (self.make_dt(2, 10), Decimal('600.00')),
            ],
        )

    def test_autopayment_expense_uses_schedule_for_flow_and_budget(self):
        autopayment = AutoPayment.objects.create(
            amount=Decimal('900.00'),
            amount_month=3,
            date=self.make_dt(1, 1),
            date_start=self.make_dt(1, 12),
            wallet_out=self.wallet_main,
            cash_flow_item=self.expense_item,
            is_transfer=False,
        )
        AutoPaymentGraphic.objects.create(document=autopayment, date_start=self.make_dt(1, 12), amount=Decimal('300.00'))
        AutoPaymentGraphic.objects.create(document=autopayment, date_start=self.make_dt(2, 12), amount=Decimal('300.00'))
        AutoPaymentGraphic.objects.create(document=autopayment, date_start=self.make_dt(3, 12), amount=Decimal('300.00'))
        sync_document_registers(autopayment)

        self.assertEqual(
            list(
                FlowOfFunds.objects.filter(document_id=autopayment.id).order_by('period').values_list('period', 'amount')
            ),
            [
                (self.make_dt(1, 12), Decimal('-300.00')),
                (self.make_dt(2, 12), Decimal('-300.00')),
                (self.make_dt(3, 12), Decimal('-300.00')),
            ],
        )
        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=autopayment.id).order_by('period').values_list('period', 'amount')
            ),
            [
                (self.make_dt(1, 12), Decimal('300.00')),
                (self.make_dt(2, 12), Decimal('300.00')),
                (self.make_dt(3, 12), Decimal('300.00')),
            ],
        )

    def test_autopayment_transfer_uses_schedule_and_skips_budget(self):
        autopayment = AutoPayment.objects.create(
            amount=Decimal('600.00'),
            amount_month=2,
            date=self.make_dt(1, 1),
            date_start=self.make_dt(1, 25),
            wallet_out=self.wallet_main,
            wallet_in=self.wallet_reserve,
            cash_flow_item=self.expense_item,
            is_transfer=True,
        )
        AutoPaymentGraphic.objects.create(document=autopayment, date_start=self.make_dt(1, 25), amount=Decimal('200.00'))
        AutoPaymentGraphic.objects.create(document=autopayment, date_start=self.make_dt(2, 25), amount=Decimal('400.00'))
        sync_document_registers(autopayment)

        self.assertEqual(
            list(
                FlowOfFunds.objects.filter(document_id=autopayment.id).order_by('period', 'amount').values_list('period', 'amount')
            ),
            [
                (self.make_dt(1, 25), Decimal('-200.00')),
                (self.make_dt(1, 25), Decimal('200.00')),
                (self.make_dt(2, 25), Decimal('-400.00')),
                (self.make_dt(2, 25), Decimal('400.00')),
            ],
        )
        self.assertEqual(BudgetExpense.objects.filter(document_id=autopayment.id).count(), 0)


class GraphicApiSyncTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.client_user = CustomUser.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass123',
        )
        cls.item = CashFlowItem.objects.create(
            name='Подписка',
            include_in_budget=True,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.client_user)

    def make_dt(self, day):
        return timezone.make_aware(datetime(2024, 2, day, 9, 0, 0))

    def test_budget_graphic_api_rebuilds_registers(self):
        budget = Budget.objects.create(
            amount=Decimal('400.00'),
            amount_month=1,
            date=self.make_dt(1),
            date_start=self.make_dt(2),
            cash_flow_item=self.item,
            type_of_budget=False,
        )

        response = self.client.post(
            '/api/v1/budget-graphics/',
            {
                'document': str(budget.id),
                'date_start': self.make_dt(10).isoformat(),
                'amount': '400.00',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=budget.id).values_list('period', 'amount')
            ),
            [(self.make_dt(10), Decimal('400.00'))],
        )

    def test_budget_graphic_contract_is_exposed_via_api(self):
        budget = Budget.objects.create(
            amount=Decimal('400.00'),
            amount_month=2,
            date=self.make_dt(1),
            date_start=self.make_dt(2),
            cash_flow_item=self.item,
            type_of_budget=False,
        )

        response = self.client.get(f'/api/v1/budgets/{budget.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['graphic_contract']['header_role'], 'graphic_generation_template')
        self.assertEqual(response.data['graphic_contract']['register_source'], 'graphics_or_header_fallback')
        self.assertEqual(response.data['graphic_contract']['recommended_graphic_action'], 'generate-graphics')
        self.assertFalse(response.data['graphic_contract']['header_updates_from_graphics'])

    def test_transfer_graphic_contract_prefers_replace_graphics(self):
        wallet_in = Wallet.objects.create(name='Кошелек назначения')
        wallet_out = Wallet.objects.create(name='Кошелек списания')
        transfer = Transfer.objects.create(
            amount=Decimal('400.00'),
            date=self.make_dt(1),
            wallet_in=wallet_in,
            wallet_out=wallet_out,
            cash_flow_item=self.item,
            include_in_budget=True,
        )

        response = self.client.get(f'/api/v1/transfers/{transfer.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['graphic_contract']['recommended_graphic_action'], 'replace-graphics')

    def test_direct_budget_graphic_edit_rebuilds_registers_without_rewriting_header(self):
        budget = Budget.objects.create(
            amount=Decimal('400.00'),
            amount_month=3,
            date=self.make_dt(1),
            date_start=self.make_dt(2),
            cash_flow_item=self.item,
            type_of_budget=False,
        )
        row = BudgetGraphic.objects.create(
            document=budget,
            date_start=self.make_dt(10),
            amount=Decimal('400.00'),
        )
        sync_document_registers(budget)

        response = self.client.patch(
            f'/api/v1/budget-graphics/{row.pk}/',
            {
                'amount': '250.00',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        budget.refresh_from_db()
        self.assertEqual(budget.amount, Decimal('400.00'))
        self.assertEqual(budget.amount_month, 3)
        self.assertEqual(budget.date_start, self.make_dt(2))
        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=budget.id).order_by('period').values_list('period', 'amount')
            ),
            [(self.make_dt(10), Decimal('250.00'))],
        )


class ExpenditureDistributionValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='budget-admin',
            email='budget-admin@example.com',
            password='adminpass123',
        )
        cls.wallet = Wallet.objects.create(name='Кошелек расходов')
        cls.item = CashFlowItem.objects.create(
            name='Коммунальные услуги',
            include_in_budget=True,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin_user)

    def make_dt(self, day):
        return timezone.make_aware(datetime(2024, 3, day, 12, 0, 0))

    def make_expenditure(self, amount='1000.00', include_in_budget=True):
        return Expenditure.objects.create(
            amount=Decimal(amount),
            wallet=self.wallet,
            cash_flow_item=self.item,
            include_in_budget=include_in_budget,
            date=self.make_dt(1),
        )

    def test_expenditure_graphic_api_rejects_partial_distribution(self):
        expenditure = self.make_expenditure()

        response = self.client.post(
            '/api/v1/expenditure-graphics/',
            {
                'document': str(expenditure.id),
                'date_start': self.make_dt(10).isoformat(),
                'amount': '400.00',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Сумма строк бюджетного распределения', str(response.data))
        self.assertFalse(ExpenditureGraphic.objects.filter(document=expenditure).exists())

    def test_expenditure_replace_graphics_api_accepts_exact_distribution(self):
        expenditure = self.make_expenditure()

        response = self.client.put(
            f'/api/v1/expenditures/{expenditure.id}/replace-graphics/',
            {
                'rows': [
                    {
                        'date_start': self.make_dt(10).isoformat(),
                        'amount': '400.00',
                    },
                    {
                        'date_start': self.make_dt(20).isoformat(),
                        'amount': '600.00',
                    },
                ]
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=expenditure.id).order_by('period').values_list('period', 'amount')
            ),
            [
                (self.make_dt(10), Decimal('400.00')),
                (self.make_dt(20), Decimal('600.00')),
            ],
        )

    def test_expenditure_api_rejects_amount_change_when_distribution_exists(self):
        expenditure = self.make_expenditure()
        ExpenditureGraphic.objects.create(
            document=expenditure,
            date_start=self.make_dt(10),
            amount=Decimal('400.00'),
        )
        ExpenditureGraphic.objects.create(
            document=expenditure,
            date_start=self.make_dt(20),
            amount=Decimal('600.00'),
        )
        sync_document_registers(expenditure)

        response = self.client.patch(
            f'/api/v1/expenditures/{expenditure.id}/',
            {'amount': '1200.00'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Сумма строк бюджетного распределения', str(response.data))

    def test_expenditure_graphic_api_rejects_delete_when_remainder_is_inexact(self):
        expenditure = self.make_expenditure()
        first_row = ExpenditureGraphic.objects.create(
            document=expenditure,
            date_start=self.make_dt(10),
            amount=Decimal('400.00'),
        )
        ExpenditureGraphic.objects.create(
            document=expenditure,
            date_start=self.make_dt(20),
            amount=Decimal('600.00'),
        )
        sync_document_registers(expenditure)

        response = self.client.delete(
            f'/api/v1/expenditure-graphics/{first_row.pk}/',
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(ExpenditureGraphic.objects.filter(document=expenditure).count(), 2)

    def test_expenditure_inline_formset_rejects_inexact_distribution(self):
        expenditure = self.make_expenditure()
        formset_class = inlineformset_factory(
            Expenditure,
            ExpenditureGraphic,
            formset=ExpenditureGraphicInlineFormSet,
            fields=('date_start', 'amount'),
            extra=0,
        )
        formset = formset_class(
            data={
                'items-TOTAL_FORMS': '2',
                'items-INITIAL_FORMS': '0',
                'items-MIN_NUM_FORMS': '0',
                'items-MAX_NUM_FORMS': '1000',
                'items-0-date_start': self.make_dt(10).isoformat(),
                'items-0-amount': '400.00',
                'items-1-date_start': self.make_dt(20).isoformat(),
                'items-1-amount': '500.00',
            },
            instance=expenditure,
            prefix='items',
        )

        self.assertFalse(formset.is_valid())
        self.assertIn('Сумма строк бюджетного распределения', str(formset.non_form_errors()))

    def test_expenditure_graphic_admin_form_rejects_partial_distribution(self):
        expenditure = self.make_expenditure()
        form = ExpenditureGraphicAdminForm(
            data={
                'document': str(expenditure.id),
                'date_start': self.make_dt(10).isoformat(),
                'amount': '400.00',
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn('Сумма строк бюджетного распределения', str(form.non_field_errors()))


class DocumentRequiredFieldValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='required-admin',
            email='required-admin@example.com',
            password='adminpass123',
        )
        cls.wallet_main = Wallet.objects.create(name='Основной')
        cls.wallet_spare = Wallet.objects.create(name='Резерв')
        cls.item = CashFlowItem.objects.create(name='Зарплата', include_in_budget=True)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin_user)

    def make_dt(self, day):
        return timezone.make_aware(datetime(2024, 4, day, 8, 0, 0))

    def test_receipt_api_requires_wallet_and_item(self):
        response = self.client.post(
            '/api/v1/receipts/',
            {
                'amount': '100.00',
                'date': self.make_dt(1).isoformat(),
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('wallet', response.data)
        self.assertIn('cash_flow_item', response.data)

    def test_expenditure_api_requires_wallet_and_item(self):
        response = self.client.post(
            '/api/v1/expenditures/',
            {
                'amount': '100.00',
                'date': self.make_dt(2).isoformat(),
                'include_in_budget': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('wallet', response.data)
        self.assertIn('cash_flow_item', response.data)

    def test_transfer_api_requires_wallets_and_budget_item(self):
        response = self.client.post(
            '/api/v1/transfers/',
            {
                'amount': '300.00',
                'date': self.make_dt(3).isoformat(),
                'wallet_out': str(self.wallet_main.id),
                'include_in_budget': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('wallet_in', response.data)
        self.assertIn('cash_flow_item', response.data)

    def test_transfer_api_allows_missing_item_when_not_in_budget(self):
        response = self.client.post(
            '/api/v1/transfers/',
            {
                'amount': '300.00',
                'date': self.make_dt(4).isoformat(),
                'wallet_out': str(self.wallet_main.id),
                'wallet_in': str(self.wallet_spare.id),
                'include_in_budget': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)

    def test_autopayment_api_requires_mode_specific_fields(self):
        payment_response = self.client.post(
            '/api/v1/auto-payments/',
            {
                'amount': '500.00',
                'amount_month': 1,
                'date': self.make_dt(5).isoformat(),
                'date_start': self.make_dt(10).isoformat(),
                'is_transfer': False,
            },
            format='json',
        )

        self.assertEqual(payment_response.status_code, 400)
        self.assertIn('wallet_out', payment_response.data)
        self.assertIn('cash_flow_item', payment_response.data)

        transfer_response = self.client.post(
            '/api/v1/auto-payments/',
            {
                'amount': '500.00',
                'amount_month': 1,
                'date': self.make_dt(6).isoformat(),
                'date_start': self.make_dt(10).isoformat(),
                'is_transfer': True,
                'wallet_out': str(self.wallet_main.id),
            },
            format='json',
        )

        self.assertEqual(transfer_response.status_code, 400)
        self.assertIn('wallet_in', transfer_response.data)
        self.assertNotIn('cash_flow_item', transfer_response.data)

    def test_admin_form_uses_same_required_field_validation(self):
        auto_payment_form = modelform_factory(AutoPayment, fields='__all__')
        form = auto_payment_form(
            data={
                'date': self.make_dt(7).isoformat(),
                'amount': '500.00',
                'amount_month': 1,
                'date_start': self.make_dt(9).isoformat(),
                'is_transfer': False,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn('wallet_out', form.errors)
        self.assertIn('cash_flow_item', form.errors)


class JwtWriteAuthenticationRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='jwt-admin',
            email='jwt-admin@example.com',
            password='adminpass123',
        )
        cls.wallet = Wallet.objects.create(name='JWT кошелек')
        cls.item = CashFlowItem.objects.create(name='JWT статья', include_in_budget=True)

    def make_dt(self, day):
        return timezone.make_aware(datetime(2024, 4, day, 9, 0, 0))

    def test_expenditure_create_prefers_bearer_auth_over_session_and_skips_csrf_requirement(self):
        client = APIClient(enforce_csrf_checks=True)
        login_ok = client.login(username='jwt-admin', password='adminpass123')
        access_token = str(RefreshToken.for_user(self.admin_user).access_token)
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')

        response = client.post(
            '/api/v1/expenditures/',
            {
                'amount': '852.00',
                'date': self.make_dt(24).isoformat(),
                'wallet': str(self.wallet.id),
                'cash_flow_item': str(self.item.id),
                'include_in_budget': True,
            },
            format='json',
        )

        self.assertTrue(login_ok)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(
            Expenditure.objects.filter(
                amount=Decimal('852.00'),
                wallet=self.wallet,
                cash_flow_item=self.item,
            ).exists()
        )


class FinancialOperationCatalogApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='catalog-admin',
            email='catalog-admin@example.com',
            password='adminpass123',
        )
        cls.wallet_main = Wallet.objects.create(name='Основной кошелек')
        cls.wallet_secondary = Wallet.objects.create(name='Резервный кошелек')
        cls.wallet_target = Wallet.objects.create(name='Целевой кошелек')
        cls.item_salary = CashFlowItem.objects.create(name='Зарплата', include_in_budget=True)
        cls.item_transport = CashFlowItem.objects.create(name='Транспорт', include_in_budget=True)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin_user)

    def make_dt(self, day):
        return timezone.make_aware(datetime(2024, 4, day, 10, 0, 0))

    def test_receipts_list_is_paginated_with_default_page_size(self):
        for day in range(1, 26):
            Receipt.objects.create(
                date=self.make_dt(day),
                amount=Decimal('100.00') + Decimal(day),
                comment=f'Приход {day}',
                wallet=self.wallet_main,
                cash_flow_item=self.item_salary,
            )

        response = self.client.get('/api/v1/receipts/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 25)
        self.assertEqual(len(response.data['results']), 20)
        self.assertIsNotNone(response.data['next'])
        self.assertIsNone(response.data['previous'])

    def test_receipts_list_accepts_only_supported_page_sizes(self):
        for day in range(1, 26):
            Receipt.objects.create(
                date=self.make_dt(day),
                amount=Decimal('50.00') + Decimal(day),
                comment=f'Размер {day}',
                wallet=self.wallet_main,
                cash_flow_item=self.item_salary,
            )

        supported = self.client.get('/api/v1/receipts/', {'page_size': 50})
        fallback = self.client.get('/api/v1/receipts/', {'page_size': 30})

        self.assertEqual(supported.status_code, 200)
        self.assertEqual(len(supported.data['results']), 25)
        self.assertEqual(fallback.status_code, 200)
        self.assertEqual(len(fallback.data['results']), 20)

    def test_expenditures_list_applies_server_side_filters(self):
        target = Expenditure.objects.create(
            date=self.make_dt(10),
            amount=Decimal('250.00'),
            comment='Такси до офиса',
            wallet=self.wallet_main,
            cash_flow_item=self.item_transport,
            include_in_budget=True,
        )
        Expenditure.objects.create(
            date=self.make_dt(12),
            amount=Decimal('250.00'),
            comment='Такси домой',
            wallet=self.wallet_secondary,
            cash_flow_item=self.item_transport,
            include_in_budget=True,
        )
        Expenditure.objects.create(
            date=self.make_dt(10),
            amount=Decimal('120.00'),
            comment='Такси до офиса',
            wallet=self.wallet_main,
            cash_flow_item=self.item_salary,
            include_in_budget=False,
        )

        response = self.client.get(
            '/api/v1/expenditures/',
            {
                'wallet': str(self.wallet_main.id),
                'cash_flow_item': str(self.item_transport.id),
                'date_from': '2024-04-09',
                'date_to': '2024-04-11',
                'amount_min': '200.00',
                'amount_max': '300.00',
                'include_in_budget': 'true',
                'search': 'такси',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], str(target.id))

    def test_transfers_list_filters_route_and_falls_back_for_invalid_page_size(self):
        for day in range(1, 22):
            Transfer.objects.create(
                date=self.make_dt(day),
                amount=Decimal('1000.00') + Decimal(day),
                comment=f'Перевод {day}',
                wallet_out=self.wallet_main,
                wallet_in=self.wallet_target,
            )

        Transfer.objects.create(
            date=self.make_dt(22),
            amount=Decimal('500.00'),
            comment='Лишний маршрут',
            wallet_out=self.wallet_secondary,
            wallet_in=self.wallet_target,
        )

        response = self.client.get(
            '/api/v1/transfers/',
            {
                'wallet_from': str(self.wallet_main.id),
                'wallet_to': str(self.wallet_target.id),
                'page_size': 30,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 21)
        self.assertEqual(len(response.data['results']), 20)


class PlanningDefaultsAndGenerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='planning-admin',
            email='planning-admin@example.com',
            password='adminpass123',
        )
        cls.wallet_main = Wallet.objects.create(name='Кошелек планирования')
        cls.wallet_target = Wallet.objects.create(name='Кошелек назначения')
        cls.item = CashFlowItem.objects.create(name='Подушка', include_in_budget=True)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin_user)

    def make_dt(self, month, day=1):
        return timezone.make_aware(datetime(2024, month, day, 7, 0, 0))

    def test_expenditure_api_defaults_include_in_budget_to_true(self):
        response = self.client.post(
            '/api/v1/expenditures/',
            {
                'amount': '250.00',
                'date': self.make_dt(5).isoformat(),
                'wallet': str(self.wallet_main.id),
                'cash_flow_item': str(self.item.id),
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['include_in_budget'])

    def test_budget_api_defaults_amount_month_and_date_start(self):
        response = self.client.post(
            '/api/v1/budgets/',
            {
                'amount': '1200.00',
                'date': self.make_dt(5).isoformat(),
                'cash_flow_item': str(self.item.id),
                'type_of_budget': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['amount_month'], 12)
        self.assertIsNotNone(response.data['date_start'])

    def test_autopayment_api_defaults_amount_month_and_date_start(self):
        response = self.client.post(
            '/api/v1/auto-payments/',
            {
                'amount': '1200.00',
                'date': self.make_dt(5).isoformat(),
                'wallet_out': str(self.wallet_main.id),
                'cash_flow_item': str(self.item.id),
                'is_transfer': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['amount_month'], 12)
        self.assertIsNotNone(response.data['date_start'])

    def test_budget_generate_graphics_uses_monthly_amount_and_updates_total(self):
        budget = Budget.objects.create(
            amount=Decimal('1000.00'),
            amount_month=2,
            date=self.make_dt(6),
            date_start=self.make_dt(6, 15),
            cash_flow_item=self.item,
            type_of_budget=False,
        )

        response = self.client.post(
            f'/api/v1/budgets/{budget.id}/generate-graphics/',
            {
                'amount_month': 3,
                'date_start': self.make_dt(7, 5).isoformat(),
                'monthly_amount': '500.00',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        budget.refresh_from_db()
        self.assertEqual(response.data['document']['amount'], '1500.00')
        self.assertEqual(response.data['document']['amount_month'], 3)
        self.assertEqual(budget.amount, Decimal('1500.00'))
        self.assertEqual(budget.amount_month, 3)
        self.assertEqual(budget.date_start, self.make_dt(7, 5))
        self.assertEqual(
            [row['amount'] for row in response.data['rows']],
            [
                '500.00',
                '500.00',
                '500.00',
            ],
        )
        self.assertEqual(
            list(
                BudgetGraphic.objects.filter(document=budget).order_by('date_start').values_list('date_start', 'amount')
            ),
            [
                (self.make_dt(7, 5), Decimal('500.00')),
                (self.make_dt(8, 5), Decimal('500.00')),
                (self.make_dt(9, 5), Decimal('500.00')),
            ],
        )
        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=budget.id).order_by('period').values_list('amount', flat=True)
            ),
            [Decimal('500.00'), Decimal('500.00'), Decimal('500.00')],
        )

    def test_autopayment_generate_graphics_without_rounding_splits_remainder(self):
        autopayment = AutoPayment.objects.create(
            amount=Decimal('100.00'),
            amount_month=3,
            date=self.make_dt(6),
            date_start=self.make_dt(6, 10),
            wallet_out=self.wallet_main,
            cash_flow_item=self.item,
            is_transfer=False,
        )

        response = self.client.post(
            f'/api/v1/auto-payments/{autopayment.id}/generate-graphics/',
            {
                'amount': '100.00',
                'amount_month': 3,
                'date_start': self.make_dt(8, 10).isoformat(),
                'without_rounding': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row['amount'] for row in response.data['rows']],
            ['33.33', '33.33', '33.34'],
        )
        self.assertEqual(
            list(
                BudgetExpense.objects.filter(document_id=autopayment.id).order_by('period').values_list('amount', flat=True)
            ),
            [Decimal('33.33'), Decimal('33.33'), Decimal('33.34')],
        )

    def test_budget_generate_graphics_rejects_too_small_rounded_payment(self):
        budget = Budget.objects.create(
            amount=Decimal('50.00'),
            amount_month=12,
            date=self.make_dt(6),
            date_start=self.make_dt(6, 1),
            cash_flow_item=self.item,
            type_of_budget=False,
        )

        response = self.client.post(
            f'/api/v1/budgets/{budget.id}/generate-graphics/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Ежемесячный платеж меньше 100 руб.', str(response.data))


class DashboardOverviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='dashboard-admin',
            email='dashboard-admin@example.com',
            password='adminpass123',
        )
        cls.visible_wallet = Wallet.objects.create(name='Основной кошелек')
        cls.hidden_wallet = Wallet.objects.create(name='Скрытый кошелек', hidden=True)
        cls.salary_item = CashFlowItem.objects.create(name='Зарплата', include_in_budget=True)
        cls.food_item = CashFlowItem.objects.create(name='Еда', include_in_budget=True)
        cls.travel_item = CashFlowItem.objects.create(name='Путешествия', include_in_budget=True)

        Receipt.objects.create(
            amount=Decimal('1000.00'),
            date=cls.make_dt(2024, 2, 5),
            wallet=cls.visible_wallet,
            cash_flow_item=cls.salary_item,
        )
        Expenditure.objects.create(
            amount=Decimal('500.00'),
            date=cls.make_dt(2024, 2, 6),
            wallet=cls.visible_wallet,
            cash_flow_item=cls.food_item,
            include_in_budget=False,
        )

        Budget.objects.create(
            amount=Decimal('500.00'),
            amount_month=1,
            date=cls.make_dt(2024, 3, 1),
            date_start=cls.make_dt(2024, 3, 1),
            cash_flow_item=cls.food_item,
            type_of_budget=False,
        )
        Budget.objects.create(
            amount=Decimal('800.00'),
            amount_month=1,
            date=cls.make_dt(2024, 3, 1),
            date_start=cls.make_dt(2024, 3, 1),
            cash_flow_item=cls.salary_item,
            type_of_budget=True,
        )
        Receipt.objects.create(
            amount=Decimal('500.00'),
            date=cls.make_dt(2024, 3, 1),
            wallet=cls.visible_wallet,
            cash_flow_item=cls.salary_item,
        )
        Receipt.objects.create(
            amount=Decimal('200.00'),
            date=cls.make_dt(2024, 3, 2),
            wallet=cls.hidden_wallet,
            cash_flow_item=cls.salary_item,
        )
        Expenditure.objects.create(
            amount=Decimal('300.00'),
            date=cls.make_dt(2024, 3, 3),
            wallet=cls.visible_wallet,
            cash_flow_item=cls.food_item,
            include_in_budget=True,
        )
        Expenditure.objects.create(
            amount=Decimal('300.00'),
            date=cls.make_dt(2024, 3, 4),
            wallet=cls.visible_wallet,
            cash_flow_item=cls.travel_item,
            include_in_budget=True,
        )

    @staticmethod
    def make_dt(year, month, day):
        return timezone.make_aware(datetime(year, month, day, 12, 0, 0))

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin_user)
        self.selected_at = self.make_dt(2024, 3, 15)

    def test_dashboard_overview_matches_1c_style_metrics(self):
        response = self.client.get(
            '/api/v1/dashboard/overview/',
            {'date': self.selected_at.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['hide_hidden_wallets'])
        self.assertEqual(response.data['wallet_total'], '400.00')
        self.assertEqual(
            response.data['wallets'],
            [
                {
                    'wallet_id': str(self.visible_wallet.id),
                    'wallet_name': 'Основной кошелек',
                    'balance': '400.00',
                }
            ],
        )
        self.assertEqual(
            response.data['budget_expense'],
            {
                'items': [
                    {
                        'cash_flow_item_id': str(self.food_item.id),
                        'cash_flow_item_name': 'Еда',
                        'remaining': '200.00',
                        'overrun': '0.00',
                    },
                    {
                        'cash_flow_item_id': str(self.travel_item.id),
                        'cash_flow_item_name': 'Путешествия',
                        'remaining': '0.00',
                        'overrun': '300.00',
                    },
                ],
                'remaining_total': '200.00',
                'overrun_total': '300.00',
            },
        )
        self.assertEqual(
            response.data['budget_income'],
            {
                'planned_total': '800.00',
                'actual_total': '700.00',
                'remaining_total': '100.00',
            },
        )
        self.assertEqual(response.data['cash_with_budget'], '300.00')
        self.assertEqual(response.data['month_comparison']['previous_month']['expense'], '500.00')
        self.assertEqual(response.data['month_comparison']['previous_month']['income'], '1000.00')
        self.assertEqual(response.data['month_comparison']['current_month']['expense'], '600.00')
        self.assertEqual(response.data['month_comparison']['current_month']['income'], '700.00')
        self.assertEqual(response.data['month_comparison']['difference_percent']['expense'], '-20.00')
        self.assertEqual(response.data['month_comparison']['difference_percent']['income'], '-42.86')

    def test_dashboard_can_include_hidden_wallets_in_balance_block(self):
        response = self.client.get(
            '/api/v1/dashboard/overview/',
            {
                'date': self.selected_at.isoformat(),
                'hide_hidden_wallets': 'false',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['hide_hidden_wallets'])
        self.assertEqual(response.data['wallet_total'], '600.00')
        self.assertEqual(
            [wallet['wallet_name'] for wallet in response.data['wallets']],
            ['Основной кошелек', 'Скрытый кошелек'],
        )
        self.assertEqual(response.data['cash_with_budget'], '500.00')

    def test_dashboard_omits_zero_balance_wallets(self):
        zero_wallet = Wallet.objects.create(name='Пустой кошелек')

        response = self.client.get(
            '/api/v1/dashboard/overview/',
            {'date': self.selected_at.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            str(zero_wallet.id),
            [wallet['wallet_id'] for wallet in response.data['wallets']],
        )

    def test_dashboard_recent_activity_uses_limit_and_selected_date(self):
        reserve_wallet = Wallet.objects.create(name='Резервный кошелек')
        transfer = Transfer.objects.create(
            amount=Decimal('120.00'),
            date=self.make_dt(2024, 3, 5),
            wallet_out=self.visible_wallet,
            wallet_in=reserve_wallet,
            comment='Перевод в резерв',
        )
        Receipt.objects.create(
            amount=Decimal('999.00'),
            date=self.make_dt(2024, 3, 20),
            wallet=self.visible_wallet,
            cash_flow_item=self.salary_item,
            comment='Будущий доход',
        )

        response = self.client.get(
            '/api/v1/dashboard/recent-activity/',
            {
                'date': self.selected_at.isoformat(),
                'limit': 2,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['hide_hidden_wallets'])
        self.assertEqual(response.data['limit'], 2)
        self.assertEqual(len(response.data['items']), 2)
        self.assertEqual(
            [item['kind'] for item in response.data['items']],
            ['transfer', 'expenditure'],
        )
        self.assertEqual(response.data['items'][0]['id'], str(transfer.id))
        self.assertEqual(response.data['items'][0]['wallet_from_name'], 'Основной кошелек')
        self.assertEqual(response.data['items'][0]['wallet_to_name'], 'Резервный кошелек')
        self.assertEqual(response.data['items'][0]['description'], 'Перевод в резерв')
        self.assertEqual(response.data['items'][1]['cash_flow_item_name'], 'Путешествия')

    def test_dashboard_budget_expense_breakdown_matches_selected_item(self):
        response = self.client.get(
            '/api/v1/dashboard/budget-expense-breakdown/',
            {
                'date': self.selected_at.isoformat(),
                'cash_flow_item': str(self.food_item.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['cash_flow_item_id'], str(self.food_item.id))
        self.assertEqual(response.data['cash_flow_item_name'], 'Еда')
        self.assertEqual(response.data['planned_total'], '500.00')
        self.assertEqual(response.data['actual_total'], '300.00')
        self.assertEqual(response.data['remaining'], '200.00')
        self.assertEqual(response.data['overrun'], '0.00')
        self.assertEqual(len(response.data['details']), 2)
        self.assertEqual(response.data['details'][0]['period'], self.make_dt(2024, 3, 1).isoformat())
        self.assertEqual(response.data['details'][0]['entry_type'], 'budget')
        self.assertEqual(response.data['details'][0]['document_type'], 'Budget')
        self.assertEqual(response.data['details'][0]['amount'], '500.00')
        self.assertIsNotNone(response.data['details'][0]['document_id'])
        self.assertEqual(response.data['details'][1]['period'], self.make_dt(2024, 3, 3).isoformat())
        self.assertEqual(response.data['details'][1]['entry_type'], 'actual')
        self.assertEqual(response.data['details'][1]['document_type'], 'Expenditure')
        self.assertEqual(response.data['details'][1]['amount'], '300.00')
        self.assertIsNotNone(response.data['details'][1]['document_id'])

    def test_dashboard_recent_activity_respects_hidden_wallet_filter(self):
        reserve_wallet = Wallet.objects.create(name='Второй видимый кошелек')
        hidden_transfer = Transfer.objects.create(
            amount=Decimal('50.00'),
            date=self.make_dt(2024, 3, 6),
            wallet_out=self.hidden_wallet,
            wallet_in=reserve_wallet,
            comment='Скрытый перевод',
        )

        hidden_response = self.client.get(
            '/api/v1/dashboard/recent-activity/',
            {
                'date': self.selected_at.isoformat(),
                'limit': 10,
            },
        )
        self.assertEqual(hidden_response.status_code, 200)
        self.assertNotIn(
            str(hidden_transfer.id),
            [item['id'] for item in hidden_response.data['items']],
        )
        self.assertNotIn(
            str(self.hidden_wallet.id),
            [item.get('wallet') for item in hidden_response.data['items']],
        )

        visible_response = self.client.get(
            '/api/v1/dashboard/recent-activity/',
            {
                'date': self.selected_at.isoformat(),
                'limit': 10,
                'hide_hidden_wallets': 'false',
            },
        )
        self.assertEqual(visible_response.status_code, 200)
        self.assertIn(
            str(hidden_transfer.id),
            [item['id'] for item in visible_response.data['items']],
        )
        self.assertIn(
            str(self.hidden_wallet.id),
            [item.get('wallet') for item in visible_response.data['items']],
        )

    def test_dashboard_uses_requested_timezone_for_end_of_day_balance(self):
        moscow_tz = dt_timezone(timedelta(hours=3))
        boundary_item = CashFlowItem.objects.create(name='Граница дня', include_in_budget=False)

        Receipt.objects.create(
            amount=Decimal('100.00'),
            date=datetime(2024, 3, 2, 23, 30, tzinfo=moscow_tz),
            wallet=self.visible_wallet,
            cash_flow_item=boundary_item,
        )
        Expenditure.objects.create(
            amount=Decimal('30.00'),
            date=datetime(2024, 3, 3, 0, 0, tzinfo=moscow_tz),
            wallet=self.visible_wallet,
            cash_flow_item=boundary_item,
            include_in_budget=False,
        )

        response = self.client.get(
            '/api/v1/dashboard/overview/',
            {'date': '2024-03-02T23:59:59+03:00'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['date'], '2024-03-02T23:59:59.999999+03:00')
        self.assertEqual(response.data['wallet_total'], '1100.00')
        self.assertEqual(
            response.data['wallets'],
            [
                {
                    'wallet_id': str(self.visible_wallet.id),
                    'wallet_name': 'Основной кошелек',
                    'balance': '1100.00',
                }
            ],
        )


class WalletSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='wallet-summary-admin',
            email='wallet-summary-admin@example.com',
            password='adminpass123',
        )
        cls.wallet = Wallet.objects.create(name='Основной кошелек')
        cls.other_wallet = Wallet.objects.create(name='Второй кошелек')
        cls.salary_item = CashFlowItem.objects.create(name='Зарплата')
        cls.food_item = CashFlowItem.objects.create(name='Еда')

        Receipt.objects.create(
            amount=Decimal('100.00'),
            date=timezone.make_aware(datetime(2024, 3, 1, 10, 0, 0)),
            wallet=cls.wallet,
            cash_flow_item=cls.salary_item,
            comment='Аванс',
        )
        Expenditure.objects.create(
            amount=Decimal('30.00'),
            date=timezone.make_aware(datetime(2024, 3, 2, 10, 0, 0)),
            wallet=cls.wallet,
            cash_flow_item=cls.food_item,
            include_in_budget=False,
            comment='Продукты',
        )
        Receipt.objects.create(
            amount=Decimal('15.00'),
            date=timezone.make_aware(datetime(2024, 3, 3, 10, 0, 0)),
            wallet=cls.other_wallet,
            cash_flow_item=cls.salary_item,
            comment='Чужой доход',
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin_user)

    def test_wallet_summary_returns_balances_totals_and_recent_operations(self):
        response = self.client.get(f'/api/v1/wallets/{self.wallet.id}/summary/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['wallet_id'], str(self.wallet.id))
        self.assertEqual(response.data['wallet_name'], 'Основной кошелек')
        self.assertEqual(response.data['balance'], '70.00')
        self.assertEqual(response.data['income_total'], '100.00')
        self.assertEqual(response.data['expense_total'], '30.00')
        self.assertEqual(
            [item['kind'] for item in response.data['recent_operations']],
            ['expenditure', 'receipt'],
        )
        self.assertEqual(
            [item['description'] for item in response.data['recent_operations']],
            ['Продукты', 'Аванс'],
        )


class ReportEndpointsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='reports-admin',
            email='reports-admin@example.com',
            password='adminpass123',
        )
        cls.wallet_main = Wallet.objects.create(name='Основной кошелек')
        cls.wallet_reserve = Wallet.objects.create(name='Резервный кошелек')
        cls.project = Project.objects.create(name='Проект А')
        cls.salary_item = CashFlowItem.objects.create(name='Зарплата', include_in_budget=True)
        cls.food_item = CashFlowItem.objects.create(name='Еда', include_in_budget=True)

        Receipt.objects.create(
            amount=Decimal('1000.00'),
            date=cls.make_dt(2024, 3, 1),
            wallet=cls.wallet_main,
            cash_flow_item=cls.salary_item,
        )
        Expenditure.objects.create(
            amount=Decimal('300.00'),
            date=cls.make_dt(2024, 3, 2),
            wallet=cls.wallet_main,
            cash_flow_item=cls.food_item,
            include_in_budget=True,
        )
        Transfer.objects.create(
            amount=Decimal('150.00'),
            date=cls.make_dt(2024, 3, 3),
            wallet_in=cls.wallet_reserve,
            wallet_out=cls.wallet_main,
            cash_flow_item=cls.food_item,
            include_in_budget=True,
        )
        Budget.objects.create(
            amount=Decimal('500.00'),
            amount_month=1,
            date=cls.make_dt(2024, 3, 1),
            date_start=cls.make_dt(2024, 3, 1),
            cash_flow_item=cls.food_item,
            project=cls.project,
            type_of_budget=False,
        )
        Budget.objects.create(
            amount=Decimal('1200.00'),
            amount_month=1,
            date=cls.make_dt(2024, 3, 1),
            date_start=cls.make_dt(2024, 3, 1),
            cash_flow_item=cls.salary_item,
            project=cls.project,
            type_of_budget=True,
        )

    @staticmethod
    def make_dt(year, month, day):
        return timezone.make_aware(datetime(year, month, day, 10, 0, 0))

    @staticmethod
    def make_month_start(year, month):
        return timezone.make_aware(datetime(year, month, 1, 0, 0, 0))

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin_user)

    def test_cash_flow_report_returns_months_and_details(self):
        response = self.client.get(
            '/api/v1/reports/cash-flow/',
            {
                'date_from': self.make_dt(2024, 3, 1).isoformat(),
                'date_to': self.make_dt(2024, 3, 31).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['totals'], {'income': '1150.00', 'expense': '450.00'})
        self.assertEqual(
            response.data['months'],
            [
                {
                    'period': self.make_month_start(2024, 3),
                    'income': '1150.00',
                    'expense': '450.00',
                }
            ],
        )
        self.assertEqual(len(response.data['details']), 4)

    def test_budget_expense_report_returns_plan_fact_and_balance(self):
        response = self.client.get(
            '/api/v1/reports/budget-expense/',
            {
                'date_from': self.make_dt(2024, 3, 1).isoformat(),
                'date_to': self.make_dt(2024, 3, 31).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['totals'], {'actual': '450.00', 'budget': '500.00', 'balance': '50.00'})
        self.assertEqual(
            response.data['summary'],
            [
                {
                    'period': self.make_month_start(2024, 3),
                    'project_id': str(self.project.id),
                    'project_name': 'Проект А',
                    'cash_flow_item_id': str(self.food_item.id),
                    'cash_flow_item_name': 'Еда',
                    'actual': '0.00',
                    'budget': '500.00',
                    'balance': '500.00',
                },
                {
                    'period': self.make_month_start(2024, 3),
                    'project_id': None,
                    'project_name': None,
                    'cash_flow_item_id': str(self.food_item.id),
                    'cash_flow_item_name': 'Еда',
                    'actual': '450.00',
                    'budget': '0.00',
                    'balance': '-450.00',
                },
            ],
        )
        self.assertEqual(len(response.data['details']), 3)

    def test_budget_income_report_returns_plan_fact_and_balance(self):
        response = self.client.get(
            '/api/v1/reports/budget-income/',
            {
                'date_from': self.make_dt(2024, 3, 1).isoformat(),
                'date_to': self.make_dt(2024, 3, 31).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['totals'], {'actual': '1000.00', 'budget': '1200.00', 'balance': '200.00'})
        self.assertEqual(
            response.data['summary'],
            [
                {
                    'period': self.make_month_start(2024, 3),
                    'project_id': str(self.project.id),
                    'project_name': 'Проект А',
                    'cash_flow_item_id': str(self.salary_item.id),
                    'cash_flow_item_name': 'Зарплата',
                    'actual': '0.00',
                    'budget': '1200.00',
                    'balance': '1200.00',
                },
                {
                    'period': self.make_month_start(2024, 3),
                    'project_id': None,
                    'project_name': None,
                    'cash_flow_item_id': str(self.salary_item.id),
                    'cash_flow_item_name': 'Зарплата',
                    'actual': '1000.00',
                    'budget': '0.00',
                    'balance': '-1000.00',
                },
            ],
        )
        self.assertEqual(len(response.data['details']), 2)

    def test_openapi_schema_contains_report_and_dashboard_endpoints(self):
        response = self.client.get('/api/schema/')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('/api/v1/reports/cash-flow/', content)
        self.assertIn('/api/v1/reports/budget-expense/', content)
        self.assertIn('/api/v1/reports/budget-income/', content)
        self.assertIn('/api/v1/dashboard/overview/', content)

    def test_openapi_schema_documents_wallet_balance_filters_and_canonical_autopayment_fields(self):
        response = self.client.get('/api/schema/')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('/api/v1/wallets/{id}/balance/', content)
        self.assertIn('/api/v1/wallets/balances/', content)
        self.assertIn('WalletBalanceResponse', content)
        self.assertIn('WalletBalancesResponse', content)
        self.assertIn('WalletRequest', content)
        self.assertIn('PatchedWalletRequest', content)
        self.assertIn('include_in_budget', content)
        self.assertIn('is_transfer', content)
        self.assertIn('type:', content)
        self.assertIn('Alias next_date не поддерживается.', content)
        self.assertIn('Alias period_days не поддерживается.', content)

    def test_openapi_wallet_request_component_does_not_require_code(self):
        response = self.client.get('/api/schema/')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('    WalletRequest:', content)
        wallet_request_block = content.split('    WalletRequest:')[1].split('\n    ')[0]
        self.assertNotIn('code:', wallet_request_block)


@override_settings(
    AI_DEFAULT_PROVIDER='rule_based',
    AI_ALLOW_RULE_BASED_FALLBACK=True,
    AI_TELEGRAM_BOT_SECRET='telegram-secret',
    AI_TELEGRAM_BOT_TOKEN='',
)
class AiAssistantApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='ai-admin',
            email='ai-admin@example.com',
            password='adminpass123',
        )
        cls.regular_user = CustomUser.objects.create_user(
            username='ai-user',
            email='ai-user@example.com',
            password='userpass123',
        )
        cls.telegram_bound_user = CustomUser.objects.create_user(
            username='trialex',
            email='trialex@example.com',
            password='userpass123',
        )
        cls.wallet_sber = Wallet.objects.create(name='Сбербанк')
        cls.wallet_alpha = Wallet.objects.create(name='Альфа')
        WalletAlias.objects.create(wallet=cls.wallet_sber, alias='сбер')
        WalletAlias.objects.create(wallet=cls.wallet_alpha, alias='альфа-банк')
        cls.income_item = CashFlowItem.objects.create(name='Зарплата', include_in_budget=True)
        cls.expense_item = CashFlowItem.objects.create(name='Продукты', include_in_budget=True)
        CashFlowItemAlias.objects.create(cash_flow_item=cls.income_item, alias='зарплата')
        CashFlowItemAlias.objects.create(cash_flow_item=cls.expense_item, alias='еда')

        Receipt.objects.create(
            amount=Decimal('10000.00'),
            wallet=cls.wallet_sber,
            cash_flow_item=cls.income_item,
            date=timezone.make_aware(datetime(2024, 6, 1, 10, 0, 0)),
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin_user)

    def test_ai_execute_creates_transfer_from_text(self):
        response = self.client.post(
            '/api/v1/ai/execute/',
            {
                'text': 'перевод сбербанк альфа 20000',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'created')
        self.assertEqual(response.data['intent'], 'create_transfer')
        transfer = Transfer.objects.get(id=response.data['created_object']['id'])
        self.assertEqual(transfer.wallet_out, self.wallet_sber)
        self.assertEqual(transfer.wallet_in, self.wallet_alpha)
        self.assertEqual(transfer.amount, Decimal('20000.00'))

    def test_ai_execute_is_available_for_authenticated_non_admin_user(self):
        client = APIClient()
        client.force_authenticate(self.regular_user)

        response = client.post(
            '/api/v1/ai/execute/',
            {
                'text': 'какой остаток на сбербанке',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'balance')

    def test_ai_service_serialize_normalized_batch_accepts_serialized_items(self):
        service = ai_service.AiOperationService()
        occurred_at = timezone.make_aware(datetime(2026, 4, 27, 16, 13, 0))

        serialized = service.serialize_normalized_batch(
            {
                'batch': True,
                'intent': 'create_multiple_operations',
                'confidence': 0.95,
                'image_based': True,
                'items': [
                    {
                        'intent': 'create_expenditure',
                        'confidence': 0.9,
                        'image_based': True,
                        'amount': '342.00',
                        'wallet_id': str(self.wallet_alpha.id),
                        'cash_flow_item_id': str(self.expense_item.id),
                        'comment': 'Дикий океан',
                        'include_in_budget': False,
                        'occurred_at': occurred_at.isoformat(),
                        'operation_sign': 'outgoing',
                        'source_index': 1,
                        'raw': {'amount': '342.00'},
                    }
                ],
                'raw': {'source': 'telegram'},
            }
        )

        self.assertEqual(serialized['items'][0]['amount'], '342.00')
        self.assertEqual(serialized['items'][0]['wallet_id'], str(self.wallet_alpha.id))
        self.assertEqual(serialized['items'][0]['cash_flow_item_id'], str(self.expense_item.id))
        self.assertEqual(serialized['items'][0]['occurred_at'], occurred_at.isoformat())

    def test_ai_execute_returns_help_for_capabilities_question(self):
        response = self.client.post(
            '/api/v1/ai/execute/',
            {
                'text': 'что ты умеешь?',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'info')
        self.assertEqual(response.data['intent'], 'help_capabilities')
        self.assertIn('Я умею', response.data['reply_text'])
        self.assertIn('остатки по кошелькам', response.data['reply_text'])

    def test_ai_execute_returns_wallet_balance(self):
        response = self.client.post(
            '/api/v1/ai/execute/',
            {
                'text': 'какой остаток на сбер',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'balance')
        self.assertEqual(response.data['intent'], 'get_wallet_balance')
        self.assertEqual(response.data['balances'][0]['wallet_name'], 'Сбербанк')
        self.assertEqual(response.data['balances'][0]['balance'], '10000.00')

    def test_ai_execute_returns_wallet_balance_for_current_date_only(self):
        FlowOfFunds.objects.create(
            document_id=uuid.uuid4(),
            period=timezone.now() + timedelta(days=7),
            type_of_document=3,
            wallet=self.wallet_sber,
            cash_flow_item=self.income_item,
            amount=Decimal('5000.00'),
        )

        response = self.client.post(
            '/api/v1/ai/execute/',
            {
                'text': 'какой остаток на сбер',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['balances'][0]['balance'], '10000.00')

    def test_ai_execute_returns_all_wallet_balances_for_current_date_only(self):
        FlowOfFunds.objects.create(
            document_id=uuid.uuid4(),
            period=timezone.now() + timedelta(days=7),
            type_of_document=3,
            wallet=self.wallet_alpha,
            cash_flow_item=self.income_item,
            amount=Decimal('7000.00'),
        )

        response = self.client.post(
            '/api/v1/ai/execute/',
            {
                'text': 'остатки по кошелькам',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        balances = {row['wallet_name']: row['balance'] for row in response.data['balances']}
        self.assertEqual(balances['Сбербанк'], '10000.00')
        self.assertNotIn('Альфа', balances)

    def test_ai_execute_creates_expenditure_from_wallet_and_item_aliases(self):
        response = self.client.post(
            '/api/v1/ai/execute/',
            {
                'text': 'расход сбер еда 2500',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'created')
        self.assertEqual(response.data['intent'], 'create_expenditure')
        expenditure = Expenditure.objects.get(id=response.data['created_object']['id'])
        self.assertEqual(expenditure.wallet, self.wallet_sber)
        self.assertEqual(expenditure.cash_flow_item, self.expense_item)
        self.assertEqual(expenditure.amount, Decimal('2500.00'))

    def test_ai_execute_creates_receipt_from_wallet_and_item_aliases(self):
        response = self.client.post(
            '/api/v1/ai/execute/',
            {
                'text': 'приход сбер зарплата 15000',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'created')
        self.assertEqual(response.data['intent'], 'create_receipt')
        receipt = Receipt.objects.get(id=response.data['created_object']['id'])
        self.assertEqual(receipt.wallet, self.wallet_sber)
        self.assertEqual(receipt.cash_flow_item, self.income_item)
        self.assertEqual(receipt.amount, Decimal('15000.00'))

    def test_ai_execute_returns_duplicate_for_repeated_text_command(self):
        first_response = self.client.post(
            '/api/v1/ai/execute/',
            {
                'text': 'расход сбер еда 2500',
            },
            format='json',
        )
        second_response = self.client.post(
            '/api/v1/ai/execute/',
            {
                'text': 'расход сбер еда 2500',
            },
            format='json',
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.data['status'], 'duplicate')
        self.assertEqual(
            Expenditure.objects.filter(wallet=self.wallet_sber, cash_flow_item=self.expense_item, amount=Decimal('2500.00')).count(),
            1,
        )
        self.assertEqual(AiProcessedInput.objects.filter(source='web').count(), 1)

    def test_ai_execute_returns_semantic_duplicate_for_equivalent_text(self):
        first_response = self.client.post(
            '/api/v1/ai/execute/',
            {'text': 'расход сбер еда 2500'},
            format='json',
        )
        second_response = self.client.post(
            '/api/v1/ai/execute/',
            {'text': 'трата сбербанк продукты 2500'},
            format='json',
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.data['status'], 'duplicate')
        self.assertEqual(
            Expenditure.objects.filter(wallet=self.wallet_sber, cash_flow_item=self.expense_item, amount=Decimal('2500.00')).count(),
            1,
        )

    def test_ai_execute_creates_expenditure_from_bank_screenshot_with_mocked_provider(self):
        current_image_dt = timezone.make_aware(datetime(2026, 4, 26, 11, 30, 0))
        mock_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.98,
            'amount': '349.00',
            'bank_name': 'Сбербанк',
            'merchant': 'Еда',
            'description': 'Покупка по карте',
            'occurred_at': '2024-06-03T09:15:00+03:00',
            'comment': 'Скриншот банка',
            'include_in_budget': False,
        }

        screenshot = SimpleUploadedFile(
            'bank.png',
            b'fake-image-bytes',
            content_type='image/png',
        )

        with patch(
            'money.ai_service._get_intent_provider',
            return_value=(type('MockProvider', (), {'parse': lambda self, **kwargs: mock_provider_result})(), 'gemini'),
        ):
            with patch('money.ai_service.timezone.now', return_value=current_image_dt):
                response = self.client.post(
                    '/api/v1/ai/execute/',
                    {
                        'image': screenshot,
                    },
                )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'created')
        self.assertEqual(response.data['intent'], 'create_expenditure')
        expenditure = Expenditure.objects.get(id=response.data['created_object']['id'])
        self.assertEqual(expenditure.wallet, self.wallet_sber)
        self.assertEqual(expenditure.cash_flow_item, self.expense_item)
        self.assertEqual(expenditure.amount, Decimal('349.00'))
        self.assertEqual(expenditure.date, current_image_dt)
        self.assertIn('Скриншот банка', expenditure.comment)
        self.assertIn('Еда', expenditure.comment)

    def test_ai_execute_creates_expenditure_from_bank_history_screenshot_with_raw_text_fallback(self):
        mock_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.94,
            'amount': '-465,75 ₽',
            'wallet_hint': None,
            'bank_name': None,
            'merchant': 'Магнит',
            'description': 'Продукты',
            'comment': 'Альфа история операций Магнит -465,75 ₽',
            'occurred_at': None,
            'operation_sign': 'outgoing',
            'include_in_budget': False,
        }

        screenshot = SimpleUploadedFile(
            'history.png',
            b'fake-history-image-bytes',
            content_type='image/png',
        )

        with patch(
            'money.ai_service._get_intent_provider',
            return_value=(type('MockProvider', (), {'parse': lambda self, **kwargs: mock_provider_result})(), 'openrouter'),
        ):
            response = self.client.post(
                '/api/v1/ai/execute/',
                {
                    'image': screenshot,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'created')
        expenditure = Expenditure.objects.get(id=response.data['created_object']['id'])
        self.assertEqual(expenditure.wallet, self.wallet_alpha)
        self.assertEqual(expenditure.cash_flow_item, self.expense_item)
        self.assertEqual(expenditure.amount, Decimal('465.75'))
        self.assertIn('Альфа история операций', expenditure.comment)

    def test_ai_execute_creates_multiple_expenditures_from_bank_history_screenshot(self):
        first_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.9,
            'amount': '342.00',
            'merchant': 'Дикий океан',
            'description': 'Дикий океан',
            'comment': 'Дикий океан',
            'operation_sign': 'outgoing',
        }
        second_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.96,
            'bank_name': 'Альфа',
            'operations': [
                {
                    'intent': 'create_expenditure',
                    'amount': '-465,75 ₽',
                    'merchant': 'Магнит',
                    'description': 'Продукты',
                    'comment': 'Магнит -465,75 ₽',
                    'operation_sign': 'outgoing',
                },
                {
                    'intent': 'create_expenditure',
                    'amount': '-342 ₽',
                    'merchant': 'Дикий океан',
                    'description': 'Продукты',
                    'comment': 'Дикий океан -342 ₽',
                    'operation_sign': 'outgoing',
                },
            ],
        }

        screenshot = SimpleUploadedFile(
            'history-multi.png',
            b'fake-history-multi-image-bytes',
            content_type='image/png',
        )

        with patch(
            'money.ai_service._get_intent_provider',
            return_value=(
                type(
                    'MockProvider',
                    (),
                    {'parse': Mock(side_effect=[first_provider_result, second_provider_result])},
                )(),
                'openrouter',
            ),
        ):
            response = self.client.post(
                '/api/v1/ai/execute/',
                {
                    'image': screenshot,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'created')
        self.assertEqual(len(response.data['created_objects']), 2)
        expenditures = list(Expenditure.objects.filter(comment__icontains='₽').order_by('amount'))
        self.assertEqual(len(expenditures), 2)
        self.assertEqual(expenditures[0].wallet, self.wallet_alpha)
        self.assertEqual(expenditures[1].wallet, self.wallet_alpha)
        self.assertEqual(expenditures[0].cash_flow_item, self.expense_item)
        self.assertEqual(expenditures[1].cash_flow_item, self.expense_item)
        self.assertEqual([expense.amount for expense in expenditures], [Decimal('342.00'), Decimal('465.75')])

    def test_ai_execute_falls_back_to_text_when_provider_misses_amount_and_wallet(self):
        wallet_vtb = Wallet.objects.create(name='ВТБ')
        WalletAlias.objects.create(wallet=wallet_vtb, alias='втб')
        car_item = CashFlowItem.objects.create(name='Шины', include_in_budget=False)
        CashFlowItemAlias.objects.create(cash_flow_item=car_item, alias='машины')

        mock_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 1.0,
            'amount': None,
            'wallet_hint': None,
            'bank_name': None,
            'cash_flow_item_hint': None,
            'merchant': None,
            'description': None,
            'comment': None,
            'occurred_at': None,
            'operation_sign': 'outgoing',
            'include_in_budget': False,
        }

        with patch(
            'money.ai_service._get_intent_provider',
            return_value=(type('MockProvider', (), {'parse': lambda self, **kwargs: mock_provider_result})(), 'openrouter'),
        ):
            response = self.client.post(
                '/api/v1/ai/execute/',
                {
                    'text': '1719000 покупка машины с втб',
                },
                format='json',
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'created')
        self.assertEqual(response.data['provider'], 'openrouter')
        expenditure = Expenditure.objects.get(id=response.data['created_object']['id'])
        self.assertEqual(expenditure.amount, Decimal('1719000.00'))
        self.assertEqual(expenditure.wallet, wallet_vtb)
        self.assertEqual(expenditure.cash_flow_item, car_item)

    @override_settings(
        AI_DEFAULT_PROVIDER='openrouter',
        AI_OPENROUTER_API_KEY='openrouter-test-key',
        AI_OPENROUTER_MODEL='google/gemini-2.5-flash',
    )
    def test_get_intent_provider_uses_openrouter_with_gemini_model(self):
        provider, provider_name = ai_service._get_intent_provider()

        self.assertEqual(provider_name, 'openrouter')
        self.assertIsInstance(provider, ai_service.OpenRouterIntentProvider)
        self.assertEqual(provider.model_name, 'google/gemini-2.5-flash')

    @override_settings(
        AI_OPENROUTER_BASE_URL='https://openrouter.ai/api/v1/chat/completions',
        AI_OPENROUTER_SITE_URL='https://lk.example.com',
        AI_OPENROUTER_APP_NAME='LK Test',
    )
    def test_openrouter_provider_calls_chat_completions_endpoint(self):
        provider = ai_service.OpenRouterIntentProvider(
            api_key='openrouter-test-key',
            model_name='google/gemini-2.5-flash',
        )

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({
                    'choices': [
                        {
                            'message': {
                                'content': '{"intent":"unknown","confidence":0.1}'
                            }
                        }
                    ]
                }).encode('utf-8')

        with patch('money.ai_service.request.urlopen', return_value=_FakeResponse()) as mocked_urlopen:
            result = provider.parse(text='остаток на сбер')

        self.assertEqual(result['intent'], 'unknown')
        http_request = mocked_urlopen.call_args.args[0]
        request_headers = {key.lower(): value for key, value in http_request.header_items()}
        self.assertEqual(http_request.full_url, 'https://openrouter.ai/api/v1/chat/completions')
        self.assertEqual(request_headers['authorization'], 'Bearer openrouter-test-key')
        self.assertEqual(request_headers['http-referer'], 'https://lk.example.com')
        self.assertEqual(request_headers['x-title'], 'LK Test')

    def test_openrouter_prompt_includes_wallet_and_cash_flow_context(self):
        provider = ai_service.OpenRouterIntentProvider(
            api_key='openrouter-test-key',
            model_name='google/gemini-2.5-flash',
        )

        prompt = provider._build_prompt(
            text='1719000 покупка машины с втб',
            context={
                'wallets': [{'name': 'ВТБ', 'aliases': ['втб'], 'code': 'VTB'}],
                'cash_flow_items': [{'name': 'Шины', 'aliases': ['машины'], 'code': 'TYRES'}],
            },
        )

        self.assertIn('Доступные кошельки', prompt)
        self.assertIn('Доступные статьи', prompt)
        self.assertIn('ВТБ', prompt)
        self.assertIn('Шины', prompt)
        self.assertIn('wallet_hint', prompt)
        self.assertIn('cash_flow_item_hint', prompt)

    @override_settings(
        AI_OPENAI_API_KEY='openai-test-key',
        AI_OPENAI_TRANSCRIBE_BASE_URL='https://api.openai.com/v1/audio/transcriptions',
        AI_OPENAI_TRANSCRIBE_MODEL='gpt-4o-mini-transcribe',
        AI_OPENAI_TRANSCRIBE_LANGUAGE='ru',
    )
    def test_openai_transcription_service_calls_audio_transcriptions_endpoint(self):
        service = ai_service.OpenAiTranscriptionService(
            api_key='openai-test-key',
            model_name='gpt-4o-mini-transcribe',
            base_url='https://api.openai.com/v1/audio/transcriptions',
            language='ru',
        )

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({'text': 'расход сбер еда 2500'}).encode('utf-8')

        with patch('money.ai_service.request.urlopen', return_value=_FakeResponse()) as mocked_urlopen:
            transcript = service.transcribe(
                audio_bytes=b'fake-voice-bytes',
                audio_mime_type='audio/ogg',
                file_name='voice.ogg',
            )

        self.assertEqual(transcript, 'расход сбер еда 2500')
        http_request = mocked_urlopen.call_args.args[0]
        request_headers = {key.lower(): value for key, value in http_request.header_items()}
        self.assertEqual(http_request.full_url, 'https://api.openai.com/v1/audio/transcriptions')
        self.assertEqual(request_headers['authorization'], 'Bearer openai-test-key')
        self.assertIn('multipart/form-data', request_headers['content-type'])
        self.assertIn(b'name="model"', http_request.data)
        self.assertIn(b'gpt-4o-mini-transcribe', http_request.data)
        self.assertIn(b'name="language"', http_request.data)
        self.assertIn(b'\r\nru\r\n', http_request.data)
        self.assertIn(b'filename="voice.ogg"', http_request.data)

    def test_ai_execute_returns_preview_when_required_fields_missing(self):
        response = self.client.post(
            '/api/v1/ai/execute/',
            {
                'text': 'приход сбербанк 10000',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'needs_confirmation')
        self.assertEqual(response.data['intent'], 'create_receipt')
        self.assertIn('cash_flow_item', response.data['missing_fields'])
        self.assertIn('options', response.data)
        self.assertIn('preview', response.data)

    def test_ai_telegram_webhook_uses_same_pipeline(self):
        client = APIClient()
        response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 1,
                'message': {
                    'message_id': 10,
                    'text': 'остатки по кошелькам',
                    'chat': {'id': 100},
                    'from': {'id': 200, 'username': 'trialex'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'balance')
        self.assertEqual(response.data['intent'], 'get_all_wallet_balances')
        self.assertEqual(len(response.data['balances']), 1)
        self.assertEqual(response.data['balances'][0]['wallet_name'], 'Сбербанк')

    def test_ai_telegram_webhook_returns_help_before_binding(self):
        client = APIClient()
        response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 991,
                'message': {
                    'message_id': 992,
                    'text': 'что ты умеешь?',
                    'chat': {'id': 993},
                    'from': {'id': 994, 'username': 'unknown-telegram'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'info')
        self.assertEqual(response.data['intent'], 'help_capabilities')
        self.assertIn('Я умею', response.data['reply_text'])
        self.assertIn('/link CODE', response.data['reply_text'])

    @override_settings(AI_TELEGRAM_BOT_TOKEN='telegram-bot-token')
    def test_ai_telegram_webhook_downloads_photo_and_creates_expenditure(self):
        client = APIClient()
        current_image_dt = timezone.make_aware(datetime(2026, 4, 26, 11, 40, 0))

        class _FakeHeaders:
            def get_content_type(self):
                return 'image/jpeg'

        class _FakeResponse:
            def __init__(self, body, headers=None):
                self._body = body
                self.headers = headers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body

        get_file_response = _FakeResponse(
            json.dumps({'ok': True, 'result': {'file_path': 'photos/expense.jpg'}}).encode('utf-8')
        )
        image_response = _FakeResponse(b'fake-telegram-image', headers=_FakeHeaders())
        send_message_response = _FakeResponse(json.dumps({'ok': True, 'result': {'message_id': 999}}).encode('utf-8'))
        mock_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.98,
            'amount': '515.00',
            'bank_name': 'Сбербанк',
            'merchant': 'Еда',
            'description': 'Покупка по карте',
            'occurred_at': '2024-06-04T10:45:00+03:00',
            'comment': 'Telegram photo',
            'include_in_budget': False,
        }

        with patch('money.views.urlrequest.urlopen', side_effect=[get_file_response, image_response, send_message_response]) as mocked_urlopen:
            with patch(
                'money.ai_service._get_intent_provider',
                return_value=(type('MockProvider', (), {'parse': lambda self, **kwargs: mock_provider_result})(), 'openrouter'),
            ):
                with patch('money.ai_service.timezone.now', return_value=current_image_dt):
                    response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 88,
                            'message': {
                                'message_id': 98,
                                'caption': 'разбери операцию',
                                'photo': [
                                    {'file_id': 'small-photo', 'file_size': 1000, 'width': 90, 'height': 90},
                                    {'file_id': 'large-photo', 'file_size': 9000, 'width': 800, 'height': 800},
                                ],
                                'chat': {'id': 808},
                                'from': {'id': 908, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'needs_confirmation')
        self.assertEqual(response.data['missing_fields'], ['final_confirmation'])
        self.assertIn('Проверь, что будет создано:', response.data['reply_text'])
        send_request = mocked_urlopen.call_args_list[2].args[0]
        send_payload = json.loads(send_request.data.decode('utf-8'))
        self.assertEqual(send_payload['reply_markup']['keyboard'][0][0]['text'], 'Создать')

        with patch('money.views.urlrequest.urlopen', side_effect=[send_message_response]):
            with patch('money.ai_service.timezone.now', return_value=current_image_dt):
                confirm_response = client.post(
                    '/api/v1/ai/telegram-webhook/',
                    {
                        'update_id': 89,
                        'message': {
                            'message_id': 99,
                            'text': 'Создать',
                            'chat': {'id': 808},
                            'from': {'id': 908, 'username': 'trialex'},
                        },
                    },
                    format='json',
                    HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                )

        self.assertEqual(confirm_response.status_code, 201)
        self.assertEqual(confirm_response.data['status'], 'created')
        expenditure = Expenditure.objects.get(id=confirm_response.data['created_object']['id'])
        self.assertEqual(expenditure.wallet, self.wallet_sber)
        self.assertEqual(expenditure.cash_flow_item, self.expense_item)
        self.assertEqual(expenditure.amount, Decimal('515.00'))
        self.assertEqual(expenditure.date, current_image_dt)
        first_request = mocked_urlopen.call_args_list[0].args[0]
        second_request = mocked_urlopen.call_args_list[1].args[0]
        third_request = mocked_urlopen.call_args_list[2].args[0]
        self.assertIn('/bottelegram-bot-token/getFile', first_request.full_url)
        self.assertIn('file_id=large-photo', first_request.full_url)
        self.assertIn('/file/bottelegram-bot-token/photos/expense.jpg', second_request.full_url)
        self.assertIn('/bottelegram-bot-token/sendMessage', third_request.full_url)

    @override_settings(AI_TELEGRAM_BOT_TOKEN='telegram-bot-token')
    def test_ai_telegram_webhook_photo_preserves_amount_and_accepts_wallet_answer(self):
        client = APIClient()

        class _FakeHeaders:
            def get_content_type(self):
                return 'image/jpeg'

        class _FakeResponse:
            def __init__(self, body, headers=None):
                self._body = body
                self.headers = headers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body

        get_file_response = _FakeResponse(
            json.dumps({'ok': True, 'result': {'file_path': 'photos/history.jpg'}}).encode('utf-8')
        )
        image_response = _FakeResponse(b'fake-telegram-history-image', headers=_FakeHeaders())
        send_message_response = _FakeResponse(json.dumps({'ok': True, 'result': {'message_id': 1001}}).encode('utf-8'))
        mock_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.97,
            'amount': '-342 ₽',
            'wallet_hint': None,
            'bank_name': None,
            'merchant': 'Дикий океан',
            'description': 'Продукты',
            'comment': 'Дикий океан -342 ₽',
            'occurred_at': None,
            'operation_sign': 'outgoing',
            'include_in_budget': False,
        }

        with patch(
            'money.views.urlrequest.urlopen',
            side_effect=[
                get_file_response,
                image_response,
                send_message_response,
                send_message_response,
                send_message_response,
            ],
        ) as mocked_urlopen:
            with patch(
                'money.ai_service._get_intent_provider',
                return_value=(type('MockProvider', (), {'parse': lambda self, **kwargs: mock_provider_result})(), 'openrouter'),
            ):
                first_response = client.post(
                    '/api/v1/ai/telegram-webhook/',
                    {
                        'update_id': 333,
                        'message': {
                            'message_id': 433,
                            'photo': [
                                {'file_id': 'history-photo', 'file_size': 9000, 'width': 900, 'height': 1600},
                            ],
                            'chat': {'id': 909},
                            'from': {'id': 910, 'username': 'trialex'},
                        },
                    },
                    format='json',
                    HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                )

                pending = AiPendingConfirmation.objects.get(telegram_binding__telegram_user_id=910, is_active=True)

                second_response = client.post(
                    '/api/v1/ai/telegram-webhook/',
                    {
                        'update_id': 334,
                        'message': {
                            'message_id': 434,
                            'text': 'Альфа банк',
                            'chat': {'id': 909},
                            'from': {'id': 910, 'username': 'trialex'},
                        },
                    },
                    format='json',
                    HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                )

                third_response = client.post(
                    '/api/v1/ai/telegram-webhook/',
                    {
                        'update_id': 335,
                        'message': {
                            'message_id': 435,
                            'text': 'Создать',
                            'chat': {'id': 909},
                            'from': {'id': 910, 'username': 'trialex'},
                        },
                    },
                    format='json',
                    HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.data['status'], 'needs_confirmation')
        self.assertEqual(first_response.data['missing_fields'], ['wallet'])
        self.assertIn('Не хватает: кошелек.', first_response.data['reply_text'])
        self.assertEqual(pending.missing_fields, ['wallet'])
        self.assertEqual(pending.normalized_payload['amount'], '342.00')
        first_send_payload = json.loads(mocked_urlopen.call_args_list[2].args[0].data.decode('utf-8'))
        first_keyboard_labels = [
            button['text']
            for row in first_send_payload['reply_markup']['keyboard']
            for button in row
        ]
        self.assertIn('Альфа', first_keyboard_labels)
        self.assertIn('/cancel', first_keyboard_labels)

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.data['status'], 'needs_confirmation')
        self.assertEqual(second_response.data['missing_fields'], ['final_confirmation'])
        self.assertIn('Проверь, что будет создано:', second_response.data['reply_text'])

        self.assertEqual(third_response.status_code, 201)
        self.assertEqual(third_response.data['status'], 'created')
        expenditure = Expenditure.objects.get(id=third_response.data['created_object']['id'])
        self.assertEqual(expenditure.wallet, self.wallet_alpha)
        self.assertEqual(expenditure.cash_flow_item, self.expense_item)
        self.assertEqual(expenditure.amount, Decimal('342.00'))
        pending.refresh_from_db()
        self.assertFalse(pending.is_active)

    @override_settings(AI_TELEGRAM_BOT_TOKEN='telegram-bot-token')
    def test_ai_telegram_webhook_photo_can_create_multiple_operations_after_wallet_answer(self):
        client = APIClient()
        current_image_dt = timezone.make_aware(datetime(2026, 4, 26, 11, 35, 0))

        class _FakeHeaders:
            def get_content_type(self):
                return 'image/jpeg'

        class _FakeResponse:
            def __init__(self, body, headers=None):
                self._body = body
                self.headers = headers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body

        get_file_response = _FakeResponse(
            json.dumps({'ok': True, 'result': {'file_path': 'photos/history-multi.jpg'}}).encode('utf-8')
        )
        image_response = _FakeResponse(b'fake-telegram-history-multi-image', headers=_FakeHeaders())
        send_message_response = _FakeResponse(json.dumps({'ok': True, 'result': {'message_id': 1002}}).encode('utf-8'))
        first_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.9,
            'amount': '342.00',
            'merchant': 'Дикий океан',
            'description': 'Дикий океан',
            'comment': 'Дикий океан',
            'operation_sign': 'outgoing',
        }
        second_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.98,
            'operations': [
                {
                    'intent': 'create_expenditure',
                    'amount': '-465,75 ₽',
                    'merchant': 'Магнит',
                    'description': 'Продукты',
                    'comment': 'Магнит -465,75 ₽',
                    'occurred_at': '2024-04-25T17:35:00+03:00',
                    'operation_sign': 'outgoing',
                },
                {
                    'intent': 'create_expenditure',
                    'amount': '-342 ₽',
                    'merchant': 'Дикий океан',
                    'description': 'Продукты',
                    'comment': 'Дикий океан -342 ₽',
                    'occurred_at': '2024-04-25T16:15:00+03:00',
                    'operation_sign': 'outgoing',
                },
            ],
        }

        with patch(
            'money.views.urlrequest.urlopen',
            side_effect=[
                get_file_response,
                image_response,
                send_message_response,
                send_message_response,
                send_message_response,
            ],
        ):
            with patch(
                'money.ai_service._get_intent_provider',
                return_value=(
                    type(
                        'MockProvider',
                        (),
                        {'parse': Mock(side_effect=[first_provider_result, second_provider_result])},
                    )(),
                    'openrouter',
                ),
            ):
                with patch('money.ai_service.timezone.now', return_value=current_image_dt):
                    first_response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 335,
                            'message': {
                                'message_id': 435,
                                'photo': [
                                    {'file_id': 'history-multi-photo', 'file_size': 9000, 'width': 900, 'height': 1600},
                                ],
                                'chat': {'id': 911},
                                'from': {'id': 912, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

                    pending = AiPendingConfirmation.objects.get(telegram_binding__telegram_user_id=912, is_active=True)

                    second_response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 336,
                            'message': {
                                'message_id': 436,
                                'text': 'Кошелек альфа банк',
                                'chat': {'id': 911},
                                'from': {'id': 912, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

                    third_response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 337,
                            'message': {
                                'message_id': 437,
                                'text': 'Создать',
                                'chat': {'id': 911},
                                'from': {'id': 912, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.data['status'], 'needs_confirmation')
        self.assertEqual(first_response.data['missing_fields'], ['wallet'])
        self.assertEqual(
            first_response.data['missing_fields_by_item'],
            [
                {'index': 1, 'missing_fields': ['wallet']},
                {'index': 2, 'missing_fields': ['wallet']},
            ],
        )
        self.assertIn('Не хватает по строкам:', first_response.data['reply_text'])
        self.assertIn('Строка 1: кошелек.', first_response.data['reply_text'])
        self.assertIn('Строка 2: кошелек.', first_response.data['reply_text'])
        self.assertEqual(len(pending.normalized_payload['items']), 2)
        self.assertEqual([item['amount'] for item in pending.normalized_payload['items']], ['465.75', '342.00'])

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.data['status'], 'needs_confirmation')
        self.assertEqual(second_response.data['missing_fields'], ['final_confirmation'])
        self.assertIn('Проверь, что будет создано:', second_response.data['reply_text'])
        self.assertIn('🔴 342.00', second_response.data['reply_text'])
        self.assertIn('👛 Альфа', second_response.data['reply_text'])
        self.assertIn('🏷 Продукты', second_response.data['reply_text'])
        self.assertNotIn('комм.', second_response.data['reply_text'])

        self.assertEqual(third_response.status_code, 201)
        self.assertEqual(third_response.data['status'], 'created')
        self.assertEqual(len(third_response.data['created_objects']), 2)
        self.assertIn('Создано документов: 2.', third_response.data['reply_text'])
        self.assertIn('🔴 342.00', third_response.data['reply_text'])
        self.assertIn('🔴 465.75', third_response.data['reply_text'])
        self.assertIn('👛 Альфа', third_response.data['reply_text'])
        self.assertIn('🏷 Продукты', third_response.data['reply_text'])
        self.assertNotIn('0.00 | Без комментария', third_response.data['reply_text'])
        self.assertNotIn('комм.', third_response.data['reply_text'])
        expenditures = list(
            Expenditure.objects.filter(wallet=self.wallet_alpha, comment__icontains='₽').order_by('amount')
        )
        self.assertEqual([expense.amount for expense in expenditures], [Decimal('342.00'), Decimal('465.75')])
        self.assertEqual([expense.date for expense in expenditures], [current_image_dt, current_image_dt])
        pending.refresh_from_db()
        self.assertFalse(pending.is_active)

    @override_settings(AI_TELEGRAM_BOT_TOKEN='telegram-bot-token')
    def test_ai_telegram_webhook_photo_caption_can_exclude_transfer_before_preview(self):
        client = APIClient()
        current_image_dt = timezone.make_aware(datetime(2026, 4, 26, 11, 35, 0))

        class _FakeHeaders:
            def get_content_type(self):
                return 'image/jpeg'

        class _FakeResponse:
            def __init__(self, body, headers=None):
                self._body = body
                self.headers = headers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body

        get_file_response = _FakeResponse(
            json.dumps({'ok': True, 'result': {'file_path': 'photos/history-filter.jpg'}}).encode('utf-8')
        )
        image_response = _FakeResponse(b'fake-telegram-history-filter-image', headers=_FakeHeaders())
        send_message_response = _FakeResponse(json.dumps({'ok': True, 'result': {'message_id': 1003}}).encode('utf-8'))
        first_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.9,
            'amount': '157.97',
            'merchant': 'Пятёрочка',
            'description': 'Продукты',
            'comment': 'Пятёрочка',
            'operation_sign': 'outgoing',
        }
        second_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.98,
            'operations': [
                {
                    'intent': 'create_transfer',
                    'amount': '100000.00',
                    'merchant': 'Алексей А.',
                    'description': 'Переводы СБП Банк ВТБ',
                    'comment': 'Перевод СБП',
                    'occurred_at': '2024-04-21T17:35:00+03:00',
                    'operation_sign': 'transfer',
                },
                {
                    'intent': 'create_expenditure',
                    'amount': '-157,97 ₽',
                    'merchant': 'Пятёрочка',
                    'description': 'Продукты',
                    'comment': 'Пятёрочка -157,97 ₽',
                    'occurred_at': '2024-04-21T17:36:00+03:00',
                    'operation_sign': 'outgoing',
                },
            ],
        }

        with patch(
            'money.views.urlrequest.urlopen',
            side_effect=[
                get_file_response,
                image_response,
                send_message_response,
                send_message_response,
                send_message_response,
            ],
        ):
            with patch(
                'money.ai_service._get_intent_provider',
                return_value=(
                    type(
                        'MockProvider',
                        (),
                        {'parse': Mock(side_effect=[first_provider_result, second_provider_result])},
                    )(),
                    'openrouter',
                ),
            ):
                with patch('money.ai_service.timezone.now', return_value=current_image_dt):
                    first_response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 338,
                            'message': {
                                'message_id': 438,
                                'caption': 'Альфа\nПеревод не заноси',
                                'photo': [
                                    {'file_id': 'history-filter-photo', 'file_size': 9000, 'width': 900, 'height': 1600},
                                ],
                                'chat': {'id': 913},
                                'from': {'id': 914, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

                    pending = AiPendingConfirmation.objects.get(telegram_binding__telegram_user_id=914, is_active=True)

                    second_response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 339,
                            'message': {
                                'message_id': 439,
                                'text': 'Альфа',
                                'chat': {'id': 913},
                                'from': {'id': 914, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

                    third_response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 340,
                            'message': {
                                'message_id': 440,
                                'text': 'Создать',
                                'chat': {'id': 913},
                                'from': {'id': 914, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.data['status'], 'needs_confirmation')
        self.assertEqual(first_response.data['missing_fields'], ['wallet'])
        self.assertEqual(len(pending.normalized_payload['items']), 1)
        self.assertEqual(pending.normalized_payload['items'][0]['amount'], '157.97')

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.data['status'], 'needs_confirmation')
        self.assertEqual(second_response.data['missing_fields'], ['final_confirmation'])
        self.assertIn('Проверь, что будет создано:', second_response.data['reply_text'])
        self.assertIn('🔴 157.97', second_response.data['reply_text'])
        self.assertNotIn('100000.00', second_response.data['reply_text'])

        self.assertEqual(third_response.status_code, 201)
        self.assertEqual(third_response.data['status'], 'created')
        self.assertEqual(len(third_response.data['created_objects']), 1)
        expenditure = Expenditure.objects.get(id=third_response.data['created_object']['id'])
        self.assertEqual(expenditure.wallet, self.wallet_alpha)
        self.assertEqual(expenditure.amount, Decimal('157.97'))
        self.assertEqual(expenditure.date, current_image_dt)
        self.assertEqual(
            Expenditure.objects.filter(wallet=self.wallet_alpha, amount=Decimal('157.97')).count(),
            1,
        )
        self.assertEqual(Transfer.objects.filter(amount=Decimal('100000.00')).count(), 0)

    @override_settings(AI_TELEGRAM_BOT_TOKEN='telegram-bot-token')
    def test_ai_telegram_webhook_photo_caption_can_override_single_batch_item_category(self):
        client = APIClient()
        current_image_dt = timezone.make_aware(datetime(2026, 4, 26, 11, 35, 0))
        transport_item = CashFlowItem.objects.create(name='Транспорт', include_in_budget=True)
        CashFlowItem.objects.create(name='Фастфуд', include_in_budget=True)

        class _FakeHeaders:
            def get_content_type(self):
                return 'image/jpeg'

        class _FakeResponse:
            def __init__(self, body, headers=None):
                self._body = body
                self.headers = headers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body

        get_file_response = _FakeResponse(
            json.dumps({'ok': True, 'result': {'file_path': 'photos/history-override.jpg'}}).encode('utf-8')
        )
        image_response = _FakeResponse(b'fake-telegram-history-override-image', headers=_FakeHeaders())
        send_message_response = _FakeResponse(json.dumps({'ok': True, 'result': {'message_id': 1004}}).encode('utf-8'))
        first_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.9,
            'amount': '704.34',
            'merchant': 'Магнит',
            'description': 'Продукты',
            'comment': 'Магнит',
            'operation_sign': 'outgoing',
        }
        second_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.98,
            'operations': [
                {
                    'intent': 'create_expenditure',
                    'amount': '-704,34 ₽',
                    'merchant': 'Магнит',
                    'description': 'Продукты',
                    'comment': 'Магнит -704,34 ₽',
                    'occurred_at': '2024-04-22T17:35:00+03:00',
                    'operation_sign': 'outgoing',
                },
                {
                    'intent': 'create_expenditure',
                    'amount': '-70 ₽',
                    'merchant': 'Осетинские Пироги',
                    'description': 'Фастфуд',
                    'comment': 'Осетинские Пироги -70 ₽',
                    'occurred_at': '2024-04-22T17:36:00+03:00',
                    'operation_sign': 'outgoing',
                },
                {
                    'intent': 'create_expenditure',
                    'amount': '-48 ₽',
                    'merchant': 'Транспорт',
                    'description': 'Транспорт',
                    'comment': 'Транспорт -48 ₽',
                    'occurred_at': '2024-04-22T17:37:00+03:00',
                    'operation_sign': 'outgoing',
                },
            ],
        }

        with patch(
            'money.views.urlrequest.urlopen',
            side_effect=[
                get_file_response,
                image_response,
                send_message_response,
                send_message_response,
                send_message_response,
            ],
        ):
            with patch(
                'money.ai_service._get_intent_provider',
                return_value=(
                    type(
                        'MockProvider',
                        (),
                        {'parse': Mock(side_effect=[first_provider_result, second_provider_result])},
                    )(),
                    'openrouter',
                ),
            ):
                with patch('money.ai_service.timezone.now', return_value=current_image_dt):
                    first_response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 341,
                            'message': {
                                'message_id': 441,
                                'photo': [
                                    {'file_id': 'history-override-photo', 'file_size': 9000, 'width': 900, 'height': 1600},
                                ],
                                'chat': {'id': 915},
                                'from': {'id': 916, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

                    pending = AiPendingConfirmation.objects.get(telegram_binding__telegram_user_id=916, is_active=True)

                    second_response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 342,
                            'message': {
                                'message_id': 442,
                                'text': 'Альфа\n3 строку сделай в продукты',
                                'chat': {'id': 915},
                                'from': {'id': 916, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

                    third_response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 343,
                            'message': {
                                'message_id': 443,
                                'text': 'Создать',
                                'chat': {'id': 915},
                                'from': {'id': 916, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.data['status'], 'needs_confirmation')
        self.assertEqual(first_response.data['missing_fields'], ['wallet'])
        self.assertEqual(len(pending.normalized_payload['items']), 3)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.data['status'], 'needs_confirmation')
        self.assertEqual(second_response.data['missing_fields'], ['final_confirmation'])
        self.assertIn('3. 🔴 48.00 | 👛 Альфа | 🏷 Продукты', second_response.data['reply_text'])
        self.assertNotIn('🏷 Транспорт', second_response.data['reply_text'])

        self.assertEqual(third_response.status_code, 201)
        self.assertEqual(third_response.data['status'], 'created')
        self.assertEqual(len(third_response.data['created_objects']), 3)
        overridden_expenditure = Expenditure.objects.get(
            wallet=self.wallet_alpha,
            amount=Decimal('48.00'),
            comment__icontains='Транспорт',
        )
        self.assertEqual(overridden_expenditure.cash_flow_item, self.expense_item)
        self.assertFalse(
            Expenditure.objects.filter(
                wallet=self.wallet_alpha,
                amount=Decimal('48.00'),
                cash_flow_item=transport_item,
            ).exists()
        )
        pending.refresh_from_db()
        self.assertFalse(pending.is_active)

    @override_settings(AI_TELEGRAM_BOT_TOKEN='telegram-bot-token')
    def test_ai_telegram_webhook_batch_confirmation_uses_llm_for_line_update(self):
        client = APIClient()
        current_image_dt = timezone.make_aware(datetime(2026, 4, 26, 11, 35, 0))

        class _FakeHeaders:
            def get_content_type(self):
                return 'image/jpeg'

        class _FakeResponse:
            def __init__(self, body, headers=None):
                self._body = body
                self.headers = headers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body

        get_file_response = _FakeResponse(
            json.dumps({'ok': True, 'result': {'file_path': 'photos/history-llm-revise.jpg'}}).encode('utf-8')
        )
        image_response = _FakeResponse(b'fake-telegram-history-llm-revise-image', headers=_FakeHeaders())
        send_message_response = _FakeResponse(json.dumps({'ok': True, 'result': {'message_id': 1005}}).encode('utf-8'))
        first_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.9,
            'amount': '704.34',
            'merchant': 'Магнит',
            'description': 'Продукты',
            'comment': 'Магнит',
            'operation_sign': 'outgoing',
        }
        second_provider_result = {
            'intent': 'create_expenditure',
            'confidence': 0.98,
            'operations': [
                {
                    'source_index': 1,
                    'intent': 'create_expenditure',
                    'amount': '-704,34 ₽',
                    'merchant': 'Магнит',
                    'description': 'Продукты',
                    'comment': 'Магнит -704,34 ₽',
                    'occurred_at': '2024-04-22T17:35:00+03:00',
                    'operation_sign': 'outgoing',
                },
                {
                    'source_index': 2,
                    'intent': 'create_expenditure',
                    'amount': '-70 ₽',
                    'merchant': 'Осетинские Пироги',
                    'description': None,
                    'comment': 'Осетинские Пироги -70 ₽',
                    'occurred_at': '2024-04-22T17:36:00+03:00',
                    'operation_sign': 'outgoing',
                },
            ],
        }
        revised_provider_result = {
            'intent': 'create_multiple_operations',
            'confidence': 0.99,
            'operations': [
                {
                    'source_index': 1,
                    'intent': 'create_expenditure',
                    'amount': '704.34',
                    'wallet_id': str(self.wallet_alpha.id),
                    'cash_flow_item_id': str(self.expense_item.id),
                    'merchant': 'Магнит',
                    'description': 'Продукты',
                    'comment': 'Магнит -704,34 ₽',
                    'occurred_at': '2024-04-22T17:35:00+03:00',
                    'operation_sign': 'outgoing',
                },
                {
                    'source_index': 2,
                    'intent': 'create_expenditure',
                    'amount': '70.00',
                    'wallet_id': str(self.wallet_alpha.id),
                    'cash_flow_item_id': str(self.expense_item.id),
                    'merchant': 'Осетинские Пироги',
                    'description': 'Продукты',
                    'comment': 'Осетинские Пироги -70 ₽',
                    'occurred_at': '2024-04-22T17:36:00+03:00',
                    'operation_sign': 'outgoing',
                },
            ],
        }
        provider = type(
            'MockProvider',
            (),
            {
                'parse': Mock(side_effect=[first_provider_result, second_provider_result]),
                'revise_batch_confirmation': Mock(return_value=revised_provider_result),
            },
        )()

        with patch(
            'money.views.urlrequest.urlopen',
            side_effect=[
                get_file_response,
                image_response,
                send_message_response,
                send_message_response,
                send_message_response,
            ],
        ):
            with patch(
                'money.ai_service._get_intent_provider',
                return_value=(provider, 'openrouter'),
            ):
                with patch('money.ai_service.timezone.now', return_value=current_image_dt):
                    first_response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 344,
                            'message': {
                                'message_id': 444,
                                'caption': '',
                                'photo': [
                                    {'file_id': 'history-llm-revise-photo', 'file_size': 9000, 'width': 900, 'height': 1600},
                                ],
                                'chat': {'id': 917},
                                'from': {'id': 918, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

                    pending = AiPendingConfirmation.objects.get(telegram_binding__telegram_user_id=918, is_active=True)

                    second_response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 345,
                            'message': {
                                'message_id': 445,
                                'text': 'Альфа\n2. продукты',
                                'chat': {'id': 917},
                                'from': {'id': 918, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

                    third_response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 346,
                            'message': {
                                'message_id': 446,
                                'text': 'Создать',
                                'chat': {'id': 917},
                                'from': {'id': 918, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.data['status'], 'needs_confirmation')
        self.assertEqual(first_response.data['missing_fields'], ['wallet', 'cash_flow_item'])
        self.assertEqual(
            first_response.data['missing_fields_by_item'],
            [
                {'index': 1, 'missing_fields': ['wallet']},
                {'index': 2, 'missing_fields': ['wallet', 'cash_flow_item']},
            ],
        )
        self.assertIn('Строка 1: кошелек.', first_response.data['reply_text'])
        self.assertIn('Строка 2: кошелек, статья движения.', first_response.data['reply_text'])
        self.assertTrue(pending.context_payload.get('image_base64'))

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.data['status'], 'needs_confirmation')
        self.assertEqual(second_response.data['missing_fields'], ['final_confirmation'])
        self.assertIn('2. 🔴 70.00 | 👛 Альфа | 🏷 Продукты', second_response.data['reply_text'])
        provider.revise_batch_confirmation.assert_called_once()

        self.assertEqual(third_response.status_code, 201)
        self.assertEqual(third_response.data['status'], 'created')
        self.assertEqual(len(third_response.data['created_objects']), 2)
        self.assertEqual(
            Expenditure.objects.filter(
                wallet=self.wallet_alpha,
                cash_flow_item=self.expense_item,
                amount=Decimal('70.00'),
                comment__icontains='Осетинские Пироги',
            ).count(),
            1,
        )

    def test_ai_telegram_webhook_transcribes_voice_and_creates_expenditure(self):
        client = APIClient()

        with patch(
            'money.views.AiAssistantViewSet._download_telegram_audio',
            return_value=(b'fake-telegram-voice', 'audio/ogg', 'expense.ogg'),
        ) as mocked_download_audio:
            with patch(
                'money.ai_service.AiOperationService.transcribe_audio',
                return_value='расход сбер еда 2500',
            ) as mocked_transcribe_audio:
                with patch('money.views.AiAssistantViewSet._send_telegram_reply', return_value=None):
                    response = client.post(
                        '/api/v1/ai/telegram-webhook/',
                        {
                            'update_id': 188,
                            'message': {
                                'message_id': 198,
                                'voice': {
                                    'file_id': 'voice-file',
                                    'file_size': 1024,
                                    'duration': 4,
                                    'mime_type': 'audio/ogg',
                                },
                                'chat': {'id': 1808},
                                'from': {'id': 1908, 'username': 'trialex'},
                            },
                        },
                        format='json',
                        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
                    )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'created')
        expenditure = Expenditure.objects.get(id=response.data['created_object']['id'])
        self.assertEqual(expenditure.wallet, self.wallet_sber)
        self.assertEqual(expenditure.cash_flow_item, self.expense_item)
        self.assertEqual(expenditure.amount, Decimal('2500.00'))
        mocked_download_audio.assert_called_once()
        mocked_transcribe_audio.assert_called_once_with(
            audio_bytes=b'fake-telegram-voice',
            audio_mime_type='audio/ogg',
            file_name='expense.ogg',
        )

    @override_settings(AI_TELEGRAM_BOT_TOKEN='telegram-bot-token')
    def test_ai_telegram_webhook_sends_reply_message(self):
        client = APIClient()

        class _FakeResponse:
            def __init__(self, body):
                self._body = body
                self.headers = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body

        send_message_response = _FakeResponse(json.dumps({'ok': True, 'result': {'message_id': 111}}).encode('utf-8'))

        with patch('money.views.urlrequest.urlopen', return_value=send_message_response) as mocked_urlopen:
            response = client.post(
                '/api/v1/ai/telegram-webhook/',
                {
                    'update_id': 501,
                    'message': {
                        'message_id': 601,
                        'text': 'остатки по кошелькам',
                        'chat': {'id': 701},
                        'from': {'id': 801, 'username': 'trialex'},
                    },
                },
                format='json',
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
            )

        self.assertEqual(response.status_code, 200)
        send_request = mocked_urlopen.call_args.args[0]
        self.assertIn('/bottelegram-bot-token/sendMessage', send_request.full_url)
        self.assertEqual(json.loads(send_request.data.decode('utf-8'))['chat_id'], 701)

    def test_ai_telegram_webhook_auto_binds_user_by_matching_username(self):
        client = APIClient()
        response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 2,
                'message': {
                    'message_id': 11,
                    'text': 'остатки по кошелькам',
                    'chat': {'id': 101},
                    'from': {'id': 201, 'username': 'trialex'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'balance')
        binding = TelegramUserBinding.objects.get(telegram_user_id=201)
        self.assertEqual(binding.user, self.telegram_bound_user)
        self.assertIsNotNone(binding.linked_at)

    def test_generate_telegram_link_token_and_bind_via_command(self):
        web_client = APIClient()
        web_client.force_authenticate(self.regular_user)
        token_response = web_client.post('/api/v1/ai/telegram-link-token/')

        self.assertEqual(token_response.status_code, 200)
        code = token_response.data['code']
        self.assertTrue(TelegramLinkToken.objects.filter(code=code, user=self.regular_user, is_used=False).exists())

        client = APIClient()
        bind_response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 21,
                'message': {
                    'message_id': 31,
                    'text': f'/link {code}',
                    'chat': {'id': 301},
                    'from': {'id': 401, 'username': 'random-telegram'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )

        self.assertEqual(bind_response.status_code, 201)
        binding = TelegramUserBinding.objects.get(telegram_user_id=401)
        self.assertEqual(binding.user, self.regular_user)
        token = TelegramLinkToken.objects.get(code=code)
        self.assertTrue(token.is_used)

    def test_ai_telegram_webhook_unlink_command_keeps_non_normalized_parsed_payload(self):
        TelegramUserBinding.objects.create(
            telegram_user_id=402,
            telegram_chat_id=302,
            telegram_username='linked-telegram',
            user=self.regular_user,
            linked_at=timezone.now(),
        )

        client = APIClient()
        response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 22,
                'message': {
                    'message_id': 32,
                    'text': '/unlink',
                    'chat': {'id': 302},
                    'from': {'id': 402, 'username': 'linked-telegram'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )

        self.assertEqual(response.status_code, 201)
        binding = TelegramUserBinding.objects.get(telegram_user_id=402)
        self.assertIsNone(binding.user)
        audit_log = AiAuditLog.objects.filter(telegram_binding=binding).order_by('-created_at').first()
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.normalized_payload, {'source': 'telegram'})
        self.assertEqual(response.data['parsed'], {'source': 'telegram'})

    def test_ai_telegram_webhook_uses_pending_confirmation_for_missing_item(self):
        client = APIClient()
        first_response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 3,
                'message': {
                    'message_id': 12,
                    'text': 'приход сбербанк 10000',
                    'chat': {'id': 102},
                    'from': {'id': 202, 'username': 'trialex'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.data['status'], 'needs_confirmation')
        pending = AiPendingConfirmation.objects.get(telegram_binding__telegram_user_id=202, is_active=True)
        self.assertEqual(pending.missing_fields, ['cash_flow_item'])

        second_response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 4,
                'message': {
                    'message_id': 13,
                    'text': 'зарплата',
                    'chat': {'id': 102},
                    'from': {'id': 202, 'username': 'trialex'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )

        self.assertEqual(second_response.status_code, 201)
        self.assertEqual(second_response.data['status'], 'created')
        receipt = Receipt.objects.get(id=second_response.data['created_object']['id'])
        self.assertEqual(receipt.wallet, self.wallet_sber)
        self.assertEqual(receipt.cash_flow_item, self.income_item)
        pending.refresh_from_db()
        self.assertFalse(pending.is_active)

    def test_ai_telegram_webhook_balance_request_bypasses_active_pending_confirmation(self):
        client = APIClient()
        Receipt.objects.create(
            amount=Decimal('500.00'),
            wallet=self.wallet_alpha,
            cash_flow_item=self.income_item,
            date=timezone.make_aware(datetime(2026, 4, 27, 12, 0, 0)),
        )

        first_response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 4301,
                'message': {
                    'message_id': 4302,
                    'text': 'приход сбербанк 10000',
                    'chat': {'id': 4303},
                    'from': {'id': 4304, 'username': 'trialex'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )

        self.assertEqual(first_response.status_code, 200)
        pending = AiPendingConfirmation.objects.get(telegram_binding__telegram_user_id=4304, is_active=True)

        second_response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 4305,
                'message': {
                    'message_id': 4306,
                    'text': 'Какой остаток на альфа',
                    'chat': {'id': 4303},
                    'from': {'id': 4304, 'username': 'trialex'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.data['status'], 'balance')
        self.assertIn('Альфа', second_response.data['reply_text'])
        pending.refresh_from_db()
        self.assertFalse(pending.is_active)

    def test_ai_telegram_webhook_can_select_option_by_number(self):
        client = APIClient()
        first_response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 41,
                'message': {
                    'message_id': 51,
                    'text': 'приход сбербанк 10000',
                    'chat': {'id': 402},
                    'from': {'id': 502, 'username': 'trialex'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.data['status'], 'needs_confirmation')
        self.assertIn('options', first_response.data)

        second_response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 42,
                'message': {
                    'message_id': 52,
                    'text': '1',
                    'chat': {'id': 402},
                    'from': {'id': 502, 'username': 'trialex'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )
        self.assertEqual(second_response.status_code, 201)
        self.assertEqual(second_response.data['status'], 'created')

    def test_ai_telegram_webhook_cancel_closes_pending_confirmation(self):
        client = APIClient()
        client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 61,
                'message': {
                    'message_id': 71,
                    'text': 'приход сбербанк 10000',
                    'chat': {'id': 502},
                    'from': {'id': 602, 'username': 'trialex'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )
        cancel_response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 62,
                'message': {
                    'message_id': 72,
                    'text': '/cancel',
                    'chat': {'id': 502},
                    'from': {'id': 602, 'username': 'trialex'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )

        self.assertEqual(cancel_response.status_code, 200)
        pending = AiPendingConfirmation.objects.get(telegram_binding__telegram_user_id=602)
        self.assertFalse(pending.is_active)

    def test_ai_telegram_webhook_returns_duplicate_for_repeated_update(self):
        client = APIClient()
        first_response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 5,
                'message': {
                    'message_id': 14,
                    'text': 'расход сбер еда 2500',
                    'chat': {'id': 103},
                    'from': {'id': 203, 'username': 'trialex'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )
        second_response = client.post(
            '/api/v1/ai/telegram-webhook/',
            {
                'update_id': 5,
                'message': {
                    'message_id': 14,
                    'text': 'расход сбер еда 2500',
                    'chat': {'id': 103},
                    'from': {'id': 203, 'username': 'trialex'},
                },
            },
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='telegram-secret',
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.data['status'], 'duplicate')
        self.assertEqual(
            Expenditure.objects.filter(wallet=self.wallet_sber, cash_flow_item=self.expense_item, amount=Decimal('2500.00')).count(),
            1,
        )

    def test_ai_creates_audit_logs(self):
        response = self.client.post(
            '/api/v1/ai/execute/',
            {'text': 'расход сбер еда 2500'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        audit = AiAuditLog.objects.order_by('-created_at').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.source, 'web')
        self.assertEqual(audit.provider, 'rule_based')
        self.assertEqual(audit.user, self.admin_user)
        self.assertEqual(audit.final_response_payload['status'], 'created')

    def test_openapi_schema_contains_ai_endpoints(self):
        response = self.client.get('/api/schema/')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('/api/v1/ai/execute/', content)
        self.assertIn('/api/v1/ai/telegram-webhook/', content)
        self.assertIn('/api/v1/ai/telegram-link-token/', content)
