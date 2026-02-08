from datetime import date, timedelta


def default_yesterday():
    """Return yesterday's date."""
    return date.today() - timedelta(days=1)
