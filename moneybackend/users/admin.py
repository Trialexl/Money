from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import CustomUserCreationForm, CustomUserChangeForm
from .models import CustomUser

# Register your models here.
class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser
    list_display = ['username', 'full_name', 'status', 'tax_id']
    fieldsets = UserAdmin.fieldsets + (
        ('Реквизиты 1с', {'fields': ('full_name', 'status', 'tax_id')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Реквизиты 1с', {'fields': ('full_name', 'status', 'tax_id')}),
    )
    search_fields = ('full_name', 'username', 'tax_id')
    ordering = ('full_name', 'username',)
    list_filter = ('status',)


admin.site.register(CustomUser, CustomUserAdmin)
