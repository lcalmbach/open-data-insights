from django.contrib import admin
from .models.story import Story
from .models.story_template import StoryTemplateDataset, StoryTemplate, StoryTemplateFocus
from .models.story_context import StoryTemplateContext
from .models.lookups import LookupCategory, LookupValue
from .models.dataset import Dataset
from .models.subscription import StoryTemplateSubscription
from .models.story_log import StoryLog
from .models.story_table import StoryTable
from .models.graphic import Graphic, StoryTemplateGraphic
from .models.story_table_template import StoryTemplateTable
from .models.user_comment import UserComment


class StoryTemplateFocusInline(admin.TabularInline):
    model = StoryTemplateFocus
    extra = 0


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "template",
        "published_date",
        "reference_period_start",
        "reference_period_end",
    )
    sorted_by = (
        "template",
        "published_date",
    )
    list_filter = ("templatefocus__story_template",)
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
        "organisation",
    )
    inlines = (StoryTemplateFocusInline,)
    search_fields = ("title", "reference_period__value")
    list_filter = ["reference_period", "organisation"]  # shows a filter sidebar


@admin.register(StoryTemplateFocus)
class StoryTemplateFocusAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "story_template",
        "filter_value",
    )
    list_select_related = ("story_template",)
    search_fields = ("story_template__title", "focus_value")
    list_filter = ("story_template",)


@admin.register(StoryTemplateContext)
class StoryTemplateContextAdmin(admin.ModelAdmin):
    list_display = ("id", "key", "story_template", "sort_order")
    sortable_by = (
        "id",
        "story_template",
        "sort_order",
    )
    search_fields = ["key"]  # shows a filter sidebar
    sorted_by = ("sort_order",)
    list_filter = ("story_template__reference_period", "story_template")


@admin.register(LookupCategory)
class LookupCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "description")
    sortable_by = ("name",)
    ordering = ("name",)
    search_fields = ["name"]  # shows a filter sidebar
    sortable_by = "id"


@admin.register(LookupValue)
class LookupValueAdmin(admin.ModelAdmin):
    list_display = ("id", "value", "key", "category", "sort_order")
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
    list_display = ("id", "name", "import_type", "source", "last_import_date","source_identifier")
    sortable_by = ("name", "source_identifier", "id")
    sorted_by = ("name",)
    search_fields = ["name", "source_identifier"]  # shows a filter sidebar
    list_filter = ("import_type", "source")


@admin.register(StoryTemplateSubscription)
class StoryTemplateSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("story_template", "user", "create_date")
    sortable_by = ("user", "story_template")
    sorted_by = ("user",)
    search_fields = ["user"]  # shows a filter sidebar
    list_filter = ("user", "story_template")


@admin.register(StoryTemplateDataset)
class StoryTemplateDatasetAdmin(admin.ModelAdmin):
    list_display = ("story_template_id", "story_template", "dataset", "dataset_source_url")
    list_filter = ("story_template", "dataset")
    ordering = ("story_template__title",)
    list_select_related = ("story_template", "dataset")

    def story_template_id(self, obj):
        return obj.story_template_id

    story_template_id.admin_order_field = "story_template__id"
    story_template_id.short_description = "Story Template ID"

    def dataset_source_url(self, obj):
        return getattr(obj.dataset, "source_url", None)

    dataset_source_url.admin_order_field = "dataset__source_url"
    dataset_source_url.short_description = "Dataset Source URL"


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
    list_display = ("id", "title", "story_template", "sort_order")
    sortable_by = ("id", "title", "story_template", "sort_order")
    search_fields = ("title",)
    list_filter = ("story_template",)


@admin.register(StoryTable)
class StoryTableAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "story_published_date",
        "story_template",
        "table_template",
    )
    list_select_related = ("story__templatefocus__story_template",)
    search_fields = ("table_template__title", "table_template__id", "story__title")

    def story_published_date(self, obj):
        return getattr(getattr(obj, "story", None), "published_date", None)

    story_published_date.short_description = "Story published"
    story_published_date.admin_order_field = "story__published_date"

    def story_template(self, obj):
        tpl = getattr(getattr(obj, "story", None), "template", None)
        return getattr(tpl, "title", None) if tpl is not None else None

    story_template.short_description = "Story template"
    story_template.admin_order_field = "story__templatefocus__story_template__title"


@admin.register(StoryTemplateGraphic)
class StoryTemplateGraphicAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "story_template",
        "graphic_type",
        "sort_order",
    )
    sortable_by = ("id", "title","sort_order")
    search_fields = ("title",)
    list_filter = ("graphic_type", "story_template")


@admin.register(Graphic)
class StoryGraphicAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "story",
        "title",
    )

    sortable_by = ("id", "title")
    search_fields = ("title",)
    list_filter = ("story__templatefocus__story_template",)


@admin.register(UserComment)
class UserCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "sentiment", "date")
    list_filter = ("sentiment", "date")
    search_fields = ("comment", "user__email", "user__first_name", "user__last_name")
