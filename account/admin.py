from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Organisation


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ["email", "first_name", "last_name", "is_staff", "is_confirmed", "is_active", "auto_subscribe"]
    list_filter = ["is_staff", "is_superuser", "is_active", "is_confirmed"]
    search_fields = ["email"]
    ordering = ["email"]
    readonly_fields = ("date_joined", "last_login")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal info",
            {"fields": ("first_name", "last_name", "country", "organisation", "auto_subscribe")},
        ),
        ("Permissions", {
            "fields": ("is_active", "is_staff", "is_superuser", "is_confirmed", "groups", "user_permissions")
        }),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "email",
                "password1",
                "password2",
                "first_name",
                "last_name",
                "auto_subscribe",
                "is_active",
                "is_staff",
                "is_confirmed",
            ),
        }),
    )
