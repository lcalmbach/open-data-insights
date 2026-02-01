import uuid
from django.db import models
from datetime import date, timedelta
from .managers import NaturalKeyManager
from .lookups import Period, ImportType
from enum import Enum


class ImportTypeEnum(Enum):
    NEW_TIMESTAMP = 75
    NEW_YEAR = 76
    NEW_YEAR_MONTH = 77
    NEW_PK = 78
    FULL_RELOAD = 79
    SKIP = 82

class PeriodEnum(Enum):
    DAILY = 35
    WEEKLY = 70
    MONTHLY = 36
    YEARLY = 38

def default_yesterday():
    return date.today() - timedelta(days=1)


class NaturalKeyManager(models.Manager):
    lookup_fields = ()

    def get_by_natural_key(self, *args):
        return self.get(**dict(zip(self.lookup_fields, args)))


class DatasetManager(NaturalKeyManager):
    lookup_fields = ("slug",)


class Dataset(models.Model):
    slug = models.SlugField(
        unique=True,
        blank=True,
        null=True,
        editable=False,
        verbose_name="Dataset Slug",
    )
    name = models.CharField(
        max_length=255, help_text="Name of the dataset.", verbose_name="Dataset Name"
    )
    description = models.TextField(
        blank=True, help_text="Description of the dataset.", verbose_name="Description"
    )
    source = models.CharField(
        max_length=255,
        help_text="Source of the dataset, e.g., 'ods', 'worldbank",
        verbose_name="Dataset Source",
    )
    source_url = models.URLField(
        max_length=500,
        help_text="URL of the original data source",
        verbose_name="Dataset source URL",
        blank=True,
        null=True,
    )
    source_url_label = models.CharField(
        max_length=100,
        help_text="Label shown for the source link",
        verbose_name="Source link label",
        blank=True,
        null=True,
    )
    fields_selection = models.JSONField(
        blank=True,
        null=True,
        default=list,
        help_text="List of fields in the dataset to be imported. Empty list if all fields will be imported.",
        verbose_name="Imported Fields",
    )
    import_filter = models.TextField(
        blank=True,
        null=True,
        help_text="Filter to be applied during import, e.g., 'temperature > 0'. If empty, no filter is applied.",
        verbose_name="Import Filter",
    )
    aggregations = models.JSONField(
        default=list,
        blank=True,
        null=True,
        help_text="List of aggregations to be applied to the if data frequency is > daily. Format: {'group_by_field: 'timestamp', 'target_field_name': 'date', 'parameters': [precipitation: ['sum'], 'temperature': ['min', 'max', 'mean']]}",
        verbose_name="Aggregations",
    )
    active = models.BooleanField(
        default=True,
        help_text="Indicates if the dataset is active. Only active datasets will be imported and synchronized.",
        verbose_name="Active Dataset",
    )
    
    source_identifier = models.CharField(
        max_length=255,
        help_text="Unique identifier for the source dataset.",
        verbose_name="Source Identifier",
    )
    base_url = models.CharField(
        max_length=255, help_text="base url for ODS-datasets.", verbose_name="Base URL"
    )
    source_timestamp_field = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Field in the source dataset that contains the timestamp.",
        verbose_name="Source Timestamp Field",
    )
    db_timestamp_field = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Field in the database that contordering = ['title']  # or any other fieldains the timestamp.",
        verbose_name="Database Timestamp Field",
    )
    record_identifier_field = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Field in the source dataset that uniquely identifies a record and increases with each import. if left empty, the entire daset will be imported each time, which is ok for smaller datasets where each record might change.",
        verbose_name="Record Identifier Field",
    )
    target_table_name = models.CharField(
        max_length=255,
        help_text="Name of the target table in the database.",
        verbose_name="Target Table",
    )
    add_time_aggregation_fields = models.BooleanField(
        default=False,
        help_text="Indicates if time aggregation fields (year, month, dayinyear, season) should be added.",
        verbose_name="Add Time Aggregation Fields",
    )
    delete_records_with_missing_values = models.JSONField(
        default=list,
        null=True,
        blank=True,
        help_text="List of fields for which records with missing values should be deleted.",
        verbose_name="Fields To Delete When Missing",
    )
    last_import_date = models.DateTimeField(
        null=True,
        blank=True,
        auto_now=True,
        help_text="Timestamp of the last import for this dataset.",
        verbose_name="Last Import Date",
    )
    post_import_sql_commands = models.TextField(
        blank=True,
        null=True,
        help_text="SQL commands to be executed after each import process.",
        verbose_name="Post Import SQL Commands",
    )
    post_create_sql_commands = models.TextField(
        blank=True,
        null=True,
        help_text="SQL commands to be executed after the initial table has been created.",
        verbose_name="Post Create SQL Commands",
    )
    data_update_frequency = models.ForeignKey(
        Period,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="datasets_by_update_frequency",
        help_text="Frequency of data updates for this dataset.",
        verbose_name="Data Update Frequency",
    )
    year_field = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Name of the field representing the year in the dataset.",
        verbose_name="Year Field",
    )
    
    month_field = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Name of the field representing the month in the dataset.",
        verbose_name="Month Field",
    )
    
    import_month = models.IntegerField(
        blank=True,
        null=True,
        help_text="Month to be imported when the import type is NEW_MONTH or NEW_YEAR_MONTH (1-12).",
        verbose_name="Import Month",
    )       

    import_day = models.IntegerField(
        blank=True,     
        null=True,
        help_text="Day to be imported when the import type is DAILY_RELOAD (1-31).",
        verbose_name="Import Day",
    )

    import_type = models.ForeignKey(
        ImportType,
        help_text="Type of import to be performed for this dataset.",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="datasets_by_import_type",
        verbose_name="Import Type",
    )

    allow_future_data = models.BooleanField(
        default=False,
        help_text="If true, limits the data import upto yesterday's date to avoid partial data"
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
