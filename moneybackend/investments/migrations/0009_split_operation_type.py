from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('investments', '0008_dividend_operation_type'),
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
                    ('split', 'Split'),
                ],
                max_length=30,
            ),
        ),
    ]
