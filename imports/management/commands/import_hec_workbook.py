from django.core.management.base import BaseCommand, CommandError

from imports.models import ImportBatch
from imports.services.hec_workbook import import_workbook
from org.models import ReportingCycle


class Command(BaseCommand):
    help = "Import an HEC ORIC scorecard workbook (Index-A..D) into one fiscal year."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--year", type=int, required=True, help="Fiscal-year end, e.g. 2025 for FY 2024-25.")
        parser.add_argument("--keep", action="store_true", help="Do not delete earlier workbook imports of that year.")

    def handle(self, path, year, keep, **opts):
        cycle = ReportingCycle.objects.filter(year=year).first()
        if not cycle:
            raise CommandError(f"No reporting cycle for year {year}. Run seed_oric first.")
        batch = ImportBatch.objects.create(kind=ImportBatch.Kind.HEC_WORKBOOK, original_name=path.split("/")[-1],
                                           cycle=cycle, options={"replace": not keep})
        stats = import_workbook(batch, path, replace=not keep)
        self.stdout.write(batch.log)
        self.stdout.write(self.style.SUCCESS(
            f"Created {stats['created']} records, {stats['unmatched']} need matching (batch #{batch.pk})."))
