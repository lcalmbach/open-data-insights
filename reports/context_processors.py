from django.conf import settings

from .language import get_content_language_id
from .taxonomy_utils import taxonomy_choices
from .utils import TIME_FREQUENCY_CHOICES


def ai_disclaimer(request):
    return {
        "AI_DISCLAIMER": (
            """🤖 This text was generated with the assistance of AI. All quantitative statements are derived directly from the dataset listed under <i>Data Source</i>."""
        )
    }


def format_instructions(request):
    return {
        "FORMAT_INSTRUCTIONS": (
            "Format the output as plain Markdown. Do not use bold or italic text for emphasis. Avoid using bullet points, numbered lists, or subheadings. Write in concise, complete sentences. Ensure that the structure is clean and easy to read using only paragraphs."
        )
    }


def show_dev_banner(request):
    return {"SHOW_DEV_BANNER": getattr(settings, "SHOW_DEV_BANNER", False)}


def content_language(request):
    """
    Provide content-language (stories) selection to all templates (navbar).
    """
    try:
        from reports.models.lookups import Language

        languages = Language.objects.order_by("sort_order", "value")
    except Exception:  # noqa: BLE001
        languages = []

    return {
        "available_languages": languages,
        "content_language_id": get_content_language_id(request),
    }


def navbar_story_filters(request):
    try:
        from reports.models.lookups import Region, Topic
        from reports.models.story_template import StoryTemplate

        region_choices = taxonomy_choices(Region)
        topic_choices = taxonomy_choices(Topic)
        template_choices = StoryTemplate.objects.accessible_to(request.user).order_by(
            "title"
        )
    except Exception:  # noqa: BLE001
        region_choices = []
        topic_choices = []
        template_choices = []

    return {
        "navbar_template_choices": template_choices,
        "navbar_region_choices": region_choices,
        "navbar_topic_choices": topic_choices,
        "navbar_time_frequency_choices": TIME_FREQUENCY_CHOICES,
    }
