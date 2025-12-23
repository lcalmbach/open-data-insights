import json
import random

import altair as alt
import markdown2
import pandas as pd
from iommi import Column, Table

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

from account.models import CustomUser
from .forms import StoryRatingForm
from .models.dataset import Dataset
from .models.graphic import Graphic
from .models.story_template import StoryTemplate
from .models.story import Story
from .models.story_table import StoryTable
from .models.lookups import Period
from .models.story_rating import StoryRating
from .models.quote import Quote
from .services.database_client import DjangoPostgresClient


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


def generate_fake_graphic(chart_id):
    """Generate a fake graphic as HTML."""
    # Fake DataFrame simulating data retrieved from the database
    data = {
        "date": pd.date_range(start="2025-07-01", periods=5, freq="D"),
        "value": [
            random.randint(5, 25) for _ in range(5)
        ],  # Random values between 5 and 25
    }
    df = pd.DataFrame(data)

    # Fake settings simulating settings stored in the database
    settings = {
        "x": "date",
        "y": "value",
        "x_title": "Date",
        "y_title": "Value",
        "type": "line",  # Graphic type (e.g., bar, line, scatter)
    }

    # Generate the graphic using Altair
    chart = (
        alt.Chart(df)
        .mark_line()
        .encode(
            x=alt.X(settings["x"], title=settings["x_title"]),
            y=alt.Y(settings["y"], title=settings["y_title"]),
        )
    )

    # Convert the chart to HTML
    chart_html = chart.to_html(embed_options={"actions": False, "renderer": "canvas"})

    # Wrap the chart HTML in a div with a unique ID
    container_html = f'<div id="{chart_id}"></div>'
    script_html = chart_html.replace('vegaEmbed("#vis"', f'vegaEmbed("#{chart_id}"')

    return f"{container_html}{script_html}"


def _get_random_quote() -> Quote | None:
    """Return one random quote that is not authored by ChatGPT."""
    return Quote.objects.exclude(author__iexact="chatgpt").order_by("?").first()


def _accessible_template_ids(user):
    """Return the story template IDs accessible to the current user."""
    return list(
        StoryTemplate.objects.accessible_to(user).values_list("id", flat=True)
    )


@never_cache
def home_view(request):
    random_quote = _get_random_quote()
    template_ids = _accessible_template_ids(request.user)
    stories = list(
        Story.objects.filter(template_id__in=template_ids).order_by("-published_date")
    )
    if not stories:
        return render(
            request,
            "home.html",
            {"story": None, "random_quote": random_quote},
        )
    selected_story = stories[0]
    next_story_id = stories[1].id if len(stories) > 1 else None
    selected_story.content_html = markdown2.markdown(
        selected_story.content, extras=["tables"]
    )
    tables = get_tables(selected_story) if selected_story else []
    graphics = selected_story.story_graphics.all() if selected_story else []
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

    # Markdown nur für das ausgewählte Template rendern
    if selected_template and selected_template.description:
        selected_template.description_html = markdown2.markdown(
            selected_template.description, extras=["tables"]
        )
        story_count = Story.objects.filter(template=selected_template).count()
    else:
        story_count = 0
    periods = Period.objects.order_by("value")

    subscribed_count = (
        selected_template.subscriptions.all().count() if selected_template else 0
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
        data_source = selected_story.template.data_source if selected_story else None
        other_ressources = (
            selected_story.template.other_ressources if selected_story else None
        )
        # Get tables and convert directly to DataFrames
        tables = get_tables(selected_story) if selected_story else []
        selected_story.content_html = markdown2.markdown(
            selected_story.content, extras=["tables"]
        )
    else:
        graphics = []
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
        },
    )


@login_required
def storytemplate_detail_view(request, pk):
    template = get_object_or_404(
        StoryTemplate.objects.accessible_to(request.user), pk=pk
    )
    template.description_html = markdown2.markdown(
        template.description, extras=["tables"]
    )
    back_url = request.META.get("HTTP_REFERER", "/")  # fallback: Startseite
    return render(
        request,
        "reports/storytemplate_detail.html",
        {
            "template": template,
            "back_url": back_url,
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
        return context


def view_story(request, story_id=None):
    random_quote = _get_random_quote()
    template_ids = _accessible_template_ids(request.user)
    stories = list(
        Story.objects.filter(template_id__in=template_ids).order_by("-published_date")
    )
    if not stories:
        return render(
            request,
            "home.html",
            {"story": None, "random_quote": random_quote},
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
    data_source = selected_story.template.data_source if selected_story else None
    other_ressources = (
        selected_story.template.other_ressources if selected_story else None
    )
    available_subscriptions = len(template_ids)
    selected_story.content_html = markdown2.markdown(
        selected_story.content, extras=["tables"]
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
    data_source = selected_story.template.data_source if selected_story else None
    other_ressources = (
        selected_story.template.other_ressources if selected_story else None
    )

    selected_story.content_html = markdown2.markdown(
        selected_story.content, extras=["tables"]
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
        },
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
