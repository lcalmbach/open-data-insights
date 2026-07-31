from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Organisation
from reports.models.press_review import UserPressReviewKeyword


class UserPressReviewKeywordInline(admin.TabularInline):
    model = UserPressReviewKeyword
    extra = 1
    fields = ["keyword"]
    verbose_name = "Press Review Keyword"
    verbose_name_plural = "Press Review Keywords"


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ["email", "first_name", "last_name", "is_staff", "is_confirmed", "is_active", "auto_subscribe", "press_review_frequency"]
    list_filter = ["is_staff", "is_superuser", "is_active", "is_confirmed", "press_review_frequency"]
    search_fields = ["email"]
    ordering = ["email"]
    readonly_fields = ("date_joined", "last_login")
    inlines = [UserPressReviewKeywordInline]
    filter_horizontal = ("press_review_sources",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal info",
            {"fields": ("first_name", "last_name", "country", "organisation", "auto_subscribe")},
        ),
        (
            "Press Review",
            {
                "fields": ("press_review_frequency", "press_review_threshold", "press_review_sources"),
                "description": "Leave sources empty to include all active sources in this user's digest.",
            },
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
