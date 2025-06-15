from django.contrib import admin
from .models import (
    Story,
    StoryTemplate,
    StoryTemplateContext,
    StoryTemplatePeriodOfInterestValues,
    LookupCategory,
    LookupValue,
    Dataset
)


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "published_date",
        "reference_period_start",
        "reference_period_end",
    )
    list_filter = ("published_date",)
    search_fields = ("title",)


@admin.register(StoryTemplate)
class StoryTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
    )
    search_fields = ("title",)


@admin.register(StoryTemplateContext)
class StoryTemplateContextAdmin(admin.ModelAdmin):
    list_display = ("story_template", "key", "sort_key")
    sortable_by = (
        "story_template",
        "sort_key",
    )
    sorted_by = ("sort_key",)
    list_filter = ("story_template",)


@admin.register(StoryTemplatePeriodOfInterestValues)
class StoryTemplatePeriodOfInterestValuesAdmin(admin.ModelAdmin):
    list_display = ("story_template", "title", "sort_key")
    sortable_by = (
        "story_template",
        "sort_key",
    )
    sorted_by = (
        "story_template",
        "sort_key",
    )


@admin.register(LookupCategory)
class LookupCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    sortable_by = ("name",)
    sorted_by = ("name",)


@admin.register(LookupValue)
class LookupValueAdmin(admin.ModelAdmin):
    list_display = ("id", "category", "value", "description", "sort_order")
    sortable_by = (
        "id",
        "sort_order",
    )
    sorted_by = (
        "category",
        "sort_order",
    )
    list_filter = ("category",)


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "source_identifier")
    sortable_by = (
        "name",
    )
    sorted_by = (
        "name",
    )
