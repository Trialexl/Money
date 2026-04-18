from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('money', '0028_make_onec_outbox_ephemeral'),
    ]

    operations = [
        migrations.AddField(
            model_name='receipt',
            name='posted',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='expenditure',
            name='posted',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='transfer',
            name='posted',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='budget',
            name='posted',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='autopayment',
            name='posted',
            field=models.BooleanField(default=True),
        ),
    ]
