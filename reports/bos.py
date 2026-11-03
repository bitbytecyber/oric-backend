"""Annex-A "Research Performance of Academic Departments": the yearly summary each department discusses in its
4th BOS meeting and sends to ORIC, computed from the records already in the portal.

Every Annex-A line is one ``Item``: which categories it counts, how (number of records, sum of the record amount,
or sum of a numeric answer), and any extra filter. Lines the portal does not record are listed with ``None``
categories and reported as "not tracked" rather than as zero.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from django.db.models import Q, Sum
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from submissions.models import Submission
from submissions.registry import CATEGORY_BY_KEY

SubmissionDepartment = Submission.departments.through

SUBMITTED = ["grant_hec_submitted", "grant_nonhec_submitted", "joint_submitted"]
APPROVED = ["grant_hec_approved", "grant_nonhec_approved", "joint_approved"]
COMPLETED = ["grant_hec_completed", "grant_nonhec_completed", "joint_completed"]
PAPERS = ["journal_article", "publication"]


@dataclass
class Item:
    no: str
    label: str
    categories: list[str] | None = None
    metric: str = "count"  # count | amount | data:<field> (sum of a numeric answer)
    filters: dict = field(default_factory=dict)
    due: bool = False  # approved projects (any year) whose end date falls in this fiscal year
    heading: bool = False


def hjrs(cat: str) -> Q:
    return Q(category="journal_article", data__hjrs_category=cat) | Q(category="publication",
                                                                      data__publication_category=cat)


ANNEX_A = [
    Item("1", "Research projects from HEC / non-HEC / joint sources (national / international funding agencies)",
         heading=True),
    Item("1(a)(i)", "Research projects submitted", SUBMITTED),
    Item("1(a)(ii)", "Research projects approved", APPROVED),
    Item("1(a)(iii)", "Research projects due to be completed", APPROVED, due=True),
    Item("1(a)(iv)", "Research projects completed", COMPLETED),
    Item("1(b)", "Contract research awarded by industry or government organizations", ["contract_research"]),
    Item("2", "Volume of R&D funding secured (PKR)", heading=True),
    Item("2(a)", "From national / international sources (approved projects)", APPROVED, metric="amount"),
    Item("2(b)", "Contract research awarded by industry or government organizations", ["contract_research"],
         metric="amount"),
    Item("3", "Number of", heading=True),
    Item("3(a)", "Policy advocacy or case studies presented to government departments", ["policy_advocacy"]),
    Item("3(b)", "Research links established with other HEIs / corporate sector / industry / community",
         ["research_link"]),
    Item("3(c)", "Civic engagement events / initiatives on issues of public concern", ["civic_engagement"]),
    Item("4", "Consultancy", heading=True),
    Item("4(a)", "Consultancy opportunities identified and circulated to faculty / researchers",
         ["consultancy_opportunity"]),
    Item("4(b)", "Consultancy contracts executed through ORIC", ["consultancy_contract"]),
    Item("5", "Intellectual property", heading=True),
    Item("5(a)", "IP disclosures made", ["ip_disclosure"]),
    Item("5(b)(i)", "Patents / trademarks / designs / copyrights filed", ["patent"],
         filters={"data__filed_or_granted": "Filed"}),
    Item("5(b)(ii)", "Patents / trademarks / designs / copyrights granted", ["patent"],
         filters={"data__filed_or_granted": "Granted"}),
    Item("5(c)(i)", "IP licensing negotiations initiated", ["licensing_negotiation"]),
    Item("5(c)(ii)", "Non-exclusive or exclusive licenses signed", ["license_signed"]),
    Item("5(d)", "Research products / processes / prototypes in prefeasibility or industrial-scale testing",
         ["prototype"]),
    Item("5(e)", "Science / arts products or creative activity displayed", ["creative_product"]),
    Item("6", "Industry and community", heading=True),
    Item("6(a)", "Visits by industry or community representatives about potential research subjects",
         ["industry_visit"]),
    Item("6(b)", "Collaboration agreements signed with industry, government or community",
         ["collaboration_agreement"]),
    Item("7", "National / international honours or awards won (research, innovation & commercialization)",
         ["award"]),
    Item("8", "Trainings / workshops / seminars / conferences on research, innovation & commercialization",
         heading=True),
    Item("8(a)", "Arranged by the department (with ORIC)", ["training_oric"]),
    Item("8(b)", "Arranged by other HEIs / entities", ["training_external"]),
    Item("9", "Startups", heading=True),
    Item("9(a)", "Faculty startups encouraged / created", ["startup"]),
    Item("9(b)", "Faculty startups as spin-offs", ["spinoff"]),
    Item("9(c)", "Student / alumni startups created"),
    Item("10", "Jobs and placements", heading=True),
    Item("10(a)", "Jobs created and retained over 2 years of faculty startup founding", ["startup"],
         metric="data:jobs_created"),
    Item("10(b)", "Jobs created and retained over 2 years of student / alumni-led startup founding"),
    Item("10(c)", "Students placed in faculty startups or spin-offs (internships, trainees)", ["startup"],
         metric="data:internships_created"),
    Item("10(d)", "Students placed in student / alumni startups"),
    Item("11", "Startup revenue and funding (PKR)", heading=True),
    Item("11(a)", "Startup revenue earned by student / alumni startups"),
    Item("11(b)", "Startup revenue earned by faculty startups", ["startup", "spinoff"], metric="amount"),
    Item("11(c)", "Funding secured for faculty / student / alumni startups", ["startup_funding"], metric="amount"),
    Item("11(d)", "Venture capital / angel investment / seed funding secured by startups", ["startup_funding"],
         metric="amount", filters={"data__funding_type__in": ["Pre-seed", "Seed", "Angel investment", "VC"]}),
    Item("11(e)", "Grant funds raised by student / alumni / faculty startups"),
    Item("12", "Participation of faculty / students in entrepreneurship / commercialization / innovation trainings",
         ["entrepreneurship_event"]),
    Item("13", "Participation in such trainings arranged by other BICs / HEIs / NICs"),
    Item("14", "Number of 'W' category papers according to HJRS", PAPERS, filters={"_q": hjrs("W")}),
    Item("15", "Number of 'X' category papers according to HJRS", PAPERS, filters={"_q": hjrs("X")}),
    Item("16", "Number of 'Y' category papers according to HJRS", PAPERS, filters={"_q": hjrs("Y")}),
]


def department_records(qs, department_id: int):
    links = SubmissionDepartment.objects.filter(department_id=department_id).values("submission_id")
    return qs.filter(Q(department_id=department_id) | Q(pk__in=links))


def _apply(qs, item: Item):
    qs = qs.filter(category__in=item.categories)
    for k, v in item.filters.items():
        qs = qs.filter(v) if k == "_q" else qs.filter(**{k: v})
    return qs


def _value(qs, item: Item):
    if item.metric == "count":
        return qs.count()
    if item.metric == "amount":
        return float(qs.aggregate(v=Sum("amount_pkr"))["v"] or 0)
    key = item.metric.split(":", 1)[1]
    total = 0.0
    for v in qs.values_list(f"data__{key}", flat=True):
        try:
            total += float(v or 0)
        except (TypeError, ValueError):
            continue
    return total


def compute(visible, department, cycle, *, include_pending=False) -> dict:
    """``visible`` = the submissions the user may see (already scoped by RBAC)."""
    statuses = [Submission.Status.VERIFIED, Submission.Status.SUBMITTED] if include_pending \
        else [Submission.Status.VERIFIED]
    dept_all = department_records(visible.filter(status__in=statuses), department.pk)
    in_year = dept_all.filter(cycle=cycle)
    rows = []
    for item in ANNEX_A:
        row = {"no": item.no, "label": item.label, "heading": item.heading, "metric": item.metric,
               "tracked": bool(item.categories) or item.heading, "value": None, "records": []}
        if item.categories:
            if item.due:
                qs = _apply(dept_all, item).filter(data__end_date__gte=cycle.starts_on.isoformat(),
                                                   data__end_date__lte=cycle.ends_on.isoformat())
            else:
                qs = _apply(in_year, item)
            row["value"] = _value(qs, item)
            row["records"] = list(qs.order_by("event_date", "pk").values_list("pk", flat=True))
        rows.append(row)
    return {"department": {"id": department.pk, "code": department.code, "name": department.name},
            "cycle": {"id": cycle.pk, "label": cycle.label, "starts_on": cycle.starts_on, "ends_on": cycle.ends_on},
            "include_pending": include_pending, "rows": rows}


HEAD = PatternFill("solid", fgColor="0F6E78")
SOFT = PatternFill("solid", fgColor="E6F1F2")


def workbook(report: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Annex-A"
    d, c = report["department"], report["cycle"]
    ws.append(["Annex-A: Research Performance of Academic Departments"])
    ws.append([f"{d['name']} ({d['code']}) · {c['label']} ({c['starts_on']:%d %b %Y} – {c['ends_on']:%d %b %Y})"])
    ws.append(["Verified and pending records" if report["include_pending"] else "Verified records only"])
    ws.append([])
    ws.append(["S.No", "Details", "Value"])
    for cell in ws[5]:
        cell.fill, cell.font = HEAD, Font(bold=True, color="FFFFFF")
    ws["A1"].font = Font(bold=True, size=13)
    for r in report["rows"]:
        value = "" if r["heading"] else ("Not tracked in the portal" if not r["tracked"] else r["value"])
        ws.append([r["no"], r["label"], value])
        if r["heading"]:
            for cell in ws[ws.max_row]:
                cell.fill, cell.font = SOFT, Font(bold=True)
        elif r["metric"] != "count" and isinstance(value, float):
            ws.cell(row=ws.max_row, column=3).number_format = "#,##0"
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 90
    ws.column_dimensions["C"].width = 22
    for row in ws.iter_rows(min_row=6):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    ids = {pk for r in report["rows"] for pk in r["records"]}
    subs = {s.pk: s for s in Submission.objects.filter(pk__in=ids).select_related("owner", "cycle")}
    ls = wb.create_sheet("Records")
    ls.append(["S.No (Annex-A)", "Category", "Title", "Lead", "Date", "Amount (PKR)", "Status", "Portal ID"])
    for cell in ls[1]:
        cell.fill, cell.font = HEAD, Font(bold=True, color="FFFFFF")
    for r in report["rows"]:
        for pk in r["records"]:
            s = subs[pk]
            ls.append([r["no"], CATEGORY_BY_KEY[s.category]["short"], s.title, s.owner.full_name if s.owner else "",
                       s.event_date, float(s.amount_pkr) if s.amount_pkr is not None else None,
                       s.get_status_display(), s.pk])
    for i, w in enumerate([14, 28, 70, 28, 12, 16, 12, 10], start=1):
        ls.column_dimensions[get_column_letter(i)].width = w
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
