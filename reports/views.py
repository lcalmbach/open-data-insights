from django.shortcuts import render
from django.http import HttpResponse
from .models import Graphic, StoryTemplate, Story, StoryTable, Period
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.shortcuts import render, get_object_or_404
import markdown2
import json
import random

import altair as alt
import pandas as pd

from django.conf import settings
from django.views.generic import TemplateView
from django.db.models import Q

from .forms import StoryRatingForm
from .models import Graphic, Story, StoryRating, StoryTable, StoryTemplate


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


@never_cache
def home_view(request):
    stories = list(Story.objects.order_by("-published_date"))
    if not stories:
        return render(request, "home.html", {"story": None})
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
    available_subscriptions = StoryTemplate.objects.count()
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
        },
    )


def templates_view(request):
    templates = StoryTemplate.objects.all()
    # provide period lookup values for the template filter (Period model contains code/name)
    periods = Period.objects.order_by("value")
    selected_template_id = request.GET.get("template")
    selected_template = None

    if selected_template_id:
        selected_template = get_object_or_404(StoryTemplate, id=selected_template_id)
        selected_template.description_html = markdown2.markdown(
            selected_template.description, extras=["tables"]
        )

    return render(
        request,
        "reports/templates_list.html",
        {
            "templates": templates,
            "selected_template": selected_template,
            "periods": periods,
        },
    )


def stories_view(request):
    # Fetch all templates
    templates = StoryTemplate.objects.order_by("title")

    # Base queryset
    stories = Story.objects.select_related("template").order_by("-published_date")

    # Filter by selected template
    template_id = request.GET.get("template")
    if template_id:
        stories = stories.filter(template_id=template_id)

    # Filter by search query
    search = request.GET.get("search")
    if search:
        stories = stories.filter(
            Q(title__icontains=search) | Q(content__icontains=search)
        )

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
        },
    )


@login_required
def storytemplate_detail_view(request, pk):
    template = get_object_or_404(StoryTemplate, pk=pk)
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
    stories = list(Story.objects.order_by("-published_date"))
    if not stories:
        return render(request, "home.html", {"story": None})

    if story_id is None:
        selected_story = stories[0]  # Default to the first story
    else:
        selected_story = get_object_or_404(Story, id=story_id)
    index = stories.index(selected_story)
    prev_story_id = stories[index - 1].id if index > 0 else None
    next_story_id = stories[index + 1].id if index < len(stories) - 1 else None
    tables = get_tables(selected_story) if selected_story else []
    graphics = selected_story.story_graphics.all() if selected_story else []
    data_source = selected_story.template.data_source if selected_story else None
    other_ressources = (
        selected_story.template.other_ressources if selected_story else None
    )
    available_subscriptions = StoryTemplate.objects.count()
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
        },
    )


def story_detail(request, story_id=None):
    selected_story = get_object_or_404(Story, id=story_id)
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
    Returns a list of table dicts for the given story, each with table_id, rows, columns, and title.
    """
    tables = []
    if selected_story:
        for t in StoryTable.objects.filter(story=selected_story):
            try:
                if t.data:
                    data = json.loads(t.data)
                    columns = list(data[0].keys()) if data else []
                    tables.append(
                        {
                            "table_id": f"table-{t.id}",
                            "rows": data,
                            "columns": columns,
                            "title": t.title or f"Table {t.id}",
                        }
                    )
            except Exception as e:
                print(f"Error processing table {t.id}: {e}")
    return tables
