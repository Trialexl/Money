from django.db import migrations


def delete_acknowledged_outbox_rows(apps, schema_editor):
    OneCSyncOutbox = apps.get_model('money', 'OneCSyncOutbox')
    OneCSyncOutbox.objects.using(schema_editor.connection.alias).filter(
        acknowledged_at__isnull=False
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('money', '0027_ai_processed_semantic_fingerprint'),
    ]

    operations = [
        migrations.RunPython(
            delete_acknowledged_outbox_rows,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name='onecsyncoutbox',
            name='acknowledged_at',
        ),
    ]
