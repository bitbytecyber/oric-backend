import json
from pathlib import Path

from django.core.management.base import BaseCommand

from org.services.directory import SEED_DIR, import_directory, read_seed_dir


class Command(BaseCommand):
    help = "Upsert faculties, departments, people and ORIC staff from org/seed/*.csv (or --dir)."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(SEED_DIR))
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--password", default=None, help="Initial password for new accounts.")

    def handle(self, dir, dry_run, password, **opts):
        files = read_seed_dir(Path(dir))
        if not files:
            self.stderr.write(f"No CSVs found in {dir}")
            return
        result = import_directory(files, dry_run=dry_run, password=password)
        for k, v in result.items():
            if isinstance(v, dict) and "created" in v:
                self.stdout.write(f"{k:12} created {v['created']:4}  updated {len(v.get('updated_items', [])) if 'updated_items' in v else v.get('updated', 0):4}  "
                                  f"unchanged {v.get('unchanged', 0):4}  errors {len(v.get('errors', []))}")
                for e in v.get("errors", [])[:20]:
                    self.stdout.write(self.style.WARNING(f"   {e}"))
        self.stdout.write(f"photos       attached {result.get('photos', {}).get('attached', 0)}")
        self.stdout.write(json.dumps(result.get("roles"), default=str))
        self.stdout.write(self.style.SUCCESS("Dry run - nothing saved." if dry_run else "Directory imported."))
