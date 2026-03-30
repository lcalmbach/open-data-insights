from datetime import date, timedelta


TIME_FREQUENCY_CHOICES = (
    ("day", "Day"),
    ("month", "Month"),
    ("season", "Season"),
    ("year", "Year"),
)

_TIME_FREQUENCY_ALIASES = {
    "day": "day",
    "daily": "day",
    "month": "month",
    "monthly": "month",
    "season": "season",
    "seasonal": "season",
    "year": "year",
    "yearly": "year",
    "annual": "year",
    "annually": "year",
}


def default_yesterday():
    """Return yesterday's date."""
    return date.today() - timedelta(days=1)


def normalize_time_frequency(value):
    """Map period labels like Daily/Monthly to canonical filter keys."""
    return _TIME_FREQUENCY_ALIASES.get((value or "").strip().lower())


def get_matching_reference_period_ids(value):
    """Resolve a canonical or raw period filter value to matching Period ids."""
    raw_value = (value or "").strip()
    if not raw_value:
        return []
    if raw_value.isdigit():
        return [int(raw_value)]

    normalized = normalize_time_frequency(raw_value)
    if not normalized:
        return []

    from .models.lookups import Period

    return [
        period.id
        for period in Period.objects.all()
        if normalize_time_frequency(period.value) == normalized
    ]
