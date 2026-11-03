from django.core.management.base import BaseCommand

from org.models import ReportingCycle
from submissions.irb import merge_irb_reviews


class Command(BaseCommand):
    help = "Fold stand-alone 'Proposal reviewed by IRB' records into their proposals (Reviewed by IRB = Yes). " \
           "Dry run unless --apply; unmatched records are listed and left as they are."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, help="Only this fiscal year (FY end year, e.g. 2025).")
        parser.add_argument("--apply", action="store_true", help="Write the changes (default: report only).")

    def handle(self, year=None, apply=False, **opts):
        cycle = ReportingCycle.objects.get(year=year) if year else None
        report = merge_irb_reviews(cycle=cycle, apply=apply)
        for r in report["matched"]:
            self.stdout.write(f"MATCH  {r['cycle']}  irb #{r['irb']} -> proposal #{r['proposal']}  {r['title'][:70]}")
        for r in report["unmatched"]:
            self.stdout.write(f"KEEP   {r['cycle']}  irb #{r['irb']} (no matching proposal)  {r['title'][:70]}")
        self.stdout.write(self.style.SUCCESS(
            f"{len(report['matched'])} matched, {len(report['unmatched'])} kept as legacy records"
            + ("" if apply else " (dry run: nothing written)")))
