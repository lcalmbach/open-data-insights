import csv
import json
import random
import re
import shlex
import subprocess
import sys
from pathlib import Path

import altair as alt
import markdown2
import pandas as pd
from iommi import Column, Table

from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import connection
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

from account.models import CustomUser
from .forms import StoryRatingForm
from .models.dataset import Dataset
from .models.graphic import Graphic
from .models.story_template import StoryTemplate, StoryTemplateDataset
from .models.story import Story
from .models.story_table import StoryTable
from .models.lookups import Period
from .models.story_rating import StoryRating
from .models.quote import Quote
from .services.database_client import DjangoPostgresClient
from .services.utils import normalize_sql_query

MARKDOWN_EXTRAS = ["tables", "fenced-code-blocks"]

class _RequestWithFilteredQuery:
    """Lightweight request proxy that drops a handful of query keys."""

    def __init__(self, request, *, exclude_keys=()):
        object.__setattr__(self, "_request", request)
        filtered_get = request.GET.copy()
        for key in exclude_keys:
            filtered_get.pop(key, None)
        object.__setattr__(self, "GET", filtered_get)

    def __getattr__(self, name):
        return getattr(self._request, name)

    def __setattr__(self, name, value):
        if name in {"_request", "GET"}:
            object.__setattr__(self, name, value)
        else:
            setattr(self._request, name, value)


class _DatasetRow:
    """Wrap a record so sorting via ``col_n`` works even for plain dict data."""

    def __init__(self, data, column_names):
        self._data = data
        self._column_names = column_names
        for idx, column_name in enumerate(column_names):
            setattr(self, f"col_{idx}", data.get(column_name))

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __getitem__(self, item):
        return self._data[item]


def _get_daily_quote(for_date=None) -> Quote | None:
    """Return a deterministic quote of the day (exclude ChatGPT)."""
    quote_qs = Quote.objects.exclude(author__iexact="chatgpt").order_by("id")
    total = quote_qs.count()
    if total == 0:
        return None
    day = for_date or timezone.localdate()
    index = day.toordinal() % total
    return quote_qs[index]


def _get_daily_splash_image(for_date=None) -> str:
    """Return a deterministic splash image path relative to static/."""
    images_dir = Path(settings.BASE_DIR) / "static" / "reports"
    if not images_dir.is_dir():
        return "reports/splash.png"
    images = sorted(
        [
            path.name
            for path in images_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
        ]
    )
    if not images:
        return "reports/splash.png"
    day = for_date or timezone.localdate()
    index = day.toordinal() % len(images)
    return f"reports/{images[index]}"


def _accessible_template_ids(user):
    """Return the story template IDs accessible to the current user."""
    return list(
        StoryTemplate.objects.accessible_to(user).values_list("id", flat=True)
    )


def _extract_chart_id(content_html: str | None) -> str | None:
    if not content_html:
        return None
    match = re.search(r'vegaEmbed\([\"\']#([^\"\']+)[\"\']', content_html)
    if match:
        return match.group(1)
    match = re.search(r'id=[\"\\\']([^\"\\\']+)[\"\\\']', content_html)
    return match.group(1) if match else None


def _attach_graphic_chart_ids(graphics):
    for graphic in graphics:
        graphic.chart_id = _extract_chart_id(graphic.content_html)


def _extract_leaflet_requirements(content_html: str | None) -> tuple[bool, bool]:
    if not content_html:
        return False, False
    needs_leaflet = bool(
        re.search(r'data-leaflet-map=["\\\']1["\\\']', content_html)
        or re.search(r"\bL\.map\(", content_html)
    )
    needs_markercluster = bool(
        re.search(r'data-markercluster=["\\\']1["\\\']', content_html)
        or re.search(r"\bmarkerClusterGroup\(", content_html)
    )
    return needs_leaflet, needs_markercluster


def _attach_graphic_requirements(graphics):
    needs_leaflet = False
    needs_markercluster = False
    for graphic in graphics:
        graphic_requires_leaflet, graphic_requires_markercluster = _extract_leaflet_requirements(
            graphic.content_html
        )
        graphic.requires_leaflet = graphic_requires_leaflet
        graphic.requires_markercluster = graphic_requires_markercluster
        needs_leaflet = needs_leaflet or graphic_requires_leaflet
        needs_markercluster = needs_markercluster or graphic_requires_markercluster
    return needs_leaflet, needs_markercluster


@never_cache
def home_view(request):
    random_quote = _get_daily_quote()
    splash_image = _get_daily_splash_image()
    template_ids = _accessible_template_ids(request.user)
    stories = list(
        Story.objects.filter(template_id__in=template_ids).order_by("-published_date")
    )
    if not stories:
        return render(
            request,
            "home.html",
            {
                "story": None,
                "random_quote": random_quote,
                "splash_image": splash_image,
            },
        )
    selected_story = stories[0]
    next_story_id = stories[1].id if len(stories) > 1 else None
    selected_story.content_html = markdown2.markdown(
        selected_story.content, extras=MARKDOWN_EXTRAS
    )
    tables = get_tables(selected_story) if selected_story else []
    graphics = selected_story.story_graphics.all() if selected_story else []
    _attach_graphic_chart_ids(graphics)
    needs_leaflet, needs_markercluster = _attach_graphic_requirements(graphics)
    data_source = selected_story.template.data_source if selected_story else None
    other_ressources = (
        selected_story.template.other_ressources if selected_story else None
    )
    available_subscriptions = len(template_ids)
    return render(
        request,
        "home.html",
        {
            "selected_story": selected_story,
            "prev_story_id": None,
            "next_story_id": next_story_id,
            "tables": tables,
            "graphics": graphics,
            "data_source": data_source,
            "other_ressources": other_ressources,
            "available_subscriptions": available_subscriptions,
            "random_quote": random_quote,
            "num_insights": Story.objects.count(),
            "splash_image": splash_image,
            "needs_leaflet": needs_leaflet,
            "needs_markercluster": needs_markercluster,
        },
    )


def templates_view(request):
    # Filter aus Query
    period_id = (request.GET.get("period") or "").strip()
    search = (request.GET.get("search") or "").strip()
    selected_template_id = (request.GET.get("template") or "").strip()
    story_count = 0

    # Gefilterte Ergebnisliste
    accessible_templates = StoryTemplate.objects.accessible_to(request.user)
    qs = accessible_templates.select_related("reference_period").order_by("title")

    if period_id:
        qs = qs.filter(reference_period_id=period_id)

    if search:
        qs = qs.filter(Q(title__icontains=search) | Q(description__icontains=search))

    # Ausgewähltes Template: zuerst ?template=..., sonst erstes der gefilterten Liste
    selected_template = None
    if selected_template_id:
        selected_template = qs.filter(id=selected_template_id).first()
    if not selected_template:
        selected_template = qs.first()
    datasets = StoryTemplateDataset.objects.filter(story_template=selected_template)
    # Markdown nur für das ausgewählte Template rendern
    if selected_template and selected_template.description:
        selected_template.description_html = markdown2.markdown(
            selected_template.description, extras=MARKDOWN_EXTRAS
        )
        story_count = Story.objects.filter(template=selected_template).count()
    else:
        story_count = 0
    periods = Period.objects.order_by("value")

    subscribed_count = (
        selected_template.subscriptions.all().count() if selected_template else 0
    )
    admin_template_edit_url = None
    if request.user.is_staff and selected_template:
        admin_template_edit_url = reverse(
            "admin:reports_storytemplate_change", args=(selected_template.id,)
        )
    
    return render(
        request,
        "reports/templates_list.html",
        {
            "templates": qs,  # gefilterte Liste
            "selected_template": selected_template,
            "periods": periods,  # für Perioden-Select
            "story_count": story_count,
            "total_users": CustomUser.objects.all().count(),
            "subscribed_count": subscribed_count,
            "admin_template_edit_url": admin_template_edit_url,
            "datasets":datasets,
        },
    )
    




def stories_view(request):
    accessible_templates = StoryTemplate.objects.accessible_to(request.user)
    template_ids = list(accessible_templates.values_list("id", flat=True))
    templates = accessible_templates.order_by("title")

    # Base queryset
    stories = (
        Story.objects.select_related("template")
        .filter(template_id__in=template_ids)
        .order_by("-published_date")
    )
    periods = Period.objects.order_by("value")
    # Filter by selected template
    template_id = request.GET.get("template")
    if template_id and template_id.isdigit() and int(template_id) not in template_ids:
        template_id = None
    if template_id:
        stories = stories.filter(template_id=template_id)

    # Filter by search query
    search = request.GET.get("search")
    if search:
        stories = stories.filter(
            Q(title__icontains=search) | Q(content__icontains=search)
        )

    # Filter by published date range
    published_from = parse_date(request.GET.get("published_from") or "")
    published_to = parse_date(request.GET.get("published_to") or "")
    if published_from:
        stories = stories.filter(published_date__gte=published_from)
    if published_to:
        stories = stories.filter(published_date__lte=published_to)

    # Selected story (for detail view)
    story_id = request.GET.get("story")
    if not stories.filter(id=story_id).exists():
        story_id = stories.first().id if stories else None
    selected_story = stories.filter(id=story_id).first() if story_id else None
    # Process story content
    if selected_story:
        graphics = selected_story.story_graphics.all() if selected_story else []
        _attach_graphic_chart_ids(graphics)
        needs_leaflet, needs_markercluster = _attach_graphic_requirements(graphics)
        data_source = selected_story.template.data_source if selected_story else None
        other_ressources = (
            selected_story.template.other_ressources if selected_story else None
        )
        # Get tables and convert directly to DataFrames
        tables = get_tables(selected_story) if selected_story else []
        selected_story.content_html = markdown2.markdown(
            selected_story.content, extras=MARKDOWN_EXTRAS
        )
    else:
        graphics = []
        needs_leaflet = False
        needs_markercluster = False
        data_source = None
        other_ressources = None
        tables = []

    return render(
        request,
        "reports/stories_list.html",
        {
            "templates": templates,
            "stories": stories,
            "selected_story": selected_story,
            "graphics": graphics,
            "tables": tables,
            "other_ressources": other_ressources,
            "data_source": data_source,
            "periods": periods,
            "needs_leaflet": needs_leaflet,
            "needs_markercluster": needs_markercluster,
        },
    )


def datasets_view(request):
    search = (request.GET.get("search") or "").strip()
    source_filter = (request.GET.get("source") or "").strip()
    frequency_filter = (request.GET.get("frequency") or "").strip()
    selected_dataset_id = request.GET.get("dataset")
    try:
        preview_limit = int(request.GET.get("limit") or 200)
    except (TypeError, ValueError):
        preview_limit = 200
    preview_limit = max(25, min(preview_limit, 1000))

    try:
        page_size = int(request.GET.get("page_size") or 50)
    except (TypeError, ValueError):
        page_size = 50
    page_size = max(5, min(page_size, 200))

    dataset_qs = (
        Dataset.objects.filter(active=True)
        .select_related("data_update_frequency")
        .order_by("name")
    )
    if source_filter:
        dataset_qs = dataset_qs.filter(source__iexact=source_filter)
    if frequency_filter.isdigit():
        dataset_qs = dataset_qs.filter(data_update_frequency_id=int(frequency_filter))
    if search:
        dataset_qs = dataset_qs.filter(
            Q(name__icontains=search)
            | Q(description__icontains=search)
            | Q(source_identifier__icontains=search)
            | Q(target_table_name__icontains=search)
        )

    filtered_datasets = list(dataset_qs)
    dataset_count = len(filtered_datasets)
    selected_dataset = None
    if selected_dataset_id:
        for dataset in filtered_datasets:
            if str(dataset.id) == selected_dataset_id:
                selected_dataset = dataset
                break
    if not selected_dataset and filtered_datasets:
        selected_dataset = filtered_datasets[0]

    sources = (
        Dataset.objects.filter(active=True)
        .order_by("source")
        .values_list("source", flat=True)
        .distinct()
    )
    frequency_options = (
        Period.objects.filter(datasets_by_update_frequency__active=True)
        .distinct()
        .order_by("value")
    )

    table = None
    table_error = None
    preview_rows = 0
    dataset_row_count = None
    data_schema = getattr(settings, "DB_DATA_SCHEMA", "opendata")

    insight_templates = []
    if selected_dataset:
        try:
            client = DjangoPostgresClient()
            table_full_name = (
                f'"{client.schema}"."{selected_dataset.target_table_name}"'
            )
            if not client.table_exists(selected_dataset.target_table_name):
                table_error = (
                    f"Target table {selected_dataset.target_table_name!r} is not available "
                    f"in the {client.schema} schema."
                )
            else:
                try:
                    count_df = client.run_query(
                        f"SELECT COUNT(*) AS total FROM {table_full_name}"
                    )
                    if not count_df.empty:
                        dataset_row_count = int(count_df.iloc[0, 0])
                except Exception:
                    dataset_row_count = None

                query = (
                    f"SELECT * FROM {table_full_name} LIMIT {preview_limit}"
                )
                df = client.run_query(query)
                columns = df.columns.tolist()
                if not columns:
                    table_error = (
                        "The selected dataset table has no columns to render."
                    )
                else:
                    records = df.to_dict("records")
                    column_kwargs = {}
                    for idx, column_name in enumerate(columns):
                        column_kwargs[f"columns__col_{idx}"] = Column(
                            display_name=column_name,
                            cell__value=lambda row, column_name=column_name, **_: row.get(
                                column_name
                            ),
                        )
                    # IOMMI will try to refine a stray `paginator` query parameter even though
                    # this preview table does not expose it, so strip it before binding.
                    request_for_table = (
                        request
                        if "paginator" not in request.GET
                        else _RequestWithFilteredQuery(
                            request, exclude_keys=("paginator",)
                        )
                    )
                    rows = [_DatasetRow(record, columns) for record in records]
                    table = (
                        Table(
                            rows=rows,
                            page_size=page_size,
                            **column_kwargs,
                        )
                        .bind(request=request_for_table)
                    )
            preview_rows = len(records)
        except Exception as exc:  # noqa: BLE001
            table_error = f"Unable to load dataset data: {exc}"
        insight_templates = list(
            StoryTemplate.objects.accessible_to(request.user)
            .filter(datasets__dataset=selected_dataset)
            .distinct()
            .order_by("title")
        )

    return render(
        request,
        "reports/datasets_list.html",
        {
            "datasets": filtered_datasets,
            "selected_dataset": selected_dataset,
            "dataset_count": dataset_count,
            "sources": sources,
            "frequencies": frequency_options,
            "table": table,
            "table_error": table_error,
            "preview_rows": preview_rows,
            "preview_limit": preview_limit,
            "dataset_row_count": dataset_row_count,
            "data_schema": data_schema,
            "filters": {
                "search": search,
                "source": source_filter,
                "frequency": frequency_filter,
                "dataset": selected_dataset_id or "",
                "limit": preview_limit,
                "page_size": page_size,
            },
            "insight_templates": insight_templates,
        },
    )


@login_required
def storytemplate_detail_view(request, pk):
    template = get_object_or_404(
        StoryTemplate.objects.accessible_to(request.user), pk=pk
    )
    template.description_html = markdown2.markdown(
        template.description, extras=MARKDOWN_EXTRAS
    )
    back_url = request.META.get("HTTP_REFERER", "/")  # fallback: Startseite
    
    admin_template_edit_url = None
    if request.user.is_staff:
        admin_template_edit_url = reverse(
            "admin:reports_storytemplate_change", args=(template.id,)
        )
    return render(
        request,
        "reports/storytemplate_detail.html",
        {
            "template": template,
            "back_url": back_url,
            "admin_template_edit_url": admin_template_edit_url,
        },
    )


@login_required
def rate_story(request, story_id):
    story = get_object_or_404(Story, pk=story_id)
    if request.method == "POST":
        form = StoryRatingForm(request.POST)
        rating = request.POST.get("rating")

        if form.is_valid() and rating:
            StoryRating.objects.create(
                story=story,
                user=request.user,
                rating=int(rating),
                rating_text=form.cleaned_data["rating_text"],
            )
            return render(request, "reports/story_rating_thanks.html", {"story": story})
    else:
        form = StoryRatingForm()

    return render(request, "reports/story_rating.html", {"form": form, "story": story})


class AboutView(TemplateView):
    template_name = "about.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["app_info"] = settings.APP_INFO
        context["num_insights"] = Story.objects.count()
        context["num_datasets"] = Dataset.objects.filter(active=True).count()
        context["num_story_templates"] = StoryTemplate.objects.count()
        context["num_odi_datasets"] = Dataset.objects.filter(active=True, source = 'odi').count()
        context["num_non_odi_datasets"] = context["num_datasets"] - context["num_odi_datasets"] 
        return context


def view_story(request, story_id=None):
    random_quote = _get_daily_quote()
    splash_image = _get_daily_splash_image()
    template_ids = _accessible_template_ids(request.user)
    stories = list(
        Story.objects.filter(template_id__in=template_ids).order_by("-published_date")
    )
    if not stories:
        return render(
            request,
            "home.html",
            {
                "story": None,
                "random_quote": random_quote,
                "splash_image": splash_image,
            },
        )

    if story_id is None:
        selected_story = stories[0]  # Default to the first story
    else:
        selected_story = get_object_or_404(
            Story.objects.filter(template_id__in=template_ids),
            id=story_id,
        )
    index = stories.index(selected_story)
    prev_story_id = stories[index - 1].id if index > 0 else None
    next_story_id = stories[index + 1].id if index < len(stories) - 1 else None
    tables = get_tables(selected_story) if selected_story else []
    graphics = selected_story.story_graphics.all() if selected_story else []
    _attach_graphic_chart_ids(graphics)
    needs_leaflet, needs_markercluster = _attach_graphic_requirements(graphics)
    data_source = selected_story.template.data_source if selected_story else None
    other_ressources = (
        selected_story.template.other_ressources if selected_story else None
    )
    available_subscriptions = len(template_ids)
    selected_story.content_html = markdown2.markdown(
        selected_story.content, extras=MARKDOWN_EXTRAS
    )
    return render(
        request,
        "home.html",
        {
            "selected_story": selected_story,
            "prev_story_id": prev_story_id,
            "next_story_id": next_story_id,
            "graphics": graphics,
            "tables": tables,
            "other_ressources": other_ressources,
            "data_source": data_source,
            "available_subscriptions": available_subscriptions,
            "random_quote": random_quote,
            "splash_image": splash_image,
            "needs_leaflet": needs_leaflet,
            "needs_markercluster": needs_markercluster,
        },
    )


def story_detail(request, story_id=None):
    template_ids = _accessible_template_ids(request.user)
    selected_story = get_object_or_404(
        Story.objects.filter(template_id__in=template_ids),
        id=story_id,
    )
    tables = get_tables(selected_story) if selected_story else []
    graphics = selected_story.story_graphics.all() if selected_story else []
    _attach_graphic_chart_ids(graphics)
    needs_leaflet, needs_markercluster = _attach_graphic_requirements(graphics)
    data_source = selected_story.template.data_source if selected_story else None
    other_ressources = (
        selected_story.template.other_ressources if selected_story else None
    )

    selected_story.content_html = markdown2.markdown(
        selected_story.content, extras=MARKDOWN_EXTRAS
    )
    return render(
        request,
        "reports/story_detail.html",
        {
            "selected_story": selected_story,
            "graphics": graphics,
            "tables": tables,
            "other_ressources": other_ressources,
            "data_source": data_source,
            "needs_leaflet": needs_leaflet,
            "needs_markercluster": needs_markercluster,
        },
    )


@login_required
@user_passes_test(lambda user: user.is_staff)
def delete_story(request, story_id):
    template_ids = _accessible_template_ids(request.user)
    story_to_delete = get_object_or_404(
        Story.objects.filter(template_id__in=template_ids),
        id=story_id,
    )
    if request.method != "POST":
        return redirect("story_detail", story_id=story_id)
    story_to_delete.delete()
    return redirect("stories")


_READ_ONLY_SQL_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|call|execute|copy)\b",
    re.IGNORECASE,
)


def _validate_read_only_sql(query: str) -> tuple[str | None, str]:
    clean_query = normalize_sql_query(query or "")
    if not clean_query:
        return "Enter a SQL query.", clean_query
    if ";" in clean_query:
        return "Only one SQL statement is allowed.", clean_query
    if not re.match(r"^(select|with)\b", clean_query, re.IGNORECASE):
        return "Only SELECT (read-only) queries are allowed.", clean_query
    if _READ_ONLY_SQL_FORBIDDEN.search(clean_query):
        return "Only read-only queries are allowed.", clean_query
    return None, clean_query


def _get_schema_tables(schema: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            [schema],
        )
        return [row[0] for row in cursor.fetchall()]


@login_required
@user_passes_test(lambda user: user.is_staff)
def query_datasets_view(request):
    query = ""
    max_rows = 200
    result = None
    error = None
    schema = getattr(settings, "DB_DATA_SCHEMA", "opendata")
    tables = _get_schema_tables(schema)

    if request.method == "POST":
        query = (request.POST.get("query") or "").strip()
        max_rows_raw = (request.POST.get("max_rows") or "").strip()
        if max_rows_raw:
            try:
                max_rows = int(max_rows_raw)
            except ValueError:
                error = "Max rows must be a number."
        if error is None:
            if max_rows < 1 or max_rows > 1000:
                error = "Max rows must be between 1 and 1000."
        if error is None:
            error, clean_query = _validate_read_only_sql(query)
        if error is None:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(clean_query)
                    columns = (
                        [col[0] for col in cursor.description]
                        if cursor.description
                        else []
                    )
                    rows = cursor.fetchmany(max_rows + 1)
                has_more = len(rows) > max_rows
                rows = rows[:max_rows]
                result = {
                    "columns": columns,
                    "rows": rows,
                    "has_more": has_more,
                }
            except Exception as exc:
                error = f"Query failed: {exc}"

    return render(
        request,
        "reports/query_datasets.html",
        {
            "query": query,
            "max_rows": max_rows,
            "result": result,
            "error": error,
            "schema": schema,
            "tables": tables,
        },
    )


def _parse_recipient_list(raw: str) -> tuple[list[str], list[str]]:
    tokens = [token for token in re.split(r"[,\s;]+", raw or "") if token]
    valid = []
    invalid = []
    seen = set()
    for token in tokens:
        email = token.strip()
        if not email or email in seen:
            continue
        try:
            validate_email(email)
            valid.append(email)
            seen.add(email)
        except ValidationError:
            invalid.append(email)
    return valid, invalid


@login_required
@user_passes_test(lambda user: user.is_staff)
def email_users_view(request):
    subject = ""
    message = ""
    recipient_group = "confirmed"
    specific_emails = ""
    send_to_self = False
    selected_user_ids = []
    result = None
    error = None
    selectable_users = list(
        CustomUser.objects.filter(is_active=True).order_by("email", "id")
    )

    if request.method == "POST":
        subject = (request.POST.get("subject") or "").strip()
        message = (request.POST.get("message") or "").strip()
        recipient_group = (request.POST.get("recipient_group") or "confirmed").strip()
        specific_emails = (request.POST.get("specific_emails") or "").strip()
        send_to_self = bool(request.POST.get("send_to_self"))
        selected_user_ids = [
            int(val) for val in request.POST.getlist("specific_users") if val.isdigit()
        ]

        if not subject or not message:
            error = "Subject and message are required."
        else:
            recipients = []
            invalid_emails = []

            if send_to_self:
                if request.user.email:
                    recipients = [request.user.email]
                else:
                    error = "Your account does not have an email address."
            elif recipient_group == "specific":
                if selected_user_ids:
                    recipients = list(
                        CustomUser.objects.filter(
                            id__in=selected_user_ids, is_active=True
                        ).values_list("email", flat=True)
                    )
                if not recipients:
                    recipients, invalid_emails = _parse_recipient_list(specific_emails)
                    if invalid_emails:
                        error = f"Invalid emails: {', '.join(invalid_emails)}"
            else:
                qs = CustomUser.objects.filter(is_active=True)
                if recipient_group == "confirmed":
                    qs = qs.filter(is_confirmed=True)
                elif recipient_group == "staff":
                    qs = qs.filter(is_staff=True)
                recipients = list(qs.values_list("email", flat=True))

            recipients = [email for email in recipients if email]
            if error is None and not recipients:
                error = "No recipients found for the selected group."

            if error is None:
                from_email = getattr(
                    settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com"
                )
                sent = 0
                failed = []
                for email in recipients:
                    try:
                        send_mail(subject, message, from_email, [email])
                        sent += 1
                    except Exception as exc:
                        failed.append({"email": email, "error": str(exc)})
                result = {
                    "total": len(recipients),
                    "sent": sent,
                    "failed": failed,
                }

    return render(
        request,
        "reports/email_users.html",
        {
            "subject": subject,
            "message": message,
            "recipient_group": recipient_group,
            "specific_emails": specific_emails,
            "selected_user_ids": selected_user_ids,
            "send_to_self": send_to_self,
            "result": result,
            "error": error,
            "selectable_users": selectable_users,
        },
    )


@login_required
@user_passes_test(lambda user: user.is_staff)
def run_commands_view(request):
    command = ""
    result = None
    if request.method == "POST":
        command = (request.POST.get("command") or "").strip()
        if command:
            try:
                args = shlex.split(command)
                manage_py = settings.BASE_DIR / "manage.py"
                completed = subprocess.run(
                    [sys.executable, str(manage_py), *args],
                    capture_output=True,
                    text=True,
                    check=False,
                    cwd=settings.BASE_DIR,
                    timeout=60,
                )
                result = {
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            except ValueError as exc:
                result = {"error": f"Invalid command: {exc}"}
            except subprocess.TimeoutExpired as exc:
                result = {"error": f"Command timed out after {exc.timeout} seconds."}
        else:
            result = {"error": "Enter a management command to run."}

    return render(
        request,
        "reports/run_commands.html",
        {"command": command, "result": result},
    )


def get_tables(selected_story):
    """
    Returns a list of table dicts for the given story, each with:
      table_id, rows, columns, title, sort_order, display_title.
    """
    tables = []
    if not selected_story:
        return tables

    # Prefer ordering by sort_order if the model has it; fall back to id.
    qs = (
        StoryTable.objects
        .filter(story=selected_story)
        .select_related('table_template')  # if relation exists
        .order_by('sort_order', 'id')      # adjust if your field is named differently
    )

    for t in qs:
        try:
            data = json.loads(t.data) if t.data else []
            columns = list(data[0].keys()) if data else []

            # Try table.sort_order first; else table.table_template.sort_order; else None
            sort_order = getattr(t, 'sort_order', None)
            if sort_order is None and hasattr(t, 'table_template'):
                sort_order = getattr(t.table_template, 'sort_order', None)

            title = t.title or f"Table {t.id}"

            # Precompute a display title so the template stays simple
            display_title = f"Table {sort_order + 1}: {title}" if sort_order is not None else title

            tables.append(
                {
                    "id": t.id,
                    "table_id": f"table-{t.id}",
                    "rows": data,
                    "columns": columns,
                    "title": title,
                    "sort_order": sort_order,
                    "display_title": display_title,
                }
            )
        except Exception as e:
            print(f"Error processing table {t.id}: {e}")

    return tables


def download_story_table_csv(request, table_id):
    table = get_object_or_404(StoryTable, pk=table_id)
    raw_data = table.data or []
    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except json.JSONDecodeError:
            raw_data = []

    if isinstance(raw_data, list):
        rows = raw_data
        columns = list(rows[0].keys()) if rows else []
    elif isinstance(raw_data, dict):
        columns = list(raw_data.keys())
        row_count = max(
            (len(values) for values in raw_data.values() if isinstance(values, list)),
            default=0,
        )
        rows = []
        for i in range(row_count):
            row = {}
            for column in columns:
                values = raw_data[column]
                if isinstance(values, list):
                    row[column] = values[i] if i < len(values) else ""
                else:
                    row[column] = values
            rows.append(row)
    else:
        rows = []
        columns = []

    filename = slugify(table.title) or f"table-{table.id}"
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    writer = csv.writer(response)
    if columns:
        writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(column, "") for column in columns])
    return response
