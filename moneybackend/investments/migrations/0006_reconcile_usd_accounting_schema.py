from django.db import migrations


def _column_exists(schema_editor, cursor, table_name, column_name):
    description = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return column_name in {column.name for column in description}


def _drop_column_if_exists(schema_editor, cursor, table_name, column_name):
    if _column_exists(schema_editor, cursor, table_name, column_name):
        table = schema_editor.quote_name(table_name)
        column = schema_editor.quote_name(column_name)
        cursor.execute(f'ALTER TABLE {table} DROP COLUMN {column}')


def _rename_or_copy_column(schema_editor, cursor, table_name, old_name, new_name, column_definition):
    old_exists = _column_exists(schema_editor, cursor, table_name, old_name)
    new_exists = _column_exists(schema_editor, cursor, table_name, new_name)
    table = schema_editor.quote_name(table_name)
    old_column = schema_editor.quote_name(old_name)
    new_column = schema_editor.quote_name(new_name)

    if old_exists and not new_exists:
        cursor.execute(f'ALTER TABLE {table} RENAME COLUMN {old_column} TO {new_column}')
        return

    if not new_exists:
        cursor.execute(f'ALTER TABLE {table} ADD COLUMN {new_column} {column_definition}')
        return

    if old_exists:
        cursor.execute(
            f'UPDATE {table} SET {new_column} = {old_column} '
            f'WHERE {new_column} IS NULL AND {old_column} IS NOT NULL'
        )
        _drop_column_if_exists(schema_editor, cursor, table_name, old_name)


def reconcile_usd_accounting_schema(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        _rename_or_copy_column(
            schema_editor,
            cursor,
            'investments_instrumentpricesnapshot',
            'fx_rate_to_rub',
            'fx_rate_to_usd',
            'numeric(18,8) NOT NULL DEFAULT 1',
        )
        _rename_or_copy_column(
            schema_editor,
            cursor,
            'investments_instrumentpricesnapshot',
            'price_rub',
            'price_usd',
            'numeric(18,2) NOT NULL DEFAULT 0',
        )
        _rename_or_copy_column(
            schema_editor,
            cursor,
            'investments_investmentoperation',
            'price',
            'price_usd',
            'numeric(24,8) NULL',
        )
        _rename_or_copy_column(
            schema_editor,
            cursor,
            'investments_investmentoperation',
            'amount_rub',
            'amount_usd',
            'numeric(18,2) NOT NULL DEFAULT 0',
        )
        _rename_or_copy_column(
            schema_editor,
            cursor,
            'investments_investmentoperation',
            'amount',
            'amount_usd',
            'numeric(18,2) NOT NULL DEFAULT 0',
        )
        _rename_or_copy_column(
            schema_editor,
            cursor,
            'investments_investmentoperation',
            'fee_rub',
            'fee_usd',
            'numeric(18,2) NOT NULL DEFAULT 0',
        )
        _rename_or_copy_column(
            schema_editor,
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
            _drop_column_if_exists(schema_editor, cursor, 'investments_investmentoperation', legacy_column)


class Migration(migrations.Migration):

    dependencies = [
        ('investments', '0005_usd_accounting'),
    ]

    operations = [
        migrations.RunPython(reconcile_usd_accounting_schema, migrations.RunPython.noop),
    ]
