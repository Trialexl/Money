from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='tax_id',
            field=models.CharField(blank=True, max_length=12, null=True, verbose_name='ИНН'),
        ),
    ]
