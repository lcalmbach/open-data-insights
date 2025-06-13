from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ["last_name", "first_name", "email", "is_confirmed"]
    list_filter = ["last_name", "is_confirmed"]
    search_fields = ["email"]
    ordering = ["email"]
    fieldsets = UserAdmin.fieldsets + (
        (
            None,
            {"fields": ("additional_field1", "additional_field2")},
        ),  # falls du eigene Felder hast
    )
