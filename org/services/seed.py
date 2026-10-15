"""Idempotent reference-data seeders (update_or_create)."""
import datetime

from org.models import ReportingCycle


def seed_cycles(today: datetime.date | None = None) -> None:
    """FY runs 1 July – 30 June; returns are filed after year-end. The FY that ended most
    recently is OPEN, older ones CLOSED."""
    today = today or datetime.date.today()
    latest_end_year = today.year if today.month >= 7 else today.year - 1
    for end_year in range(latest_end_year - 2, latest_end_year + 1):
        status = ReportingCycle.Status.OPEN if end_year == latest_end_year else ReportingCycle.Status.CLOSED
        ReportingCycle.objects.update_or_create(
            year=end_year,
            defaults={
                "label": f"FY {end_year - 1}-{str(end_year)[-2:]}",
                "starts_on": datetime.date(end_year - 1, 7, 1),
                "ends_on": datetime.date(end_year, 6, 30),
                "submission_deadline": datetime.date(end_year, 12, 15),
                "status": status,
            },
        )
