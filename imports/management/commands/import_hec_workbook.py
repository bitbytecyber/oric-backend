from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from imports.models import ImportBatch
from imports.services.hec_workbook import Book, detect_template, import_workbook, score_card_as_submitted
from org.models import ReportingCycle


class _DryRun(Exception):
    pass


class Command(BaseCommand):
    help = "Import an HEC ORIC scorecard workbook (any template: Annexure 2019-20, Index A-D 2020-21 onward) " \
           "into one fiscal year."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--year", type=int, required=True, help="Fiscal-year end, e.g. 2025 for FY 2024-25.")
        parser.add_argument("--keep", action="store_true", help="Do not delete earlier workbook imports of that year.")
        parser.add_argument("--dry-run", action="store_true", help="Run everything, print the report, roll back.")
        parser.add_argument("--only", nargs="+", metavar="TABLE",
                            help="Import only these tables (e.g. B.xi). Their earlier rows in the year are replaced.")
        parser.add_argument("--sheet", action="append", default=[], metavar="TABLE=SHEET",
                            help='Read a table from another sheet, e.g. --sheet "B.xi=Uploade PC".')
        parser.add_argument("--card-only", action="store_true",
                            help="Records untouched: only store this workbook's Score Card (\"as submitted to HEC\") "
                                 "on the year's latest full workbook import.")

    def handle(self, path, year, keep, dry_run, only, sheet, card_only, **opts):
        cycle = ReportingCycle.objects.filter(year=year).first()
        if not cycle:
            raise CommandError(f"No reporting cycle for year {year}. Run ensure_cycles first.")
        if card_only:
            return self._card_only(path, cycle, dry_run)
        overrides = {}
        for item in sheet:
            key, _, name = item.partition("=")
            if not name:
                raise CommandError(f"--sheet expects TABLE=SHEET, got {item!r}")
            overrides[key.strip()] = name.strip()
        try:
            with transaction.atomic():
                batch = ImportBatch.objects.create(
                    kind=ImportBatch.Kind.HEC_WORKBOOK, original_name=path.replace("\\", "/").split("/")[-1],
                    cycle=cycle, options={"replace": not keep, "only": only or [], "sheet_overrides": overrides})
                try:
                    stats = import_workbook(batch, path, replace=not keep, only=only, sheet_overrides=overrides)
                except ValueError as e:
                    raise CommandError(str(e)) from e
                self.stdout.write(batch.log)
                self.stdout.write(self.style.SUCCESS(
                    f"{'[dry run] ' if dry_run else ''}Created {stats['created']} records, {stats['unmatched']} need "
                    f"matching, {sum(stats['flags'].values())} flagged ({stats['template']}, batch #{batch.pk})."))
                if dry_run:
                    raise _DryRun
        except _DryRun:
            self.stdout.write("Rolled back.")

    def _card_only(self, path, cycle, dry_run):
        batch = (ImportBatch.objects.filter(cycle=cycle, kind=ImportBatch.Kind.HEC_WORKBOOK,
                                            status=ImportBatch.Status.APPLIED)
                 .exclude(stats__has_key="only").order_by("-created_at").first())
        if not batch:
            raise CommandError(f"{cycle.label} has no workbook import to attach the Score Card to.")
        try:
            wb = Book(path)
            template = detect_template(wb)
        except ValueError as e:
            raise CommandError(str(e)) from e
        card = score_card_as_submitted(wb, template)
        self.stdout.write(f"{cycle.label}, batch #{batch.pk}: {template}, Score Card "
                          f"{card.get('reported_fy') or 'without a reported FY'}, self {card.get('total', {}).get('self')}")
        if dry_run:
            self.stdout.write("Dry run, nothing stored.")
            return
        batch.stats = {**batch.stats, "as_submitted": card, "template": template}
        batch.save(update_fields=["stats"])
        self.stdout.write(self.style.SUCCESS("Stored."))
