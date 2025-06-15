from django.db import models
from account.models import CustomUser
from datetime import date, timedelta


def default_yesterday():
    return date.today() - timedelta(days=1)


class LookupCategory(models.Model):
    id = models.IntegerField(primary_key=True)
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
    id = models.IntegerField(primary_key=True)
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

    def __str__(self):
        return f"{self.category.name}: {self.value}"


class ThemeManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=1)


class Theme(LookupValue):
    objects = ThemeManager()

    class Meta:
        proxy = True
        verbose_name = "Theme"
        verbose_name_plural = "Themes"


class PeriodManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=2)


class Period(LookupValue):
    objects = PeriodManager()

    class Meta:
        proxy = True
        verbose_name = "Period"
        verbose_name_plural = "Periods"


class AggregationFunctionManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=3)


class AggregationFunction(LookupValue):
    objects = AggregationFunctionManager()

    class Meta:
        proxy = True
        verbose_name = "AggregationFunction"
        verbose_name_plural = "AggregationFunctions"


class ContextPeriodManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=4)


class ContextPeriod(LookupValue):
    objects = ContextPeriodManager()

    class Meta:
        proxy = True
        verbose_name = "ContextPeriod"
        verbose_name_plural = "ContextPeriods"


class Dataset(models.Model):
    name = models.CharField(max_length=255, help_text="Name of the dataset.")
    description = models.TextField(blank=True, help_text="Description of the dataset.")
    source = models.CharField(
        max_length=255, help_text="Source of the dataset, e.g., 'ods', 'worldbank"
    )
    fields_selection = models.JSONField(
        blank=True,
        null=True,
        default=list,
        help_text="List of fields in the dataset to be imported. Empty list if all fields will be imported.",
    )
    import_filter = models.TextField(
        blank=True,
        null=True,
        help_text="Filter to be applied during import, e.g., 'temperature > 0'. If empty, no filter is applied.",
    )
    aggregations = models.JSONField(
        default=list,
        blank=True,
        null=True,
        help_text="List of aggregations to be applied to the if data frequency is > daily. Format: {'group_by_field: 'timestamp', 'target_field_name': 'date', 'parameters': [precipitation: ['sum'], 'temperature': ['min', 'max', 'mean']]}",
    )
    active = models.BooleanField(
        default=True,
        help_text="Indicates if the dataset is active. Only active datasets will be imported and synchronized.",
    )
    constants = models.JSONField(
        default=list,
        blank=True,
        null=True,
        help_text="List of constants to be added to the dataset. format: [{'field_name': 'station', 'type': 'int', 'value': 1}]. These constants will be added to each record during import.",
    )
    source_identifier = models.CharField(
        max_length=255, help_text="Unique identifier for the source dataset."
    )
    base_url = models.CharField(max_length=255, help_text="base url for ODS-datasets.")
    source_timestamp_field = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Field in the source dataset that contains the timestamp.",
    )
    db_timestamp_field = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Field in the database that contains the timestamp.",
    )
    record_identifier_field = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Field in the source dataset that uniquely identifies a record and increases with each import. if left empty, the entire daset will be imported each time, which is ok for smaller datasets where each record might change.",
    )
    target_table_name = models.CharField(
        max_length=255, help_text="Name of the target table in the database."
    )
    add_time_aggregation_fields = models.BooleanField(
        default=False,
        help_text="Indicates if time aggregation fields (year, month, dayinyear, season) should be added.",
    )
    delete_records_with_missing_values = models.JSONField(
        default=list,
        null=True,
        blank=True,
        help_text="List of fields for which records with missing values should be deleted.",
    )
    last_import_date = models.DateTimeField(
        null=True,
        blank=True,
        auto_now=True,
        help_text="Timestamp of the last import for this dataset.",
    )
    # format for calculated fields: [{'field_name': 'new_field', 'type': 'int', 'command': 'update script'}]
    calculated_fields = models.JSONField(
        default=list,
        null=True,
        blank=True,
        help_text="List of fields to be calculated by the commnds defined in post_import_commands.",
    )

    class Meta:
        verbose_name = "Dataset"
        verbose_name_plural = "Datasets"

    def __str__(self):
        return self.name


class StoryTemplate(models.Model):
    active = models.BooleanField(
        default=True,
        help_text="Indicates if the story template is active. Only active templates will be used for generating stories.",
    )
    title = models.CharField(max_length=255, help_text="Title of the story template.")
    description = models.TextField(
        blank=True, help_text="Description of the story template."
    )
    reference_period = models.ForeignKey(
        Period,
        on_delete=models.CASCADE,
        related_name="story_templates",
        help_text="Reference period for the story template: day, month, season, year, etc.",
    )
    prompt_text = models.TextField(help_text="The prompt used to generate the story.")
    temperature = models.FloatField(
        default=0.3,
        help_text="Temperature parameter for the AI model. Controls the randomness of the output.",
    )

    class Meta:
        verbose_name = "Story Template"
        verbose_name_plural = "Story Templates"

    def __str__(self):
        return self.title


class StoryTemplateParameter(models.Model):
    story_template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="parameters",
        help_text="parameters used in the story template, e.g., 'max_temperature_degc', 'precipitation_mm', etc.",
    )
    name = models.CharField(
        max_length=255,
        help_text="Name of the parameter, e.g., 'max_temperature_degc', 'precipitation_mm', etc.",
    )
    db_field_name = models.CharField(
        max_length=255,
        help_text="Database field name for the parameter, e.g., 'max_temperature', 'precipitation', etc.",
    )
    unit = models.CharField(
        max_length=50, help_text="Unit of the parameter, e.g., '°C', 'mm', etc."
    )
    description = models.TextField(
        blank=True, help_text="Description of the parameter."
    )

    def __str__(self):
        return self.name


class StoryTemplateContext(models.Model):
    story_template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="contexts",
        help_text="The story this context belongs to.",
    )
    description = models.TextField(
        max_length=1000,
        help_text="Name of the context, e.g., 'Context monthly average with all previous years of same month'",
    )
    key = models.CharField(
        max_length=255,
        help_text="Key for the context, e.g., 'monthly_average_all_previous_years'. This key is used to identify the context in the story template.",
    )
    sql_command = models.TextField(
        max_length=4000,
        help_text="SQL command to get the value for the context, e.g., 'SELECT AVG(temperature) FROM weather_data WHERE date >= %s AND date <= %s'.",
    )
    sort_key = models.IntegerField(
        default=0,
        help_text="Sort order of the context within the story template.",
    )
    context_period = models.ForeignKey(
        ContextPeriod,
        on_delete=models.CASCADE,
        related_name="context_periods",
        help_text="The context period for this context, e.g., 'day', 'month', 'season', 'year'.",
    )
    create_condition = models.TextField(
        null=True,
        blank=True,
        help_text="command holding the condition on whether this context is created. e.g. if reference day is a heat day, check on how many heat days there were in the current month or season.",
    )
    follow_up_command = models.TextField(
        null=True,
        blank=True,
        help_text="command holding the condition on whether follow up contexts are executed. e.g. if reference day is a heat day, check on how many heat days there were in the current month or season.",
    )
    predecessor = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contexts",
        help_text="master context for this context, in case follow_up_condition is met.",
    )


class StoryTemplatePeriodOfInterestValues(models.Model):
    story_template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="period_of_interest_values",
        help_text="The story template this period of interest values belong to.",
    )
    title = models.CharField(
        max_length=255,
        help_text="Title of the period of interest value, e.g., 'Monthly Average Temperature'.",
    )
    sql_command = models.TextField(
        max_length=4000,
        help_text="Sql command to get the value for the period of interest, e.g., 'SELECT AVG(temperature) FROM weather_data WHERE date >= %s AND date <= %s'.",
    )
    sort_key = models.IntegerField(
        default=0,
        help_text="Sort order of the period of interest value within the story template.",
    )


class Story(models.Model):
    template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="stories",
        help_text="The template used to generate the story.",
    )
    title = models.CharField(max_length=255, help_text="Title of the story.")
    published_date = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the story was published."
    )
    prompt_text = models.TextField(
        help_text="The prompt used to generate the story.", blank=True, null=True
    )
    json_payload = models.JSONField(
        help_text="The JSON data used for the data story generation.",
        blank=True,
        null=True,
    )
    ai_model = models.CharField(
        max_length=50, help_text="AI model used for generating the story."
    )
    reference_period_start = models.DateField(
        default=default_yesterday,
        help_text="Start date of the reference period for the story.",
    )
    reference_period_end = models.DateField(
        default=default_yesterday,
        help_text="End date of the reference period for the story.",
    )
    reference_values = models.JSONField(
        help_text="Reference values for the story, e.g., {'max_temperature_degc': 30, 'precipitation_mm': 14}",
        blank=True,
        null=True,
    )
    content = models.TextField(help_text="Content of the story.", blank=True, null=True)

    def reference_month(self):
        return self.reference_period_start.strftime("%B %Y")

    def reference_year(self):
        return self.reference_period_start.strftime("%Y")

    def __str__(self):
        return f"Report {self.title} - {self.published_date}"


class StoryRating(models.Model):
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name="ratings",
        help_text="The story being rated.",
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="story_ratings",
        help_text="User who rated the story.",
    )
    rating = models.IntegerField(help_text="Rating given to the story.")
    create_date = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the rating was created."
    )
    rating_text = models.TextField(
        blank=True, help_text="Optional feedback for the story."
    )

    class Meta:
        verbose_name = "Story Rating"
        verbose_name_plural = "Story Ratings"

    def __str__(self):
        return f"Rating {self.rating} for {self.story.title}"


class StoryFeedback(models.Model):
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name="feedbacks",
        help_text="The story being rated.",
    )
    feedback_text = models.TextField(help_text="Feedback for the story.")
    create_date = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the feedback was created."
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="story_feedbacks",
        help_text="User who provided feedback.",
    )

    class Meta:
        verbose_name = "Story Feedback"
        verbose_name_plural = "Story Feedbacks"

    def __str__(self):
        return f"Feedback for {self.story.title} by {self.user_id}"


class StoryTemplateSubscription(models.Model):
    story_template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="ratings",
        help_text="The story template being rated.",
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="story_template_subscriptions",
        help_text="User who subscribed to the story template.",
    )
    create_date = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the subscription was created."
    )
    cancellation_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the subscription was ended by the user. Null if still active.",
    )
    cancel_reason_text = models.TextField(
        blank=True,
        null=True,
        help_text="Optional text explaining why the subscription was revoked.",
    )

    def __str__(self):
        return f"{self.story_template.title} > {self.user.last_name}"
