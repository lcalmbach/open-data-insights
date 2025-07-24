from django.contrib import admin
from .models import (
    Story,
    StoryTemplate,
    StoryTemplateContext,
    StoryTemplatePeriodOfInterestValues,
    LookupCategory,
    LookupValue,
    Dataset,
    StoryTemplateSubscription,
    StoryLog,
    StoryTable,
    Graphic,
    StoryRating,
    StoryTemplateTable,
    StoryTemplateGraphic,
)


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "template",
        "published_date",
    )
    sorted_by = (
        "template",
        "published_date",
    )
    list_filter = ("template",)
    search_fields = (
        "id",
        "title",
    )


@admin.register(StoryTemplate)
class StoryTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "reference_period",
    )
    search_fields = ("title", "reference_period__value")
    list_filter = ["title", "reference_period"]  # shows a filter sidebar


@admin.register(StoryTemplateContext)
class StoryTemplateContextAdmin(admin.ModelAdmin):
    list_display = ("story_template", "key", "sort_order")
    sortable_by = (
        "story_template",
        "sort_order",
    )
    sorted_by = ("sort_order",)
    list_filter = ("story_template",)


@admin.register(StoryTemplatePeriodOfInterestValues)
class StoryTemplatePeriodOfInterestValuesAdmin(admin.ModelAdmin):
    list_display = ("story_template", "title", "sort_order")
    sortable_by = (
        "story_template",
        "sort_order",
    )
    sorted_by = (
        "story_template",
        "sort_order",
    )
    list_filter = ("story_template",)


@admin.register(LookupCategory)
class LookupCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "description")
    sortable_by = ("name",)
    ordering = ("name",)
    search_fields = ["name"]  # shows a filter sidebar


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
    sortable_by = ("name", "source_identifier")
    sorted_by = ("name",)
    search_fields = ["name", "source_identifier"]  # shows a filter sidebar


@admin.register(StoryTemplateSubscription)
class StoryTemplateSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("story_template", "user", "create_date")
    sortable_by = ("user", "story_template")
    sorted_by = ("user",)
    search_fields = ["user"]  # shows a filter sidebar
    list_filter = ("user", "story_template")


@admin.register(StoryLog)
class StoryLogAdmin(admin.ModelAdmin):
    list_display = (
        "story",
        "publish_date",
        "reference_period_start",
        "reference_period_end",
    )
    sortable_by = ("story", "publish_date")
    search_fields = ("story__title",)



@admin.register(StoryTemplateTable)
class StoryTemplateTableAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "story_template",
    )
    sortable_by = ("id", "title")
    search_fields = ("title",)


@admin.register(StoryTable)
class StoryTableAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "story",
        "table_template",
    )
    sortable_by = ("id", "story")
    search_fields = ("story__title", "table_template__title")
    list_filter = ("story",)


@admin.register(StoryTemplateGraphic)
class StoryTemplateGraphicAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "story_template",
    )
    sortable_by = ("id", "title")
    search_fields = ("title",)
    list_filter = ("story_template",)


@admin.register(Graphic)
class StoryGraphiAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "story",
        "title",
        "story_id"
    )

    sortable_by = ("id", "title")
    search_fields = ("title",)
    list_filter = ("story",)