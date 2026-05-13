from decimal import Decimal

from django.db import migrations, models
from django.db.models import F


CURRENCY_CHOICES = [('USD', 'USD'), ('EUR', 'EUR'), ('RUB', 'RUB')]


def normalize_existing_currencies(apps, schema_editor):
    InvestmentPortfolio = apps.get_model('investments', 'InvestmentPortfolio')
    InvestmentAccount = apps.get_model('investments', 'InvestmentAccount')
    InstrumentPriceSnapshot = apps.get_model('investments', 'InstrumentPriceSnapshot')
    FxRateSnapshot = apps.get_model('investments', 'FxRateSnapshot')

    InvestmentPortfolio.objects.update(base_currency='USD')
    InvestmentAccount.objects.filter(currency__isnull=True).update(currency='USD')
    InvestmentAccount.objects.filter(currency='').update(currency='USD')
    InstrumentPriceSnapshot.objects.update(
        price_currency='USD',
        fx_rate_to_usd=Decimal('1'),
        price_usd=F('price'),
    )
    FxRateSnapshot.objects.filter(quote_currency__isnull=True).update(quote_currency='USD')
    FxRateSnapshot.objects.filter(quote_currency='').update(quote_currency='USD')


class Migration(migrations.Migration):

    dependencies = [
        ('investments', '0004_investmenttargetallocation'),
    ]

    operations = [
        migrations.RenameField(
            model_name='instrumentpricesnapshot',
            old_name='fx_rate_to_rub',
            new_name='fx_rate_to_usd',
        ),
        migrations.RenameField(
            model_name='instrumentpricesnapshot',
            old_name='price_rub',
            new_name='price_usd',
        ),
        migrations.RenameField(
            model_name='investmentoperation',
            old_name='price',
            new_name='price_usd',
        ),
        migrations.RenameField(
            model_name='investmentoperation',
            old_name='amount_rub',
            new_name='amount_usd',
        ),
        migrations.RenameField(
            model_name='investmentoperation',
            old_name='fee_rub',
            new_name='fee_usd',
        ),
        migrations.RemoveField(
            model_name='investmentoperation',
            name='amount',
        ),
        migrations.RemoveField(
            model_name='investmentoperation',
            name='amount_currency',
        ),
        migrations.RemoveField(
            model_name='investmentoperation',
            name='fee_amount',
        ),
        migrations.RemoveField(
            model_name='investmentoperation',
            name='fee_currency',
        ),
        migrations.RemoveField(
            model_name='investmentoperation',
            name='fx_rate_to_rub',
        ),
        migrations.RemoveField(
            model_name='investmentoperation',
            name='price_currency',
        ),
        migrations.AlterField(
            model_name='fxratesnapshot',
            name='quote_currency',
            field=models.CharField(choices=CURRENCY_CHOICES, default='USD', max_length=10),
        ),
        migrations.AlterField(
            model_name='instrumentpricesnapshot',
            name='price_currency',
            field=models.CharField(choices=CURRENCY_CHOICES, default='USD', max_length=10),
        ),
        migrations.AlterField(
            model_name='investmentaccount',
            name='currency',
            field=models.CharField(choices=CURRENCY_CHOICES, default='USD', max_length=10),
        ),
        migrations.AlterField(
            model_name='investmentportfolio',
            name='base_currency',
            field=models.CharField(choices=CURRENCY_CHOICES, default='USD', max_length=10),
        ),
        migrations.AlterField(
            model_name='instrumentpricesnapshot',
            name='fx_rate_to_usd',
            field=models.DecimalField(decimal_places=8, default=Decimal('1'), max_digits=18),
        ),
        migrations.RunPython(normalize_existing_currencies, migrations.RunPython.noop),
    ]
