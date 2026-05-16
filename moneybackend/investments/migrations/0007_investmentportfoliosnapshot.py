import uuid
from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('investments', '0006_reconcile_usd_accounting_schema'),
    ]

    operations = [
        migrations.AddField(
            model_name='instrumentpricesnapshot',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, blank=True, null=True),
        ),
        migrations.CreateModel(
            name='InvestmentPortfolioSnapshot',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('snapshot_date', models.DateField()),
                ('cost_basis_usd', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=18)),
                ('current_value_usd', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=18)),
                ('realized_pl_usd', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=18)),
                ('unrealized_pl_usd', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=18)),
                ('total_pl_usd', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=18)),
                ('return_percent', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('valuation_complete', models.BooleanField(default=False)),
                ('bought_usd', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=18)),
                ('sold_usd', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=18)),
                ('latest_price_at', models.DateTimeField(blank=True, null=True)),
                ('positions_payload', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('portfolio', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='snapshots', to='investments.investmentportfolio')),
            ],
            options={
                'verbose_name': 'Снимок инвестиционного портфеля',
                'verbose_name_plural': 'Снимки инвестиционных портфелей',
                'ordering': ['portfolio', '-snapshot_date'],
            },
        ),
        migrations.AddIndex(
            model_name='investmentportfoliosnapshot',
            index=models.Index(fields=['portfolio', '-snapshot_date'], name='investments_portfol_407fc4_idx'),
        ),
        migrations.AddConstraint(
            model_name='investmentportfoliosnapshot',
            constraint=models.UniqueConstraint(fields=('portfolio', 'snapshot_date'), name='uniq_portfolio_snapshot_date'),
        ),
    ]
