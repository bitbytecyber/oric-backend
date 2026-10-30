from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from imports.models import ImportBatch
from org.models import ReportingCycle
from submissions.models import EvidenceFile, Submission


class Command(BaseCommand):
    help = "Delete every submission of one fiscal year (with contributors, files, history) and its import " \
           "batches, e.g. before replacing demo data with a workbook import."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Fiscal-year end, e.g. 2026 for FY 2025-26.")
        parser.add_argument("--dry-run", action="store_true", help="Only print what would be deleted.")
        parser.add_argument("--yes", action="store_true", help="Delete without asking (required when not a TTY).")

    def handle(self, year, dry_run, yes, **opts):
        cycle = ReportingCycle.objects.filter(year=year).first()
        if not cycle:
            raise CommandError(f"No reporting cycle for year {year}.")
        subs = Submission.objects.filter(cycle=cycle)
        by_source = Counter(subs.values_list("source", flat=True))
        demo = subs.filter(data__has_key="_demo").count()
        files = EvidenceFile.objects.filter(submission__in=subs)
        batches = ImportBatch.objects.filter(cycle=cycle)
        self.stdout.write(f"{cycle.label}: {subs.count()} submissions ({dict(by_source)}; {demo} demo), "
                          f"{files.count()} evidence files, {batches.count()} import batches.")
        if dry_run:
            self.stdout.write("Dry run, nothing deleted.")
            return
        if not yes and input(f"Delete all of this from {cycle.label}? Type the year ({year}) to confirm: ") != str(year):
            raise CommandError("Not confirmed, nothing deleted.")
        with transaction.atomic():
            paths = [f.file for f in files] + [b.file for b in batches if b.file]
            subs.delete()
            batches.delete()
        for f in paths:  # after the commit, so a failed transaction never loses files
            f.delete(save=False)
        self.stdout.write(self.style.WARNING(f"Cleared {cycle.label}."))
