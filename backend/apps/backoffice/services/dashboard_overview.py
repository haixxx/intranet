"""
Compatibility wrapper for the overview dashboard services.

The implementation is split by domain under apps.backoffice.services.dashboard:
- common.py
- work_summary.py
- device_summary.py
- alerts.py
- daily.py
- period.py
"""

from .dashboard import OverviewDailyService, OverviewPeriodService, parse_date

__all__ = [
    "OverviewDailyService",
    "OverviewPeriodService",
    "parse_date",
]
