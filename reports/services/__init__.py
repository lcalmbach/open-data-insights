"""
ETL Services Package
Provides Django-integrated ETL services for data synchronization, story generation, and email delivery

Imports are lazy (PEP 562). Eagerly importing every service here meant that touching
any one of them — even `from reports.services.database_client import ...` in a view —
pulled in pandas, pyarrow, matplotlib, wordcloud and the LLM SDKs: ~130 MB of libraries
a web worker never uses to serve a stored page. `from reports.services import X` still
works exactly as before; the module is only loaded when the name is first accessed.
"""

import importlib

_LAZY_EXPORTS = {
    "ETLBaseService": ".base",
    "DatasetSyncService": ".dataset_sync",
    "StoryGenerationService": ".story_generation",
    "EmailService": ".email_service",
    "StorySubscriptionService": ".story_subscription_service",
    "PressReviewHarvestService": ".press_review_service",
    "PressReviewMailer": ".press_review_service",
    "PressReviewRelevanceService": ".press_review_service",
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_path, __name__), name)
    globals()[name] = value  # cache so later lookups skip __getattr__
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
