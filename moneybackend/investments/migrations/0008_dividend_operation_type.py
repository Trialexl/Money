from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('investments', '0007_investmentportfoliosnapshot'),
    ]

    operations = [
        migrations.AlterField(
            model_name='investmentoperation',
            name='operation_type',
            field=models.CharField(
                choices=[
                    ('buy', 'Покупка'),
                    ('sell', 'Продажа'),
                    ('transfer_instrument', 'Перевод инструмента'),
                    ('correction', 'Корректировка'),
                    ('dividend', 'Дивиденд'),
                ],
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name='investmentoperation',
            name='quantity',
            field=models.DecimalField(
                decimal_places=10,
                default=Decimal('0'),
                max_digits=24,
            ),
        ),
    ]
