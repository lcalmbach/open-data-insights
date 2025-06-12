from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ["email", "is_staff", "is_active"]
    list_filter = ["is_staff", "is_active", "groups"]
    search_fields = ["email"]
    ordering = ["email"]
    fieldsets = UserAdmin.fieldsets + (
        (
            None,
            {"fields": ("additional_field1", "additional_field2")},
        ),  # falls du eigene Felder hast
    )
