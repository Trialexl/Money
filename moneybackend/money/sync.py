from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_save, pre_delete

from .onec_context import is_outbox_sync_suppressed
from .models import (
    AutoPayment,
    AutoPaymentGraphic,
    Budget,
    BudgetGraphic,
    CashFlowItem,
    Expenditure,
    ExpenditureGraphic,
    OneCSyncOutbox,
    Project,
    Receipt,
    Transfer,
    TransferGraphic,
    Wallet,
)


def _serialize_uuid(value):
    return str(value) if value is not None else None


def _serialize_datetime(value):
    return value.isoformat() if value is not None else None


def _serialize_decimal(value):
    return f'{value:.2f}' if value is not None else None


def _serialize_graphics(rows):
    return [
        {
            'date_start': _serialize_datetime(row.date_start),
            'amount': _serialize_decimal(row.amount),
        }
        for row in rows.order_by('date_start')
    ]


def _cash_flow_item_payload(instance):
    return {
        'id': _serialize_uuid(instance.id),
        'code': instance.code,
        'name': instance.name,
        'deleted': instance.deleted,
        'include_in_budget': instance.include_in_budget,
        'parent': _serialize_uuid(instance.parent_id),
    }


def _wallet_payload(instance):
    return {
        'id': _serialize_uuid(instance.id),
        'code': instance.code,
        'name': instance.name,
        'deleted': instance.deleted,
        'hidden': instance.hidden,
    }


def _project_payload(instance):
    return {
        'id': _serialize_uuid(instance.id),
        'code': instance.code,
        'name': instance.name,
        'deleted': instance.deleted,
    }


def _receipt_payload(instance):
    return {
        'id': _serialize_uuid(instance.id),
        'number': instance.number,
        'date': _serialize_datetime(instance.date),
        'deleted': instance.deleted,
        'posted': instance.posted,
        'wallet': _serialize_uuid(instance.wallet_id),
        'cash_flow_item': _serialize_uuid(instance.cash_flow_item_id),
        'amount': _serialize_decimal(instance.amount),
        'comment': instance.comment,
    }


def _expenditure_payload(instance):
    return {
        'id': _serialize_uuid(instance.id),
        'number': instance.number,
        'date': _serialize_datetime(instance.date),
        'deleted': instance.deleted,
        'posted': instance.posted,
        'wallet': _serialize_uuid(instance.wallet_id),
        'cash_flow_item': _serialize_uuid(instance.cash_flow_item_id),
        'amount': _serialize_decimal(instance.amount),
        'comment': instance.comment,
        'include_in_budget': instance.include_in_budget,
        'graphics': _serialize_graphics(instance.items.all()),
    }


def _transfer_payload(instance):
    return {
        'id': _serialize_uuid(instance.id),
        'number': instance.number,
        'date': _serialize_datetime(instance.date),
        'deleted': instance.deleted,
        'posted': instance.posted,
        'wallet_out': _serialize_uuid(instance.wallet_out_id),
        'wallet_in': _serialize_uuid(instance.wallet_in_id),
        'cash_flow_item': _serialize_uuid(instance.cash_flow_item_id),
        'amount': _serialize_decimal(instance.amount),
        'comment': instance.comment,
        'include_in_budget': instance.include_in_budget,
        'graphics': _serialize_graphics(instance.items.all()),
    }


def _budget_payload(instance):
    return {
        'id': _serialize_uuid(instance.id),
        'number': instance.number,
        'date': _serialize_datetime(instance.date),
        'deleted': instance.deleted,
        'posted': instance.posted,
        'cash_flow_item': _serialize_uuid(instance.cash_flow_item_id),
        'amount_month': instance.amount_month,
        'amount': _serialize_decimal(instance.amount),
        'date_start': _serialize_datetime(instance.date_start),
        'comment': instance.comment,
        'project': _serialize_uuid(instance.project_id),
        'type_of_budget': instance.type_of_budget,
        'graphics': _serialize_graphics(instance.items.all()),
    }


def _autopayment_payload(instance):
    return {
        'id': _serialize_uuid(instance.id),
        'number': instance.number,
        'date': _serialize_datetime(instance.date),
        'deleted': instance.deleted,
        'posted': instance.posted,
        'wallet_in': _serialize_uuid(instance.wallet_in_id),
        'wallet_out': _serialize_uuid(instance.wallet_out_id),
        'cash_flow_item': _serialize_uuid(instance.cash_flow_item_id),
        'is_transfer': instance.is_transfer,
        'amount_month': instance.amount_month,
        'amount': _serialize_decimal(instance.amount),
        'comment': instance.comment,
        'date_start': _serialize_datetime(instance.date_start),
        'graphics': _serialize_graphics(instance.items.all()),
    }


def _user_payload(instance):
    return {
        'id': _serialize_uuid(instance.id),
        'username': instance.username,
        'full_name': instance.full_name,
        'status': instance.status,
        'tax_id': instance.tax_id,
        'is_active': instance.is_active,
    }


UserModel = get_user_model()


SYNC_MODEL_CONFIG = {
    CashFlowItem: {
        'entity_type': 'cash_flow_item',
        'route': 'cash-flow-items',
        'payload_builder': _cash_flow_item_payload,
    },
    Wallet: {
        'entity_type': 'wallet',
        'route': 'wallets',
        'payload_builder': _wallet_payload,
    },
    Project: {
        'entity_type': 'project',
        'route': 'projects',
        'payload_builder': _project_payload,
    },
    Receipt: {
        'entity_type': 'receipt',
        'route': 'receipts',
        'payload_builder': _receipt_payload,
    },
    Expenditure: {
        'entity_type': 'expenditure',
        'route': 'expenditures',
        'graphics_route': 'expenditure-graphics',
        'clear_type': 'ExpenditureGraphics',
        'payload_builder': _expenditure_payload,
    },
    Transfer: {
        'entity_type': 'transfer',
        'route': 'transfers',
        'graphics_route': 'transfer-graphics',
        'clear_type': 'TransferGraphics',
        'payload_builder': _transfer_payload,
    },
    Budget: {
        'entity_type': 'budget',
        'route': 'budgets',
        'graphics_route': 'budget-graphics',
        'clear_type': 'BudgetGraphics',
        'payload_builder': _budget_payload,
    },
    AutoPayment: {
        'entity_type': 'auto_payment',
        'route': 'auto-payments',
        'graphics_route': 'auto-payment-graphics',
        'clear_type': 'AutoPaymentGraphics',
        'payload_builder': _autopayment_payload,
    },
    UserModel: {
        'entity_type': 'user',
        'route': 'users',
        'payload_builder': _user_payload,
    },
}


GRAPHIC_PARENT_MODELS = {
    ExpenditureGraphic: Expenditure,
    TransferGraphic: Transfer,
    BudgetGraphic: Budget,
    AutoPaymentGraphic: AutoPayment,
}


def _delete_payload(instance):
    payload = {'id': _serialize_uuid(instance.pk)}
    if hasattr(instance, 'deleted'):
        payload['deleted'] = True
    elif hasattr(instance, 'is_active'):
        payload['is_active'] = False
    return payload


def queue_instance_sync(instance, operation=OneCSyncOutbox.UPSERT):
    from django.utils import timezone

    config = SYNC_MODEL_CONFIG.get(instance.__class__)
    if config is None:
        return
    if is_outbox_sync_suppressed():
        return

    payload_builder = config['payload_builder']
    payload = payload_builder(instance) if operation == OneCSyncOutbox.UPSERT else _delete_payload(instance)

    OneCSyncOutbox.objects.update_or_create(
        entity_type=config['entity_type'],
        object_id=instance.pk,
        defaults={
            'route': config['route'],
            'clear_type': config.get('clear_type', ''),
            'graphics_route': config.get('graphics_route', ''),
            'operation': operation,
            'payload': payload,
            'changed_at': timezone.now(),
        },
    )


def _queue_parent_document(parent_model, parent_id):
    try:
        parent = parent_model.objects.get(pk=parent_id)
    except parent_model.DoesNotExist:
        return
    queue_instance_sync(parent, operation=OneCSyncOutbox.UPSERT)


def register_sync_signals():
    for model in SYNC_MODEL_CONFIG:
        post_save.connect(
            _top_level_post_save,
            sender=model,
            weak=False,
            dispatch_uid=f'money_sync_post_save_{model._meta.label_lower}',
        )
        pre_delete.connect(
            _top_level_pre_delete,
            sender=model,
            weak=False,
            dispatch_uid=f'money_sync_pre_delete_{model._meta.label_lower}',
        )

    for model in GRAPHIC_PARENT_MODELS:
        post_save.connect(
            _graphic_post_save,
            sender=model,
            weak=False,
            dispatch_uid=f'money_sync_graphic_post_save_{model._meta.label_lower}',
        )
        pre_delete.connect(
            _graphic_pre_delete,
            sender=model,
            weak=False,
            dispatch_uid=f'money_sync_graphic_pre_delete_{model._meta.label_lower}',
        )


def _top_level_post_save(sender, instance, **kwargs):
    transaction.on_commit(lambda: queue_instance_sync(instance, operation=OneCSyncOutbox.UPSERT))


def _top_level_pre_delete(sender, instance, **kwargs):
    transaction.on_commit(lambda: queue_instance_sync(instance, operation=OneCSyncOutbox.DELETE))


def _graphic_post_save(sender, instance, **kwargs):
    parent_model = GRAPHIC_PARENT_MODELS[sender]
    parent_id = instance.document_id
    transaction.on_commit(lambda: _queue_parent_document(parent_model, parent_id))


def _graphic_pre_delete(sender, instance, **kwargs):
    parent_model = GRAPHIC_PARENT_MODELS[sender]
    parent_id = instance.document_id
    transaction.on_commit(lambda: _queue_parent_document(parent_model, parent_id))
