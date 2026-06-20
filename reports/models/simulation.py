from django.db import models
from django.utils.text import slugify


class SimulationTemplate(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True, blank=True, editable=False)
    description = models.TextField(blank=True, help_text="Internal note on what this tool does.")
    text = models.TextField(blank=True, help_text="Intro/article text (HTML).")
    js_template = models.TextField(
        help_text="Widget HTML+JS. Parameter values are injected as a JS const BASELINE = {...} block."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Simulation Template"
        verbose_name_plural = "Simulation Templates"
        ordering = ["title"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:100]
            slug = base
            n = 1
            while SimulationTemplate.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base[:95]}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class SimulationParameter(models.Model):
    CONSTANT = "constant"
    SQL = "sql"
    PARAMETER_TYPE_CHOICES = [
        (CONSTANT, "Constant"),
        (SQL, "SQL Expression"),
    ]

    simulation = models.ForeignKey(
        SimulationTemplate,
        on_delete=models.CASCADE,
        related_name="parameters",
    )
    parameter_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    parameter_type = models.CharField(max_length=10, choices=PARAMETER_TYPE_CHOICES)
    value = models.DecimalField(
        max_digits=20, decimal_places=6,
        null=True, blank=True,
        help_text="Used when parameter_type is 'constant'.",
    )
    sql_expression = models.TextField(
        blank=True,
        help_text="Must return a single scalar value. Used when parameter_type is 'sql'.",
    )
    sort_order = models.IntegerField(default=0)

    UNIQUE_FIELDS = ("parameter_name",)

    class Meta:
        verbose_name = "Simulation Parameter"
        verbose_name_plural = "Simulation Parameters"
        ordering = ["sort_order", "parameter_name"]
        unique_together = [("simulation", "parameter_name")]

    def __str__(self):
        return f"{self.simulation.title} / {self.parameter_name}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.parameter_type == self.CONSTANT and self.value is None:
            raise ValidationError("A constant parameter requires a value.")
        if self.parameter_type == self.SQL and not self.sql_expression:
            raise ValidationError("A SQL parameter requires a sql_expression.")

    def resolve(self, cursor) -> float:
        if self.parameter_type == self.CONSTANT:
            return float(self.value)
        cursor.execute(self.sql_expression)
        row = cursor.fetchone()
        if row is None:
            raise ValueError(
                f"SQL for parameter '{self.parameter_name}' returned no rows."
            )
        return float(row[0])


class Simulation(models.Model):
    simulation_template = models.ForeignKey(
        SimulationTemplate,
        on_delete=models.CASCADE,
        related_name="generated",
    )
    html = models.TextField(help_text="Fully resolved widget HTML, ready for |safe.")
    parameters_used = models.JSONField(default=dict)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Simulation"
        verbose_name_plural = "Simulations"
        ordering = ["-generated_at"]
        get_latest_by = "generated_at"

    def __str__(self):
        return f"{self.simulation_template.title} ({self.generated_at:%Y-%m-%d})"
