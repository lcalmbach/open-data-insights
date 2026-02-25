from __future__ import annotations

from django.conf import settings
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CONTENT_LANGUAGE_SESSION_KEY = "content_language_id"

# LookupValue IDs (see reports.models.lookups.LanguageEnum)
ENGLISH_LANGUAGE_ID = 94
GERMAN_LANGUAGE_ID = 95
FRENCH_LANGUAGE_ID = 96

DEFAULT_LANGUAGE_CODE = "en"
SUPPORTED_LANGUAGE_CODES = ("en", "de", "fr")
LANGUAGE_CODE_TO_ID = {
    "en": ENGLISH_LANGUAGE_ID,
    "de": GERMAN_LANGUAGE_ID,
    "fr": FRENCH_LANGUAGE_ID,
}
LANGUAGE_ID_TO_CODE = {value: key for key, value in LANGUAGE_CODE_TO_ID.items()}


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


def get_language_code_for_id(language_id: int | None) -> str:
    resolved = _get_language_code_for_id_from_db(language_id)
    if resolved:
        return resolved
    try:
        return LANGUAGE_ID_TO_CODE[int(language_id)]
    except (TypeError, ValueError, KeyError):
        return DEFAULT_LANGUAGE_CODE


def get_language_id_for_code(language_code: str | None) -> int:
    resolved = _get_language_id_for_code_from_db(language_code)
    if resolved is not None:
        return resolved
    if not language_code:
        return LANGUAGE_CODE_TO_ID[DEFAULT_LANGUAGE_CODE]
    return LANGUAGE_CODE_TO_ID.get(language_code.lower(), LANGUAGE_CODE_TO_ID[DEFAULT_LANGUAGE_CODE])


def split_language_prefix(path: str) -> tuple[str | None, str]:
    """
    Return (language_code, stripped_path).
    Examples:
    - "/en/stories/" -> ("en", "/stories/")
    - "/fr" -> ("fr", "/")
    - "/stories/" -> (None, "/stories/")
    """
    raw_path = path or "/"
    if not raw_path.startswith("/"):
        raw_path = f"/{raw_path}"
    segments = raw_path.lstrip("/").split("/", 1)
    if not segments:
        return None, raw_path
    candidate = (segments[0] or "").lower()
    if candidate not in SUPPORTED_LANGUAGE_CODES:
        return None, raw_path
    remainder = segments[1] if len(segments) > 1 else ""
    stripped = f"/{remainder}" if remainder else "/"
    return candidate, stripped


def with_language_prefix(path: str, language_code: str) -> str:
    _, stripped = split_language_prefix(path)
    normalized_code = language_code if language_code in SUPPORTED_LANGUAGE_CODES else DEFAULT_LANGUAGE_CODE
    return f"/{normalized_code}{stripped}"


def rewrite_url_language(url: str, language_code: str) -> str:
    """
    Rewrite/insert language code in a relative URL while preserving query params.
    If language appears in query as ?lang=..., it is updated too.
    """
    if not url:
        return with_language_prefix("/", language_code)

    parts = urlsplit(url)
    path = parts.path or "/"
    prefixed_path = with_language_prefix(path, language_code)

    query_items = parse_qsl(parts.query, keep_blank_values=True)
    if query_items:
        rewritten = []
        for key, value in query_items:
            if key == "lang":
                rewritten.append((key, language_code))
            else:
                rewritten.append((key, value))
        query = urlencode(rewritten)
    else:
        query = parts.query

    return urlunsplit((parts.scheme, parts.netloc, prefixed_path, query, parts.fragment))


def _infer_language_code(value: str | None, key: str | None) -> str | None:
    raw = f"{(key or '').strip()} {(value or '').strip()}".lower().strip()
    if not raw:
        return None
    tokens = set(re.findall(r"[a-z]+", raw))
    if {"de", "german", "deutsch"} & tokens:
        return "de"
    if {"fr", "french", "francais"} & tokens:
        return "fr"
    if {"en", "english"} & tokens:
        return "en"
    return None


def _get_language_code_for_id_from_db(language_id: int | None) -> str | None:
    try:
        language_id_int = int(language_id)
    except (TypeError, ValueError):
        return None
    try:
        from reports.models.lookups import Language

        row = Language.objects.filter(id=language_id_int).values_list("value", "key").first()
    except Exception:
        return None
    if not row:
        return None
    value, key = row
    return _infer_language_code(value, key)


def _get_language_id_for_code_from_db(language_code: str | None) -> int | None:
    normalized_code = (language_code or "").strip().lower()
    if normalized_code not in SUPPORTED_LANGUAGE_CODES:
        return None
    try:
        from reports.models.lookups import Language

        languages = Language.objects.values_list("id", "value", "key")
    except Exception:
        return None
    for language_id, value, key in languages:
        if _infer_language_code(value, key) == normalized_code:
            try:
                return int(language_id)
            except (TypeError, ValueError):
                continue
    return None
