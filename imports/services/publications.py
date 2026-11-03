"""Import a journal-publications list (e.g. the HEC REF "Q1 Journal Publications" sheet) as ``journal_article``
records.

* The header row is found by its column titles; the last header row wins (the sheet repeats one above a worked
  example). Rows without a title and authors (blank lines, the Q1/Q2/Q3 summary block) are skipped.
* Papers already in the portal (same DOI, or same title) are skipped, so re-running the file adds nothing.
* Authors are matched to NED people (``AuthorMatcher``). Every matched author is linked; the first one owns the
  record. Papers with no matched author, or with an author that fits several people, go to the review queue.
* Records are created as *submitted*: ORIC still verifies the SJR / JCR categories.
"""
from __future__ import annotations

import datetime
import hashlib
import re

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from imports.models import ImportBatch, ImportRow
from org.models import ReportingCycle
from submissions.models import Contributor, ReviewEvent, Submission

from .normalize import AuthorMatcher, split_authors, text, to_date

CATEGORY = "journal_article"
COLUMNS = [
    ("sno", r"^s\.?\s*no"), ("sjr", r"^sjr"), ("jcr", r"clarivate|\bjcr\b"), ("authors", r"^authors?"),
    ("title", r"^title"), ("journal", r"^journal"), ("doi", r"^doi"), ("url", r"^url|^link"),
    ("abstract", r"abstract|context statement"), ("date", r"year of publication|date on e-print|publication date"),
    ("impact", r"research impact"), ("hjrs", r"\bhjrs\b"),
]
QUARTILE_RE = re.compile(r"\bQ\s*([1-4])", re.I)
DOI_RE = re.compile(r"10\.\d{4,9}/\S+")


def norm_doi(v) -> str:
    s = re.sub(r"\s+", "", str(v or "")).lower()
    m = DOI_RE.search(s)
    return m.group(0).rstrip(".,;") if m else ""


def norm_title(v) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(v or "").lower()).split())


def paper_key(doi: str, title: str) -> str:
    return f"doi:{doi}" if doi else "title:" + hashlib.sha1(norm_title(title).encode()).hexdigest()[:16]


def quartile(v) -> str | None:
    m = QUARTILE_RE.search(str(v or ""))
    return f"Q{m.group(1)}" if m else None


def pub_date(v) -> tuple[str | None, str]:
    """-> (ISO date, precision day / month / year). A bare year counts as 1 January (FY ending that year)."""
    if v is None or str(v).strip() == "":
        return None, ""
    if isinstance(v, (datetime.date, datetime.datetime)):
        return to_date(v), "day"
    if isinstance(v, (int, float)):
        n = int(v)
        if 1950 <= n <= 2100:
            return datetime.date(n, 1, 1).isoformat(), "year"
        return to_date(n), "day"
    s = str(v).strip().replace("+", " ").strip(" ,.")
    if re.fullmatch(r"\d{4}", s):
        return datetime.date(int(s), 1, 1).isoformat(), "year"
    m = re.match(r"(\d{5})\s*[.,]\s*\d{4}$", s)  # "45477. 2024": an Excel serial typed next to its year
    if m:
        return to_date(int(m.group(1))), "day"
    m = re.fullmatch(r"(\d{4})\s*[,/]?\s*([A-Za-z]+)", s) or re.fullmatch(r"([A-Za-z]+)\s*,?\s*(\d{4})", s)
    if m:
        d = to_date(f"1 {m.group(2) if m.group(1).isdigit() else m.group(1)} "
                    f"{m.group(1) if m.group(1).isdigit() else m.group(2)}")
        if d:
            return d, "month"
    m = re.match(r"(\d{4})\s*/\s*(.+)$", s)  # "2024/ 1 May"
    if m:
        s = f"{m.group(2)} {m.group(1)}"
    d = to_date(s)
    if d:
        return d, "day"
    m = re.search(r"(?<!\d)(19[5-9]\d|20\d\d)\s*$", s)  # unreadable text that still ends in a year
    return (datetime.date(int(m.group(1)), 1, 1).isoformat(), "year") if m else (None, "")


def find_header(ws) -> tuple[int, dict[str, int]]:
    best_row, best = 0, {}
    for r, row in enumerate(ws.iter_rows(min_row=1, max_row=40, values_only=True), start=1):
        cols = {}
        for i, cell in enumerate(row):
            label = " ".join(str(cell or "").split()).lower()
            for key, rx in COLUMNS:
                if label and key not in cols and re.search(rx, label):
                    cols[key] = i
                    break
        if {"title", "authors"} <= cols.keys() and len(cols) >= 5:
            best_row, best = r, cols
    if not best:
        raise ValueError("No header row with Title and Authors columns found.")
    return best_row, best


def existing_keys() -> set[str]:
    keys = set()
    for d in Submission.objects.filter(category=CATEGORY).values_list("data", flat=True):
        if d.get("doi") and norm_doi(d["doi"]):
            keys.add(f"doi:{norm_doi(d['doi'])}")
        keys.add(paper_key("", d.get("title") or ""))
    return keys


def import_publications(batch: ImportBatch, path: str, *, user=None, sheet: str | None = None) -> dict:
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    header, cols = find_header(ws)
    matcher = AuthorMatcher()
    seen = existing_keys()
    sheet_rows: dict[str, int] = {}
    stats = {"created": 0, "duplicates": 0, "unmatched": 0, "review": 0, "no_cycle": 0, "authors_linked": 0,
             "skipped_rows": 0, "errors": 0}
    log: list[str] = [f"Header on row {header}: {', '.join(sorted(cols))}"]
    now = timezone.now()

    with transaction.atomic():
        for r, row in enumerate(ws.iter_rows(min_row=header + 1, values_only=True), start=header + 1):
            def cell(key):
                i = cols.get(key)
                return row[i] if i is not None and i < len(row) else None

            title, authors = text(cell("title")), text(cell("authors"))
            if authors and re.fullmatch(r"[\d.\s]+", authors):
                authors = None  # a stray number in the authors column
            ref = f"{ws.title}!{r}"
            raw = {k: (str(cell(k)) if cell(k) is not None else None) for k in cols}
            if not title:
                if any(v not in (None, "") for v in row):
                    stats["skipped_rows"] += 1
                continue
            if not authors:
                stats["errors"] += 1
                ImportRow.objects.create(batch=batch, ref=ref, table="PUB", category=CATEGORY,
                                         status=ImportRow.Status.ERROR, raw=raw, message="No authors given")
                continue
            doi = norm_doi(cell("doi")) or norm_doi(cell("url"))
            key = paper_key(doi, title)
            if key in seen or paper_key("", title) in seen:
                again = sheet_rows.get(key) or sheet_rows.get(paper_key("", title))
                stats["duplicates"] += 1
                ImportRow.objects.create(batch=batch, ref=ref, table="PUB", category=CATEGORY,
                                         status=ImportRow.Status.SKIPPED, raw=raw,
                                         message=f"Same paper as row {again}" if again else "Already in the portal")
                continue
            seen.update({key, paper_key("", title)})
            sheet_rows.update({key: r, paper_key("", title): r})

            date, precision = pub_date(cell("date"))
            cycle = ReportingCycle.for_date(datetime.date.fromisoformat(date)) if date else None
            flags = []
            if precision == "year":
                flags.append("only the year is known: counted in the fiscal year ending that year")
            if not date:
                flags.append("publication date not readable")
            if cycle is None:
                stats["no_cycle"] += 1
                ImportRow.objects.create(batch=batch, ref=ref, table="PUB", category=CATEGORY,
                                         status=ImportRow.Status.ERROR, raw=raw,
                                         message=f"No fiscal year for date {date or cell('date')!r}")
                continue

            jcr_text = text(cell("jcr")) or ""
            data = {
                "title": title[:500], "journal_name": text(cell("journal")) or "", "authors_text": authors,
                "publication_date": date, "date_precision": precision, "doi": doi or (text(cell("doi")) or ""),
                "url": text(cell("url")) or "", "sjr_quartile": quartile(cell("sjr")),
                "jcr_quartile": quartile(jcr_text), "jcr_subject": " ".join(jcr_text.split())[:300],
                "context_statement": text(cell("abstract")) or "", "research_impact": text(cell("impact")) or "",
                "_source": raw,
            }
            hjrs = (text(cell("hjrs")) or "").strip().upper()[:1]
            if hjrs in ("W", "X", "Y"):
                data["hjrs_category"] = hjrs
            if data["research_impact"] and re.fullmatch(r"[\d.]+", data["research_impact"]):
                data["research_impact"] = ""  # a stray number in the impact column
            data = {k: v for k, v in data.items() if v not in (None, "")}

            linked, ambiguous, external = [], [], []
            for name in split_authors(authors):
                person, sugg, how = matcher.match(name)
                if person and person.pk not in {p.pk for p, _ in linked}:
                    linked.append((person, how))
                elif how == "ambiguous":
                    ambiguous.append({"name": name, "suggestions": sugg})
                elif not person:
                    external.append(name)
            data["_authors"] = {"linked": [{"person_id": p.pk, "name": p.full_name, "how": how} for p, how in linked],
                                "ambiguous": ambiguous, "external": external}
            if flags:
                data["_flags"] = flags

            owner = linked[0][0] if linked else None
            sub = Submission(category=CATEGORY, cycle=cycle, owner=owner, submitted_by=user, data=data,
                             status=Submission.Status.SUBMITTED, source=Submission.Source.EXCEL, import_batch=batch,
                             import_ref=key[:60], needs_match=not linked, submitted_at=now)
            if owner and owner.department_id:
                sub.department = owner.department
                sub.faculty = owner.department.faculty
            sub.promote()
            sub.save()
            Contributor.objects.bulk_create([
                Contributor(submission=sub, role="author" if i == 0 else "co_author", person=p, order=i)
                for i, (p, _) in enumerate(linked)
            ])
            sub.sync_departments()
            ReviewEvent.objects.create(submission=sub, actor=user, action=ReviewEvent.Action.IMPORT,
                                       to_status=sub.status, comment=f"Imported from {batch.original_name}")
            stats["created"] += 1
            stats["authors_linked"] += len(linked)

            needs_review = not linked or ambiguous
            status = ImportRow.Status.UNMATCHED if needs_review else ImportRow.Status.CREATED
            if not linked:
                stats["unmatched"] += 1
                person_text = "; ".join(a["name"] for a in ambiguous) or authors
            elif ambiguous:
                stats["review"] += 1
                person_text = "; ".join(a["name"] for a in ambiguous)
            else:
                person_text = ""
            sugg = [s for a in ambiguous for s in a["suggestions"]][:8]
            ImportRow.objects.create(batch=batch, ref=ref, table="PUB", category=CATEGORY, status=status, raw=raw,
                                     parsed={k: v for k, v in data.items() if k != "_source"},
                                     person_text=person_text[:500], suggestions=sugg, submission=sub,
                                     message=("Some authors fit more than one person" if ambiguous else
                                              "No NED author recognised" if not linked else ""))

    log.append(f"{stats['created']} papers created, {stats['duplicates']} duplicates (repeated in the sheet or "
               f"already in the portal), {stats['unmatched']} without a matched NED author "
               f"({stats['review']} more with authors to confirm), {stats['no_cycle']} without a fiscal year, "
               f"{stats['errors']} without authors")
    batch.stats = stats
    batch.log = "\n".join(log)
    batch.status = ImportBatch.Status.APPLIED
    batch.save()
    return stats

