"""Shared helpers for the traffic-usage retention tiers.

Kept dependency-free (stdlib only) so it can be imported from both the
aggregation task and the read-path CRUD without risking import cycles.
"""

from datetime import date as _date, timedelta

# Fixed anchor for bi-weekly buckets. 2024-01-01 is a Monday, so every
# bucket starts on a Monday and boundaries are stable across runs
# regardless of when aggregation executes or what range is queried.
BIWEEK_ANCHOR = _date(2024, 1, 1)
BIWEEK_DAYS = 14


def biweek_start(d: _date) -> _date:
    """Return the start date of the fixed 2-week bucket containing ``d``."""
    delta_days = (d - BIWEEK_ANCHOR).days
    # Floor division handles dates before the anchor correctly too.
    return BIWEEK_ANCHOR + timedelta(days=BIWEEK_DAYS * (delta_days // BIWEEK_DAYS))
