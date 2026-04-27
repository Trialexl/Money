from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('money', '0029_document_posted_flag'),
    ]

    operations = [
        migrations.AddField(
            model_name='aipendingconfirmation',
            name='context_payload',
            field=models.JSONField(default=dict),
        ),
    ]
