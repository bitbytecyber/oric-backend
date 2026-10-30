import datetime
import re

from dateutil import parser as dateparser
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from imports.models import ImportBatch, ImportRow
from imports.services import normalize


def _prep(v) -> tuple[str, str]:
    s = str(v).strip()
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s, flags=re.I)
    s = re.sub(r"\bsept\b", "sep", s, flags=re.I)
    s = s.replace(",", ", ").replace("  ", " ")
    return s, re.split(r"\s+(?:to|till|until|-|–)\s+", s)[0].strip(" ,")


def _reaches_fallback(v) -> bool:
    """True when to_date gets past its exact formats to the fuzzy parse (the only path whose result changed)."""
    s, first = _prep(v)
    for cand in (s, first):
        for fmt in normalize.DATE_FORMATS:
            try:
                datetime.datetime.strptime(cand.strip(" ,"), fmt)
                return False
            except ValueError:
                pass
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        y = int(m.group(3))
        try:
            datetime.date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
            return False
        except ValueError:
            pass
    return True


def _legacy_fuzzy(v) -> str | None:
    """What to_date returned before the 'year written in the cell wins' fix ('30–31 July 2024' -> 2030-07-31)."""
    _, first = _prep(v)
    if not re.search(r"\d{4}", first):
        return None
    try:
        return dateparser.parse(first, dayfirst=True, fuzzy=True,
                                default=datetime.datetime(2000, 1, 1)).date().isoformat()
    except Exception:  # noqa: BLE001
        return None


class Command(BaseCommand):
    help = ("Re-date records of earlier workbook imports whose dates the old fuzzy parser mis-yeared "
            "('30–31 July 2024' stored as 2030-07-31). Prints every change; --apply writes them.")

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, nargs="+", help="Import batch ids (default: every applied batch).")
        parser.add_argument("--apply", action="store_true", help="Write the changes (default: report only).")

    def handle(self, batch, apply, **opts):
        batches = ImportBatch.objects.filter(status=ImportBatch.Status.APPLIED)
        if batch:
            batches = batches.filter(pk__in=batch)
            if batches.count() != len(set(batch)):
                raise CommandError("Unknown or not applied batch id(s).")
        changed = 0
        with transaction.atomic():
            rows = ImportRow.objects.filter(batch__in=batches).select_related("submission", "batch__cycle")
            for r in rows.iterator():
                swaps = {}
                for v in r.raw.values():
                    if isinstance(v, str) and re.search(r"\d{4}", v) and _reaches_fallback(v):
                        old, new = _legacy_fuzzy(v), normalize.to_date(v)
                        if old and new and new != old:
                            swaps[old] = new
                hit = {k: x for k, x in r.parsed.items() if isinstance(x, str) and x in swaps}
                if not hit:
                    continue
                changed += 1
                for k, x in hit.items():
                    self.stdout.write(f"{r.batch.cycle.label} #{r.batch_id} {r.ref} {k}: {x} -> {swaps[x]}")
                    r.parsed[k] = swaps[x]
                if not apply:
                    continue
                r.save(update_fields=["parsed"])
                s = r.submission
                if s:
                    for k, x in list(s.data.items()):
                        if isinstance(x, str) and x in swaps:
                            s.data[k] = swaps[x]
                    s.promote()
                    s.save()
        verb = "Re-dated" if apply else "Would re-date"
        self.stdout.write(self.style.SUCCESS(f"{verb} {changed} rows." + ("" if apply else " Run with --apply.")))
