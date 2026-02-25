from __future__ import annotations

from django.http import HttpResponseRedirect
from django.urls import get_script_prefix, set_script_prefix

from reports.language import (
    get_content_language_id,
    get_language_code_for_id,
    get_language_id_for_code,
    set_content_language_id,
    split_language_prefix,
    with_language_prefix,
)

EXEMPT_PATH_PREFIXES = ("/admin/", "/static/", "/media/", "/accounts/")
EXEMPT_EXACT_PATHS = ("/favicon.ico", "/robots.txt")


class LanguagePrefixMiddleware:
    """
    Make language part of URL path (/en, /de, /fr) and keep it in sync with
    content-language session state.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info or "/"
        if self._is_exempt(path):
            return self.get_response(request)

        language_code, stripped_path = split_language_prefix(path)
        if language_code is None:
            target_code = get_language_code_for_id(get_content_language_id(request))
            target_path = with_language_prefix(path, target_code)
            query = request.META.get("QUERY_STRING", "")
            if query:
                target_path = f"{target_path}?{query}"
            return HttpResponseRedirect(target_path)

        target_language_id = get_language_id_for_code(language_code)
        if get_content_language_id(request) != target_language_id:
            set_content_language_id(request, target_language_id)

        original_script_prefix = get_script_prefix()
        request.path_info = stripped_path
        request.META["PATH_INFO"] = stripped_path
        set_script_prefix(f"/{language_code}/")
        try:
            return self.get_response(request)
        finally:
            set_script_prefix(original_script_prefix)

    @staticmethod
    def _is_exempt(path: str) -> bool:
        if path in EXEMPT_EXACT_PATHS:
            return True
        for prefix in EXEMPT_PATH_PREFIXES:
            bare = prefix.rstrip("/")
            if path == bare or path.startswith(prefix):
                return True
        return False
