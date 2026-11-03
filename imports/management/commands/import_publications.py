from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from imports.models import ImportBatch
from imports.services.publications import import_publications


class Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Import a journal-publications list (xlsx) as journal_article records. Papers already in the portal " \
           "(same DOI or title) are skipped, so re-running is safe."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--sheet", help="Sheet name (default: the first sheet).")
        parser.add_argument("--dry-run", action="store_true", help="Run everything, then roll back.")

    def handle(self, path, sheet=None, dry_run=False, **opts):
        stats = {}
        try:
            with transaction.atomic():
                batch = ImportBatch.objects.create(kind=ImportBatch.Kind.PUBLICATIONS, original_name=Path(path).name,
                                                   options={"sheet": sheet} if sheet else {})
                stats = import_publications(batch, path, sheet=sheet)
                self.stdout.write(batch.log)
                for row in batch.rows.exclude(status="created").order_by("id"):
                    self.stdout.write(f"  {row.ref:12} {row.status:9} {row.message[:40]:40} {row.person_text[:70]}")
                if dry_run:
                    raise Rollback
        except Rollback:
            self.stdout.write(self.style.WARNING("Dry run: rolled back."))
            return
        self.stdout.write(self.style.SUCCESS(f"Batch #{batch.pk}: {stats}"))
