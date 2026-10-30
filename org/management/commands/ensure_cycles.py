import datetime

from django.core.management.base import BaseCommand, CommandError

from org.models import ReportingCycle


class Command(BaseCommand):
    help = "Create missing reporting cycles (fiscal years) as CLOSED, e.g. to back-fill history. " \
           "Existing cycles are left exactly as they are."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="first", type=int, required=True, help="First FY end year, e.g. 2020.")
        parser.add_argument("--to", dest="last", type=int, required=True, help="Last FY end year, e.g. 2026.")

    def handle(self, first, last, **opts):
        if first > last:
            raise CommandError("--from must not be after --to")
        for end_year in range(first, last + 1):
            cycle, created = ReportingCycle.objects.get_or_create(
                year=end_year,
                defaults={
                    "label": f"FY {end_year - 1}-{str(end_year)[-2:]}",
                    "starts_on": datetime.date(end_year - 1, 7, 1),
                    "ends_on": datetime.date(end_year, 6, 30),
                    "submission_deadline": datetime.date(end_year, 12, 15),
                    "status": ReportingCycle.Status.CLOSED,
                },
            )
            self.stdout.write(f"{cycle.label}: {'created (closed)' if created else f'exists ({cycle.status})'}")
