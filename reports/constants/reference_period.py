"""Shared reference period enum used by templates and generators."""

from enum import Enum


class ReferencePeriod(Enum):
    """Represents the various reference periods used for stories."""

    DAILY = 35
    MONTHLY = 36
    SEASONAL = 37
    YEARLY = 38
    ALLTIME = 39
    DECADAL = 44  # For backward compatibility
    IRREGULAR = 56  # For backward compatibility
    WEEKLY = 70  # For backward compatibility

    @classmethod
    def get_name(cls, value: int) -> str:
        """Look up the name for a stored reference period value."""
        for period in cls:
            if period.value == value:
                return period.name.lower()
        return "unknown"
