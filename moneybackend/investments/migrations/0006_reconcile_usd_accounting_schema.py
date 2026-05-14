from django.db import migrations


def _column_exists(cursor, table_name, column_name):
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %s
              AND column_name = %s
        )
        """,
        [table_name, column_name],
    )
    return cursor.fetchone()[0]


def _drop_column_if_exists(cursor, table_name, column_name):
    if _column_exists(cursor, table_name, column_name):
        cursor.execute(f'ALTER TABLE "{table_name}" DROP COLUMN "{column_name}"')


def _rename_or_copy_column(cursor, table_name, old_name, new_name, column_definition):
    old_exists = _column_exists(cursor, table_name, old_name)
    new_exists = _column_exists(cursor, table_name, new_name)

    if old_exists and not new_exists:
        cursor.execute(f'ALTER TABLE "{table_name}" RENAME COLUMN "{old_name}" TO "{new_name}"')
        return

    if not new_exists:
        cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{new_name}" {column_definition}')
        return

    if old_exists:
        cursor.execute(
            f'UPDATE "{table_name}" SET "{new_name}" = "{old_name}" '
            f'WHERE "{new_name}" IS NULL AND "{old_name}" IS NOT NULL'
        )
        _drop_column_if_exists(cursor, table_name, old_name)


def reconcile_usd_accounting_schema(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        _rename_or_copy_column(
            cursor,
            'investments_instrumentpricesnapshot',
            'fx_rate_to_rub',
            'fx_rate_to_usd',
            'numeric(18,8) NOT NULL DEFAULT 1',
        )
        _rename_or_copy_column(
            cursor,
            'investments_instrumentpricesnapshot',
            'price_rub',
            'price_usd',
            'numeric(18,2) NOT NULL DEFAULT 0',
        )
        _rename_or_copy_column(
            cursor,
            'investments_investmentoperation',
            'price',
            'price_usd',
            'numeric(24,8) NULL',
        )
        _rename_or_copy_column(
            cursor,
            'investments_investmentoperation',
            'amount_rub',
            'amount_usd',
            'numeric(18,2) NOT NULL DEFAULT 0',
        )
        _rename_or_copy_column(
            cursor,
            'investments_investmentoperation',
            'amount',
            'amount_usd',
            'numeric(18,2) NOT NULL DEFAULT 0',
        )
        _rename_or_copy_column(
            cursor,
            'investments_investmentoperation',
            'fee_rub',
            'fee_usd',
            'numeric(18,2) NOT NULL DEFAULT 0',
        )
        _rename_or_copy_column(
            cursor,
            'investments_investmentoperation',
            'fee_amount',
            'fee_usd',
            'numeric(18,2) NOT NULL DEFAULT 0',
        )
        for legacy_column in [
            'amount_currency',
            'fee_currency',
            'fx_rate_to_rub',
            'fx_rate_to_usd',
            'price_currency',
        ]:
            _drop_column_if_exists(cursor, 'investments_investmentoperation', legacy_column)


class Migration(migrations.Migration):

    dependencies = [
        ('investments', '0005_usd_accounting'),
    ]

    operations = [
        migrations.RunPython(reconcile_usd_accounting_schema, migrations.RunPython.noop),
    ]
