"""Aggregations for dashboards and the ORIC scorecard (legacy ric_form_1_report / form3report)."""
from collections import defaultdict

from django.db.models import Count, Q

from org.models import ReportingCycle
from rbac.utils import capability_scope_q
from submissions.models import SectionEntry, Submission
from submissions.registry import PILLARS, section_count_fields

COUNTED_STATUSES = ("submitted", "under_review", "returned", "approved")


def scoped_submissions(user, key: str, *, year=None, department=None, pillar=None, statuses=None):
    qs = Submission.objects.all()
    q = capability_scope_q(user, key, department_field="department_id", pillar_field="pillar")
    if q is not None:
        qs = qs.filter(q)
    if year:
        qs = qs.filter(cycle__year=year)
    if department:
        qs = qs.filter(department_id=department)
    if pillar:
        qs = qs.filter(pillar=pillar)
    if statuses:
        qs = qs.filter(status__in=statuses)
    return qs


def scorecard_summary(user, *, year, department=None, pillar=None, approved_only=False):
    statuses = ("approved",) if approved_only else COUNTED_STATUSES
    subs = scoped_submissions(user, "report.view", year=year, department=department, pillar=pillar,
                              statuses=statuses)
    entries = SectionEntry.objects.filter(submission__in=subs.values("pk"))

    entry_counts = dict(entries.values("section").annotate(n=Count("id")).values_list("section", "n"))

    # declared totals from headers
    declared = defaultdict(int)
    for counts in subs.values_list("counts", flat=True):
        for k, v in (counts or {}).items():
            declared[k] += int(v or 0)

    pillars_out = []
    for p in PILLARS:
        if pillar and p["key"] != pillar:
            continue
        sections = []
        for s in p["sections"]:
            af = s.get("amount_field")
            total = _sum(entries, s["key"], af) if af else 0.0
            sections.append({
                "key": s["key"],
                "code": s["code"],
                "title": s["title"],
                "declared": sum(declared.get(f, 0) for f in section_count_fields(s)),
                "entries": entry_counts.get(s["key"], 0),
                "amount_field": af,
                "amount_total": round(total, 3) if af else None,
            })
        p_subs = subs.filter(pillar=p["key"])
        pillars_out.append({
            "key": p["key"],
            "name": p["name"],
            "submissions": p_subs.count(),
            "by_status": dict(p_subs.values("status").annotate(n=Count("id")).values_list("status", "n")),
            "sections": sections,
        })

    by_department = list(
        subs.values("department_id", "department__name")
        .annotate(
            submissions=Count("id", distinct=True),
            approved=Count("id", filter=Q(status="approved"), distinct=True),
            entries=Count("entries"),
        )
        .order_by("-entries")
    )
    funding = _funding_comparison(entries)
    return {
        "year": year,
        "approved_only": approved_only,
        "total_submissions": subs.count(),
        "faculty_count": subs.values("owner").distinct().count(),
        "pillars": pillars_out,
        "by_department": [
            {"department_id": d["department_id"], "department": d["department__name"],
             "submissions": d["submissions"], "approved": d["approved"], "entries": d["entries"]}
            for d in by_department
        ],
        "funding": funding,
    }


def _sum(entries, section, field):
    total = 0.0
    for data in entries.filter(section=section).values_list("data", flat=True):
        try:
            total += float(data.get(field) or 0)
        except (TypeError, ValueError):
            pass
    return round(total, 3)


def _funding_comparison(entries):
    """Requested → approved → released → utilized (PKR million), legacy 'Approved vs Utilized' chart."""
    return {
        "requested": _sum(entries, "A1", "total_funding_requested") + _sum(entries, "A2", "total_funding_requested")
        + _sum(entries, "A7", "total_funding_requested"),
        "approved": _sum(entries, "A3", "total_funding_approved") + _sum(entries, "A4", "total_funding_approved")
        + _sum(entries, "A8", "total_funding_approved") + _sum(entries, "A10", "total_amount_approved"),
        "released": _sum(entries, "A5", "total_funding_released") + _sum(entries, "A6", "total_funding_released")
        + _sum(entries, "A9", "total_funding_released"),
        "utilized": _sum(entries, "A5", "total_funding_utilized") + _sum(entries, "A6", "total_funding_utilized")
        + _sum(entries, "A9", "total_funding_utilized"),
    }


def yearly_trend(user, pillar=None):
    subs = scoped_submissions(user, "report.view", pillar=pillar, statuses=COUNTED_STATUSES)
    rows = subs.values("cycle__year").annotate(submissions=Count("id", distinct=True), entries=Count("entries"))
    return [{"year": r["cycle__year"], "submissions": r["submissions"], "entries": r["entries"]}
            for r in rows.order_by("cycle__year")]


def available_years():
    return list(ReportingCycle.objects.order_by("-year").values_list("year", flat=True))
