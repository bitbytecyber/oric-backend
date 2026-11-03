import csv

from django.core.management.base import BaseCommand

from submissions.grants import GRANT_CATEGORIES, normalize_grant_data
from submissions.models import Submission
from submissions.registry import FUNDING_AGENCIES, GRANT_SCHEMES
from submissions.services import resolve_organization


class Command(BaseCommand):
    help = "Move old free-text grant names / funding agencies onto the new dropdown values. Values that do not " \
           "clearly map stay as typed (shown as 'Others'). Dry run unless --apply; --csv lists what stays 'Others'."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--csv", dest="csv_path", help="Write the records left as 'Others' to this CSV for ORIC to review.")

    def handle(self, apply=False, csv_path=None, **opts):
        changed, others = 0, []
        for sub in Submission.objects.filter(category__in=GRANT_CATEGORIES).select_related("cycle").iterator():
            new = normalize_grant_data(sub.category, sub.data)
            if new != sub.data:
                changed += 1
                if apply:
                    sub.data = new
                    sub.organization = resolve_organization(new.get("funding_agency")) \
                        if new.get("funding_agency") else sub.organization
                    sub.save(update_fields=["data", "organization"])
            name, agency = new.get("research_grant_name") or "", new.get("funding_agency") or ""
            if (name and name not in GRANT_SCHEMES) or (agency and agency not in FUNDING_AGENCIES) or not agency:
                others.append([sub.pk, sub.cycle.label, sub.category, name, agency, sub.title])
        if csv_path:
            with open(csv_path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["id", "fiscal_year", "category", "grant_name", "funding_agency", "title"])
                w.writerows(others)
        self.stdout.write(self.style.SUCCESS(
            f"{changed} records {'updated' if apply else 'would change'}; "
            f"{len(others)} keep an 'Others' grant name or agency (or have no agency)"))
