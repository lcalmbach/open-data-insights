from django.db import models
from enum import Enum
from django.conf import settings

THEME_CATEGORY_ID = 1
PERIOD_CATEGORY_ID = 2
AGGREGATION_FUNCTION_CATEGORY_ID = 3
CONTEXT_PERIOD_CATEGORY_ID = 4
DAY_PERIOD_CATEGORY_ID = 5
GRAPH_TYPE_CATEGORY_ID = 6
PERIOD_DIRECTION_CATEGORY_ID = 7
IMPORT_TYPE_CATEGORY_ID = 8
TAG_CATEGORY_ID = 9
LANGUAGE_CATEGORY_ID = 10
REGION_CATEGORY_ID = 11
TOPIC_CATEGORY_ID = 12
AI_MODEL_CATEGORY_ID = 13

class LanguageEnum(Enum):
    ENGLISH=94
    GERMAN=95
    FRENCH=96


class PeriodDirectionEnum(Enum):
    Backward = 72
    Forward = 71
    CURRENT = 73


class LookupCategory(models.Model):
    name = models.CharField(max_length=255, help_text="Name of the lookup category.")
    description = models.TextField(
        blank=True, help_text="Description of the lookup category."
    )

    class Meta:
        verbose_name = "Lookup Category"
        verbose_name_plural = "Lookup Categories"

    def __str__(self):
        return self.name


class LookupValue(models.Model):
    category = models.ForeignKey(
        LookupCategory,
        on_delete=models.CASCADE,
        related_name="values",
        help_text="The category this value belongs to.",
    )
    value = models.CharField(max_length=255, help_text="The actual lookup value.")
    description = models.TextField(
        blank=True, help_text="Description of the lookup value."
    )
    key = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Optional key for the lookup value, e.g., 'temperature', 'precipitation'. This can be used for quick access or filtering.",
    )
    predecessor = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL
    )
    level = models.IntegerField(
        default=0,
        help_text="Level of the lookup value in the hierarchy. 0 for root, 1 for first level, etc.",
    )
    sort_order = models.IntegerField(
        default=0, help_text="Sort order of the lookup value within its category."
    )

    class Meta:
        verbose_name = "Lookup Value"
        verbose_name_plural = "Lookup Values"
        ordering = ["sort_order", "value"]  # or any other field

    def __str__(self):
        return self.value


class ScopedLookupManager(models.Manager):
    category_id = None

    def get_queryset(self):
        return super().get_queryset().filter(category_id=self.category_id)

    def create(self, **kwargs):
        kwargs.setdefault("category_id", self.category_id)
        return super().create(**kwargs)

    def get_or_create(self, defaults=None, **kwargs):
        kwargs.setdefault("category_id", self.category_id)
        defaults = dict(defaults or {})
        defaults.setdefault("category_id", self.category_id)
        return super().get_or_create(defaults=defaults, **kwargs)

    def update_or_create(self, defaults=None, **kwargs):
        kwargs.setdefault("category_id", self.category_id)
        defaults = dict(defaults or {})
        defaults.setdefault("category_id", self.category_id)
        return super().update_or_create(defaults=defaults, **kwargs)


class TagManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=TAG_CATEGORY_ID)


class Tag(LookupValue):
    objects = TagManager()

    class Meta:
        proxy = True
        verbose_name = "Tag"
        verbose_name_plural = "Tags"


class PeriodDirectionManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=PERIOD_DIRECTION_CATEGORY_ID)


class PeriodDirection(LookupValue):
    objects = PeriodDirectionManager()

    class Meta:
        proxy = True
        verbose_name = "PeriodDirection"
        verbose_name_plural = "PeriodDirections"


class ImportTypeManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=IMPORT_TYPE_CATEGORY_ID)


class ImportType(LookupValue):
    objects = ImportTypeManager()

    class Meta:
        proxy = True
        verbose_name = "ImportType"
        verbose_name_plural = "ImportTypes"


class GraphTypeManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=GRAPH_TYPE_CATEGORY_ID)


class GraphType(LookupValue):
    objects = GraphTypeManager()

    class Meta:
        proxy = True
        verbose_name = "GraphType"
        verbose_name_plural = "GraphTypes"


class PeriodManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=PERIOD_CATEGORY_ID)


class Period(LookupValue):
    objects = PeriodManager()

    class Meta:
        proxy = True
        verbose_name = "Period"
        verbose_name_plural = "Periods"


class ThemeManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=THEME_CATEGORY_ID)


class Theme(LookupValue):
    objects = ThemeManager()

    class Meta:
        proxy = True
        verbose_name = "Theme"
        verbose_name_plural = "Themes"


class AggregationFunctionManager(models.Manager):
    def get_queryset(self):
        return (
            super().get_queryset().filter(category_id=AGGREGATION_FUNCTION_CATEGORY_ID)
        )


class AggregationFunction(LookupValue):
    objects = AggregationFunctionManager()

    class Meta:
        proxy = True
        verbose_name = "AggregationFunction"
        verbose_name_plural = "AggregationFunctions"


class ContextPeriodManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=CONTEXT_PERIOD_CATEGORY_ID)


class ContextPeriod(LookupValue):
    objects = ContextPeriodManager()

    class Meta:
        proxy = True
        verbose_name = "Context Period"
        verbose_name_plural = "Context Periods"

class LanguageManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=LANGUAGE_CATEGORY_ID)


class Language(LookupValue):
    objects = LanguageManager()

    class Meta:
        proxy = True
        verbose_name = "Language"
        verbose_name_plural = "Languages"


class RegionManager(ScopedLookupManager):
    category_id = REGION_CATEGORY_ID


class Region(LookupValue):
    objects = RegionManager()

    class Meta:
        proxy = True
        verbose_name = "Region"
        verbose_name_plural = "Regions"


class TopicManager(ScopedLookupManager):
    category_id = TOPIC_CATEGORY_ID


class Topic(LookupValue):
    objects = TopicManager()

    class Meta:
        proxy = True
        verbose_name = "Topic"
        verbose_name_plural = "Topics"


class AiModelManager(ScopedLookupManager):
    category_id = AI_MODEL_CATEGORY_ID


class AiModel(LookupValue):
    objects = AiModelManager()

    class Meta:
        proxy = True
        verbose_name = "AI Model"
        verbose_name_plural = "AI Models"


class TagDataset(models.Model):
    tag = models.ForeignKey(
        Tag, on_delete=models.CASCADE, related_name="dataset_assignments"
    )
    dataset = models.ForeignKey(
        "Dataset", on_delete=models.CASCADE, related_name="tag_assignments"
    )

    class Meta:
        verbose_name = "Dataset Tag Assignment"
        verbose_name_plural = "Dataset Tag Assignments"
        unique_together = ("tag", "dataset")

    def __str__(self):
        return f"{self.tag.value} - {self.dataset.name}"


class TagStoryTemplate(models.Model):
    tag = models.ForeignKey(
        Tag, on_delete=models.CASCADE, related_name="story_template_assignments"
    )
    story_template = models.ForeignKey(
        "StoryTemplate", on_delete=models.CASCADE, related_name="tag_assignments"
    )

    class Meta:
        verbose_name = "Story Template Tag Assignment"
        verbose_name_plural = "Story Template Tag Assignments"
        unique_together = ("tag", "story_template")

    def __str__(self):
        return f"{self.tag.value} - {self.story_template.title}"


class TagUser(models.Model):
    tag = models.ForeignKey(
        Tag, on_delete=models.CASCADE, related_name="user_assignments"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tag_assignments"
    )

    class Meta:
        verbose_name = "User Tag Assignment"
        verbose_name_plural = "User Tag Assignments"
        unique_together = ("tag", "user")

    def __str__(self):
        return f"{self.tag.value} - {self.user.username}"
