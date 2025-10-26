from django.db import models

THEME_CATEGORY_ID = 1
PERIOD_CATEGORY_ID = 2
AGGREGATION_FUNCTION_CATEGORY_ID = 3
CONTEXT_PERIOD_CATEGORY_ID = 4



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


class GraphTypeManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=6)


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
        return super().get_queryset().filter(category_id=AGGREGATION_FUNCTION_CATEGORY_ID)


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