from __future__ import annotations

from django.conf import settings

CONTENT_LANGUAGE_SESSION_KEY = "content_language_id"

# LookupValue IDs (see reports.models.lookups.LanguageEnum)
ENGLISH_LANGUAGE_ID = 94


def get_content_language_id(request) -> int:
    """
    Content language (stories) resolution order:
    1) Session override (CONTENT_LANGUAGE_SESSION_KEY)
    2) Authenticated user's preferred_language_id
    3) Settings DEFAULT_PREFERRED_LANGUAGE_ID, else ENGLISH_LANGUAGE_ID
    """
    session_value = request.session.get(CONTENT_LANGUAGE_SESSION_KEY)
    if session_value is not None:
        try:
            return int(session_value)
        except (TypeError, ValueError):
            pass

    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        preferred_id = getattr(user, "preferred_language_id", None)
        if preferred_id:
            return int(preferred_id)

    return int(getattr(settings, "DEFAULT_PREFERRED_LANGUAGE_ID", ENGLISH_LANGUAGE_ID))


def set_content_language_id(request, language_id: int) -> None:
    request.session[CONTENT_LANGUAGE_SESSION_KEY] = int(language_id)
    request.session.modified = True

