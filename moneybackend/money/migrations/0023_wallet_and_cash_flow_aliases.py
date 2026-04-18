from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('money', '0022_onec_sync_outbox'),
    ]

    operations = [
        migrations.CreateModel(
            name='CashFlowItemAlias',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('alias', models.CharField(max_length=50)),
                (
                    'cash_flow_item',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='aliases',
                        to='money.cashflowitem',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Псевдоним статьи',
                'verbose_name_plural': 'Псевдонимы статей',
                'ordering': ['alias'],
            },
        ),
        migrations.CreateModel(
            name='WalletAlias',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('alias', models.CharField(max_length=50)),
                (
                    'wallet',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='aliases',
                        to='money.wallet',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Псевдоним кошелька',
                'verbose_name_plural': 'Псевдонимы кошельков',
                'ordering': ['alias'],
            },
        ),
        migrations.AddConstraint(
            model_name='cashflowitemalias',
            constraint=models.UniqueConstraint(fields=('cash_flow_item', 'alias'), name='uniq_cash_flow_item_alias'),
        ),
        migrations.AddConstraint(
            model_name='walletalias',
            constraint=models.UniqueConstraint(fields=('wallet', 'alias'), name='uniq_wallet_alias'),
        ),
    ]
