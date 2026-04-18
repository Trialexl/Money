import uuid
from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import AbstractUser


# Create your models here.
class CustomUser(AbstractUser):
    COMPANY = 'COMP'
    PRIVATE_PERSON = 'PRIV'
    COMPANY_PRIVATE = [
        (COMPANY, 'Компания'),
        (PRIVATE_PERSON, 'Частное лицо')

    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(verbose_name='Наименование полное', max_length=250,
                                 unique=True, null=True, blank=True)
    status = models.CharField(verbose_name='Юр/Физ.лицо', max_length=50,
                              choices=COMPANY_PRIVATE, default=COMPANY)
    tax_id = models.CharField(verbose_name='ИНН', max_length=12, null=True, blank=True)

    def clean(self):
        errors = {}
        if self.tax_id:
            if not self.tax_id.isdigit():
                errors['tax_id'] = 'ИНН должен состоять только из цифр.'
            elif len(self.tax_id) not in (10, 12):
                errors['tax_id'] = 'ИНН должен содержать 10 или 12 цифр.'
        if errors:
            raise ValidationError(errors)
