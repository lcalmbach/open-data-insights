from django.conf import settings

from .language import get_content_language_id


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
