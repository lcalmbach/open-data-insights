from django.db import models
from account.models import CustomUser
from datetime import date, timedelta
from django.core.exceptions import ValidationError
import json
from django.conf import settings
from django.urls import reverse

def default_yesterday():
    return date.today() - timedelta(days=1)


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
        return super().get_queryset().filter(category_id=2)


class Period(LookupValue):
    objects = PeriodManager()

    class Meta:
        proxy = True
        verbose_name = "Period"
        verbose_name_plural = "Periods"


class ThemeManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(category_id=1)


class Theme(LookupValue):
    objects = ThemeManager()

    class Meta:
        proxy = True
        verbose_name = "Theme"
        verbose_name_plural = "Themes"


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
        verbose_name = "Context Period"
        verbose_name_plural = "Context Periods"


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
    import_month = models.IntegerField(
        blank=True,
        null=True,
        help_text="Month of the year when the dataset should be imported. If left empty, the dataset will be imported every month.",
    )
    import_day = models.IntegerField(
        blank=True,
        null=True,
        help_text="Day of the month when the dataset should be imported. If left empty, the dataset will be imported every day.",
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
        help_text="Field in the database that contordering = ['title']  # or any other fieldains the timestamp.",
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
    post_import_sql_commands = models.TextField(
        blank=True,
        null=True,
        help_text="SQL commands to be executed after the import process."
    )

    class Meta:
        verbose_name = "Dataset"
        verbose_name_plural = "Datasets"
        ordering = ["name"]  # or any other field

    def __str__(self):
        return self.name


class StoryTemplate(models.Model):
    active = models.BooleanField(
        default=True,
        help_text="Indicates if the story template is active. Only active templates will be used for generating stories.",
    )
    has_data_sql = models.TextField(
        blank=True,
        null=True,
        help_text="SQL command to check if there is data for a given date.",
    )
    publish_conditions = models.TextField(
        help_text="SQL command to check if the story should be published. If this command returns no results, the story will not be published.",
        blank=True,
        null=True,
    )
    most_recent_day_sql = models.TextField(
        blank=True,
        null=True,
        help_text="SQL command to get the most recent day for which data is available. This is used to determine the reference period for the story.",
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
    data_source = models.JSONField(
        default=dict,
        help_text="Data source for the story template, e.g., [{'text': 'data.bs', 'url': 'https://data.bs.ch/explore/dataset/100051']",
    )
    other_ressources = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="Additional ressource, e.g., [{'text': 'meteoblue', 'url': 'https://meteoblue.ch/station_346353']",
    )
    prompt_text = models.TextField(help_text="The prompt used to generate the story.")
    temperature = models.FloatField(
        default=0.3,
        help_text="Temperature parameter for the AI model. Controls the randomness of the output.",
    )
    post_publish_command = models.TextField(
        blank=True,
        null=True,
        help_text="SQL command to be executed after the story is published. This can be used to update other tables or perform additional actions.",
    )

    class Meta:
        verbose_name = "Story Template"
        verbose_name_plural = "Story Templates"
        ordering = ["title"]  # or any other field

    def __str__(self):
        return self.title


class StoryTemplateGraphic(models.Model):
    story_template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="graphics",
        help_text="The story template this graphic belongs to.",
    )
    title = models.CharField(max_length=255, help_text="Title of the graphic.")
    settings = models.JSONField(
        default=dict,
        help_text="Settings for the graphic, e.g., {'type': 'bar', 'x': 'date', 'y': 'value'}. This can include any settings required by the graphic library used.",
    )
    sql_command = models.TextField(
        max_length=4000,
        help_text="SQL command to get the data for the graphic, e.g., 'SELECT date, value FROM weather_data WHERE date >= %s AND date <= %s'. This command should return the data in a format suitable for the graphic library used.",
    )
    graphic_type = models.CharField(
        max_length=50,
        choices=[
            ("bar", "Bar Chart"),
            ("line", "Line Chart"),
            ("scatter", "Scatter Plot"),
        ],
    )
    sort_order = models.IntegerField(
        default=0, help_text="Sort order of the graphic within the story template."
    )

    class Meta:
        verbose_name = "Graphic Template"
        verbose_name_plural = "Graphics Templates"
        ordering = ["sort_order"]  # or any other field

    def __str__(self):
        return self.title


class StoryTemplateTable(models.Model):
    story_template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="tables",  # Changed from "graphics" to "tables"
        help_text="The story template this table belongs to.",
    )
    title = models.CharField(max_length=255, help_text="Title of the table.")

    sql_command = models.TextField(
        max_length=4000,
        help_text="SQL command to get the data for the graphic, e.g., 'SELECT date, value FROM weather_data WHERE date >= %s AND date <= %s'. This command should return the data in a format suitable for the graphic library used.",
    )
    sort_order = models.IntegerField(
        default=0, help_text="Sort order of the graphic within the story template."
    )

    class Meta:
        verbose_name = "Table Template"
        verbose_name_plural = "Table Templates"
        ordering = ["sort_order"]  # or any other field

    def __str__(self):
        return self.title


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
    sort_order = models.IntegerField(
        default=0,
        help_text="Sort order of the context within the story template.",
    )
    context_period = models.ForeignKey(
        ContextPeriod,
        on_delete=models.CASCADE,
        related_name="context_periods",
        help_text="The context period for this context, e.g., 'day', 'month', 'season', 'year'.",
    )

    class Meta:
        verbose_name = "Story Template Context"
        verbose_name_plural = "Story Template Contexts"
        ordering = ["sort_order"]  # or any other field



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
    sort_order = models.IntegerField(
        default=0,
        help_text="Sort order of the period of interest value within the story template.",
    )

    class Meta:
        verbose_name = "Story Template Period of Interest Values"
        verbose_name_plural = "Story Template Period of Interest Values"
        ordering = ["sort_order"]  # or any other field


class Story(models.Model):
    template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="stories",
        help_text="The template used to generate the story.",
    )
    title = models.CharField(max_length=255, help_text="Title of the story.",
                             blank=True, null=True)
    summary = models.TextField(
        blank=True,
        null=True,
        help_text="Summary of the story template. This is used to provide a brief overview of the story.",
    )
    published_date = models.DateField(
        auto_now_add=True, help_text="Date when the story was published.",
        blank=True, null=True
    )
    prompt_text = models.TextField(
        help_text="The prompt used to generate the story.", blank=True, null=True
    )
    context_values = models.JSONField(
        help_text="The JSON data used for the data story generation.",
        blank=True,
        null=True,
    )
    ai_model = models.CharField(
        max_length=50, help_text="AI model used for generating the story.", blank=True, null=True   
    )
    reference_period_start = models.DateField(
        default=default_yesterday,
        help_text="Start date of the reference period for the story.",
        blank=True,
        null=True,
    )
    reference_period_end = models.DateField(
        default=default_yesterday,
        help_text="End date of the reference period for the story.",
        blank=True,
        null=True,
    )
    reference_values = models.JSONField(
        help_text="Reference values for the story, e.g., {'max_temperature_degc': 30, 'precipitation_mm': 14}",
        blank=True,
        null=True,
    )
    content = models.TextField(help_text="Content of the story.", blank=True, null=True)

    @property
    def reference_period(self):
        if self.reference_period_start == self.reference_period_end:
            return self.reference_period_start.strftime("%Y-%m-%d")
        else:
            return f"{ self.reference_period_start.strftime('%Y-%m-%d') } – { self.reference_period_end.strftime('%Y-%m-%d') }"

    def reference_month(self):
        return self.reference_period_start.strftime("%B %Y")

    def reference_year(self):
        return self.reference_period_start.strftime("%Y")

    def __str__(self):
        return f"Report {self.title} - {self.published_date}"

    def clean(self):
        """Validate all model fields to prevent silent failures"""
        super().clean()
        
        # Check required fields
        if not self.title:
            raise ValidationError({'title': 'Title is required'})
        
        if self.template is None:
            raise ValidationError({'template': 'Story template is required'})
        
        if not self.content:
            raise ValidationError({'content': 'Content is required'})
        
        # Validate date fields
        if self.reference_period_start and self.reference_period_end:
            if self.reference_period_start > self.reference_period_end:
                raise ValidationError({'reference_period_start': 'Reference period start date cannot be after end date'})
        
        # Validate JSON fields
        # Validate reference_values field
        if self.reference_values:
            try:
                if isinstance(self.reference_values, str):
                    json_obj = json.loads(self.reference_values)
                    # Additional structure validation if needed
                    if not isinstance(json_obj, dict):
                        raise ValidationError({'reference_values': 'Must be a valid JSON object'})
                    
                    # Check for required structure in reference_values
                    if 'period_of_interest' not in json_obj:
                        raise ValidationError({'reference_values': 'Missing "period_of_interest" in reference values'})
                    
                    if 'measured_values' not in json_obj:
                        raise ValidationError({'reference_values': 'Missing "measured_values" in reference values'})
                    
            except json.JSONDecodeError:
                raise ValidationError({'reference_values': 'Invalid JSON format'})
        
        # Validate context_values field
        if self.context_values:
            try:
                if isinstance(self.context_values, str):
                    json_obj = json.loads(self.context_values)
                    # Validate structure - check if it has expected keys
                    if not isinstance(json_obj, dict):
                        raise ValidationError({'context_values': 'Must be a valid JSON object'})
                    
                    if 'context_data' not in json_obj:
                        raise ValidationError({'context_values': 'Missing "context_data" key in context values'})
                    
                    # Verify context_data is a dictionary
                    if not isinstance(json_obj['context_data'], dict):
                        raise ValidationError({'context_values': '"context_data" must be a JSON object'})
                    
            except json.JSONDecodeError:
                raise ValidationError({'context_values': 'Invalid JSON format'})
        
        # Validate AI model field
        valid_ai_models = ['gpt-4o', 'gpt-4', 'gpt-3.5-turbo']  # Update with your valid models
        if self.ai_model and self.ai_model not in valid_ai_models:
            raise ValidationError({'ai_model': f'Invalid AI model. Choose from: {", ".join(valid_ai_models)}'})

    def get_absolute_url(self):
        return settings.APP_ROOT.rstrip('/') + reverse('story_detail', args=[self.id])

    def get_email_list_entry(self):
        return f"<b>{self.title}:</b></br><p>{self.summary}<p>"

class StoryLog(models.Model):
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name="story_logs",
        help_text="The story this log belongs to.",
    )
    publish_date = models.DateField(
        help_text="Date for which the log is created. Defaults to yesterday.",
    )
    reference_period_start = models.DateField(
        default=default_yesterday,
        help_text="Start date of the reference period for the log.",
    )
    reference_period_end = models.DateField(
        default=default_yesterday,
        help_text="End date of the reference period for the log.",
    )

    class Meta:
        verbose_name = "Story Log"
        verbose_name_plural = "Story Logs"

    def __str__(self):
        return f"Report {self.story.title} - {self.reference_period_start}"


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

    class Meta:
        verbose_name = "Story Template Subscription"
        verbose_name_plural = "Story Template Subscriptions"
        ordering = ["-create_date"]

    def __str__(self):
        return f"{self.story_template.title} > {self.user.last_name}"


class Graphic(models.Model):
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name="story_graphics",
        help_text="The story this graph belongs to.",
    )
    graphic_template = models.ForeignKey(
        StoryTemplateGraphic,
        on_delete=models.CASCADE,
        related_name="story_template_graphics",
        help_text="The story template this graphic belongs to.",
    )
    title = models.CharField(max_length=255, help_text="Title of the graphic.")
    content_html = models.TextField(
        blank=True,
        null=True,
        help_text="HTML content of the graphic. This is used to render the graphic in the story view.",
    )
    data = models.JSONField(
        default=dict,
        help_text="Data for the graphic, e.g., {'date': ['2023-01-01', '2023-01-02'], 'value': [10, 20]}. This should match the settings defined in the graphic.",
    )
    sort_order = models.IntegerField(
        default=0, help_text="Sort order of the graphic within the story."
    )

    class Meta:
        verbose_name = "Graphic"
        verbose_name_plural = "Graphics"
        ordering = ["sort_order"]  # or any other field

    def __str__(self):
        return str(self.title)
    

class StoryTable(models.Model):
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name="storytables",
        help_text="The story this table belongs to.",
    )
    table_template = models.ForeignKey(
        StoryTemplateTable,
        on_delete=models.CASCADE,
        related_name="storytables",
        help_text="The story template this table belongs to.",
    )
    title = models.CharField(max_length=255, help_text="Title of the table.")
    data = models.JSONField(
        default=dict,
        help_text="Data for the table, e.g., {'date': ['2023-01-01', '2023-01-02'], 'value': [10, 20]}. This should match the settings defined in the table.",
    )
    sort_order = models.IntegerField(
        default=0, help_text="Sort order of the table within the story."
    )

    class Meta:
        verbose_name = "Table"
        verbose_name_plural = "Tables"
        ordering = ["sort_order"]  # or any other field

    def __str__(self):
        return str(self.table_template.title)
