import uuid
from django.db import models
from datetime import date, timedelta
from .managers import NaturalKeyManager

def default_yesterday():
    return date.today() - timedelta(days=1)


class NaturalKeyManager(models.Manager):
    lookup_fields = ()
    def get_by_natural_key(self, *args):
        return self.get(**dict(zip(self.lookup_fields, args)))


class DatasetManager(NaturalKeyManager):
    lookup_fields = ('slug',)


class Dataset(models.Model):
    slug = models.SlugField(unique=True, blank=True, null=True, editable=False)
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
        help_text="SQL commands to be executed after each import process.",
    )

    post_create_sql_commands = models.TextField(
        blank=True,
        null=True,
        help_text="SQL commands to be executed after the initial table has been created.",
    )

    class Meta:
        verbose_name = "Dataset"
        verbose_name_plural = "Datasets"
        ordering = ["name"] 

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = uuid.uuid4().hex[:8]  # or shortuuid.uuid()[:10]
        super().save(*args, **kwargs)

    def natural_key(self):
        return (self.slug,)

    natural_key.dependencies = []  # optional; can be omitted
    objects = DatasetManager()