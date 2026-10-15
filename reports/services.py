"""Aggregations behind Home, Explore (drill-down) and Reports. Always scoped to what the user may see."""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from org.models import Department, Faculty, ReportingCycle
from people.models import Person
from rbac.utils import capability_scopes
from submissions.access import own_q, visible_submissions
from submissions.models import Contributor, Submission
from submissions.registry import CATEGORY_BY_KEY, PILLARS

S = Submission.Status
SubmissionDepartment = Submission.departments.through

# Categories whose amount is "money brought in" (funding volume tiles).
FUNDING_CATEGORIES = ["grant_hec_approved", "grant_nonhec_approved", "joint_approved", "contract_research",
                      "consultancy_contract"]
GRANT_CATEGORIES = [k for k in CATEGORY_BY_KEY if k.startswith(("grant_hec", "grant_nonhec", "joint_"))]
IP_CATEGORIES = ["ip_disclosure", "patent", "licensing_negotiation", "license_signed"]
COUNTED_STATUSES = [S.SUBMITTED, S.VERIFIED]


def _f(v) -> float:
    return float(v or 0)


def parse_cycles(params) -> list[int]:
    raw = params.get("cycle") or params.get("cycles") or ""
    if str(raw) in ("0", "all"):
        return []
    ids = [int(x) for x in str(raw).split(",") if x.strip().isdigit()]
    if ids:
        return ids
    cur = ReportingCycle.current()
    return [cur.pk] if cur else []


def scoped(user, cycles: list[int] | None = None, *, include_drafts=False):
    qs = visible_submissions(user, Submission.objects.all())
    if cycles:
        qs = qs.filter(cycle_id__in=cycles)
    if not include_drafts:
        qs = qs.exclude(status__in=[S.DRAFT, S.REJECTED])
    return qs


def kpi_strip(qs) -> dict:
    agg = qs.aggregate(
        items=Count("id", distinct=True),
        verified=Count("id", filter=Q(status=S.VERIFIED), distinct=True),
        pending=Count("id", filter=Q(status=S.SUBMITTED), distinct=True),
        returned=Count("id", filter=Q(status=S.RETURNED), distinct=True),
        grants=Count("id", filter=Q(category__in=GRANT_CATEGORIES), distinct=True),
        ip=Count("id", filter=Q(category__in=IP_CATEGORIES), distinct=True),
        needs_match=Count("id", filter=Q(needs_match=True), distinct=True),
    )
    funding = qs.filter(category__in=FUNDING_CATEGORIES).aggregate(v=Sum("amount_pkr"))["v"]
    agg["funding_pkr"] = _f(funding)
    since = timezone.now() - datetime.timedelta(days=30)
    agg["last_30d"] = qs.filter(created_at__gte=since).count()
    return agg


# ---------------------------------------------------------------------------
# Explore: University → Faculty → Department → Person
# ---------------------------------------------------------------------------
def view_root(user) -> dict:
    """Where Explore starts for this user: university (ORIC), one faculty (Dean), one department (Chair)."""
    if user.is_superuser:
        return {"level": "university"}
    scopes = capability_scopes(user, "submission.view")
    if not scopes:
        return {"level": "self"}
    if any(s.is_global for s in scopes):
        return {"level": "university"}
    facs = sorted({s.faculty_id for s in scopes if s.faculty_id})
    depts = sorted({s.department_id for s in scopes if s.department_id})
    if len(facs) == 1 and not [d for d in depts if not Department.objects.filter(pk=d, faculty_id=facs[0]).exists()]:
        return {"level": "faculty", "id": facs[0]}
    if not facs and len(depts) == 1:
        return {"level": "department", "id": depts[0]}
    return {"level": "university", "faculty_ids": facs, "department_ids": depts}


def _per_department(qs) -> dict[int, dict]:
    """Aggregate over department links (co-PI departments included)."""
    links = SubmissionDepartment.objects.filter(submission__in=qs.values("pk"))
    rows = links.values("department_id").annotate(
        items=Count("submission_id", distinct=True),
        verified=Count("submission_id", filter=Q(submission__status=S.VERIFIED), distinct=True),
        pending=Count("submission_id", filter=Q(submission__status=S.SUBMITTED), distinct=True),
        grants=Count("submission_id", filter=Q(submission__category__in=GRANT_CATEGORIES), distinct=True),
        ip=Count("submission_id", filter=Q(submission__category__in=IP_CATEGORIES), distinct=True),
        funding=Sum("submission__amount_pkr", filter=Q(submission__category__in=FUNDING_CATEGORIES)),
    )
    return {r["department_id"]: r for r in rows}


def _active_people(qs) -> set[int]:
    owners = set(qs.exclude(owner__isnull=True).values_list("owner_id", flat=True))
    contrib = set(Contributor.objects.filter(submission__in=qs.values("pk"), person__isnull=False)
                  .values_list("person_id", flat=True))
    return owners | contrib


def explore(user, *, level: str, obj_id: int | None, cycles: list[int]) -> dict:
    qs = scoped(user, cycles)
    active = _active_people(qs)
    if level == "university":
        per_dept = _per_department(qs)
        rows = []
        visible_depts = _visible_department_ids(user)
        for f in Faculty.objects.filter(is_active=True).prefetch_related("departments").select_related("dean"):
            dept_ids = [d.pk for d in f.departments.all() if visible_depts is None or d.pk in visible_depts]
            if not dept_ids:
                continue
            members = Person.objects.filter(department_id__in=dept_ids, is_faculty=True)
            fq = qs.filter(Q(faculty=f) | Q(pk__in=SubmissionDepartment.objects.filter(
                department__faculty=f).values("submission_id")))
            rows.append({
                "type": "faculty", "id": f.pk, "code": f.code, "name": f.name, "lead": f.dean.full_name if f.dean else None,
                "members": members.count(),
                "active_members": members.filter(pk__in=active).count(),
                **_sum_rows([per_dept.get(d, {}) for d in dept_ids]),
                "items": fq.count(),
            })
        institution = qs.filter(owner__isnull=True, department__isnull=True)
        return {"level": level, "title": "NED University", "breadcrumb": [], "kpis": kpi_strip(qs),
                "rows": rows, "institution_items": institution.count()}

    if level == "faculty":
        f = Faculty.objects.select_related("dean").get(pk=obj_id)
        visible_depts = _visible_department_ids(user)
        fq = qs.filter(Q(faculty=f) | Q(pk__in=SubmissionDepartment.objects.filter(
            department__faculty=f).values("submission_id")))
        per_dept = _per_department(fq)
        rows = []
        for d in f.departments.filter(is_active=True).select_related("chair").order_by("name"):
            if visible_depts is not None and d.pk not in visible_depts:
                continue
            members = Person.objects.filter(department=d, is_faculty=True)
            rows.append({"type": "department", "id": d.pk, "code": d.code, "name": d.name,
                         "lead": d.chair.full_name if d.chair else None, "members": members.count(),
                         "active_members": members.filter(pk__in=active).count(),
                         **_sum_rows([per_dept.get(d.pk, {})])})
        return {"level": level, "id": f.pk, "title": f.name, "subtitle": f"Dean: {f.dean.full_name}" if f.dean else "",
                "breadcrumb": [{"level": "university", "name": "NED University"}], "kpis": kpi_strip(fq), "rows": rows}

    if level == "department":
        d = Department.objects.select_related("faculty", "chair").get(pk=obj_id)
        dq = qs.filter(Q(department=d) | Q(pk__in=SubmissionDepartment.objects.filter(department=d)
                                              .values("submission_id")))
        owned = dq.values("owner_id").annotate(
            items=Count("id"), verified=Count("id", filter=Q(status=S.VERIFIED)),
            pending=Count("id", filter=Q(status=S.SUBMITTED)),
            grants=Count("id", filter=Q(category__in=GRANT_CATEGORIES)),
            ip=Count("id", filter=Q(category__in=IP_CATEGORIES)),
            funding=Sum("amount_pkr", filter=Q(category__in=FUNDING_CATEGORIES)))
        by_owner = {r["owner_id"]: r for r in owned}
        co = dict(Contributor.objects.filter(submission__in=dq.values("pk"), person__department=d)
                  .exclude(role__in=["pi", "inventor", "lead", "winner", "founder", "author", "focal", "host",
                                     "participant", "faculty"])
                  .values("person_id").annotate(n=Count("submission_id", distinct=True))
                  .values_list("person_id", "n"))
        rows = []
        for p in Person.objects.filter(department=d, is_faculty=True).select_related("user").order_by("full_name"):
            r = by_owner.get(p.pk, {})
            rows.append({"type": "person", "id": p.pk, "code": "", "name": p.full_name, "lead": p.designation,
                         "avatar": p.avatar.url if p.avatar else None,
                         "email": p.user.email if p.user_id else None, "is_phd": p.is_phd,
                         "is_chair": d.chair_id == p.pk, "items": r.get("items", 0), "verified": r.get("verified", 0),
                         "pending": r.get("pending", 0), "grants": r.get("grants", 0), "ip": r.get("ip", 0),
                         "funding": _f(r.get("funding")), "co_items": co.get(p.pk, 0)})
        crumbs = [{"level": "university", "name": "NED University"}]
        if d.faculty_id:
            crumbs.append({"level": "faculty", "id": d.faculty_id, "name": d.faculty.name})
        return {"level": level, "id": d.pk, "title": d.name,
                "subtitle": f"Chairman: {d.chair.full_name}" if d.chair else "", "breadcrumb": crumbs,
                "kpis": kpi_strip(dq), "rows": rows,
                "not_submitted": sum(1 for r in rows if not r["items"] and not r["co_items"])}

    if level == "person":
        p = Person.objects.select_related("department__faculty", "user").get(pk=obj_id)
        pq = qs.filter(Q(owner=p) | Q(pk__in=Contributor.objects.filter(person=p).values("submission_id")))
        by_cat = list(pq.values("category").annotate(n=Count("id"), amount=Sum("amount_pkr")).order_by("-n"))
        crumbs = [{"level": "university", "name": "NED University"}]
        if p.department_id and p.department.faculty_id:
            crumbs.append({"level": "faculty", "id": p.department.faculty_id, "name": p.department.faculty.name})
        if p.department_id:
            crumbs.append({"level": "department", "id": p.department_id, "name": p.department.name})
        return {"level": level, "id": p.pk, "title": p.full_name,
                "subtitle": " · ".join(x for x in [p.designation, p.department.code if p.department_id else ""] if x),
                "email": p.user.email if p.user_id else None, "avatar": p.avatar.url if p.avatar else None,
                "breadcrumb": crumbs, "kpis": kpi_strip(pq),
                "by_category": [{**r, "label": CATEGORY_BY_KEY[r["category"]]["short"], "amount": _f(r["amount"])}
                                for r in by_cat]}
    raise ValueError("unknown level")


def _sum_rows(rows: list[dict]) -> dict:
    out = {"items": 0, "verified": 0, "pending": 0, "grants": 0, "ip": 0, "funding": 0.0}
    for r in rows:
        for k in out:
            out[k] += _f(r.get(k)) if k == "funding" else int(r.get(k) or 0)
    return out


def _visible_department_ids(user) -> set[int] | None:
    from rbac.utils import ALL, capability_department_ids

    ids = capability_department_ids(user, "submission.view")
    return None if ids == ALL else set(ids)


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------
def home(user, cycle_id: int | None = None) -> dict:
    """``cycle_id`` is the year the rail switcher shows; deadlines always come from the open year."""
    open_cycle = ReportingCycle.current()
    cycle = (ReportingCycle.objects.filter(pk=cycle_id).first() if cycle_id else None) or open_cycle
    cycles = [cycle.pk] if cycle else []
    person = getattr(user, "person", None) if hasattr(user, "person") else None
    mine = Submission.objects.filter(own_q(user))
    if cycles:
        mine_cycle = mine.filter(cycle_id__in=cycles)
    else:
        mine_cycle = mine
    by_pillar = {p["key"]: 0 for p in PILLARS}
    for row in mine_cycle.exclude(status=S.REJECTED).values("pillar").annotate(n=Count("id")):
        by_pillar[row["pillar"]] = row["n"]
    out = {
        "cycle": {"id": cycle.pk, "label": cycle.label, "deadline": cycle.submission_deadline,
                  "accepts_submissions": cycle.accepts_submissions, "starts_on": cycle.starts_on,
                  "ends_on": cycle.ends_on, "status": cycle.status} if cycle else None,
        "open_cycle": {"id": open_cycle.pk, "label": open_cycle.label, "deadline": open_cycle.submission_deadline}
        if open_cycle else None,
        "person": {"id": person.pk, "full_name": person.full_name, "department_id": person.department_id,
                   "department_code": person.department.code if person and person.department_id else None}
        if person else None,
        "mine": {
            "by_pillar": by_pillar,
            "total": mine_cycle.exclude(status=S.REJECTED).count(),
            "by_status": {r["status"]: r["n"] for r in mine_cycle.values("status").annotate(n=Count("id"))},
            "drafts": mine.filter(status=S.DRAFT).count(),
            "returned": list(mine.filter(status=S.RETURNED).values("id", "title", "category", "review_comment")[:10]),
            "recent": list(mine_cycle.order_by("-updated_at").values("id", "title", "category", "status",
                                                                     "updated_at")[:6]),
        },
        "root": view_root(user),
    }
    from rbac.utils import user_has_capability

    if user_has_capability(user, "dashboard.view_admin"):
        qs = scoped(user, cycles)
        out["scope"] = {"kpis": kpi_strip(qs)}
        out["scope"]["recent"] = list(
            qs.order_by("-updated_at").values(
                "id", "title", "category", "status", "updated_at", "owner__full_name", "department__code")[:8])
        if user_has_capability(user, "submission.verify"):
            from submissions.access import scope_q

            q = scope_q(user, "submission.verify")
            pend = Submission.objects.filter(status=S.SUBMITTED, cycle_id__in=cycles)
            if q is not None:
                pend = pend.filter(q)
            out["scope"]["to_verify"] = pend.count()
    return out


# ---------------------------------------------------------------------------
# Reports / analytics
# ---------------------------------------------------------------------------
def analytics(user, cycles: list[int], filters_qs=None) -> dict:
    qs = filters_qs if filters_qs is not None else scoped(user, cycles)
    by_category = [
        {"category": r["category"], "label": CATEGORY_BY_KEY[r["category"]]["short"],
         "pillar": CATEGORY_BY_KEY[r["category"]]["pillar"], "n": r["n"], "amount": _f(r["amount"])}
        for r in qs.values("category").annotate(n=Count("id"), amount=Sum("amount_pkr")).order_by("-n")
    ]
    by_faculty = [
        {"faculty_id": r["faculty_id"], "code": r["faculty__code"] or "ORIC", "name": r["faculty__name"] or
         "Institution / unassigned", "n": r["n"],
         "funding": _f(r["funding"])}
        for r in qs.values("faculty_id", "faculty__code", "faculty__name").annotate(
            n=Count("id"), funding=Sum("amount_pkr", filter=Q(category__in=FUNDING_CATEGORIES))).order_by("-n")
    ]
    by_department = [
        {"department_id": r["department_id"], "code": r["department__code"] or "-", "n": r["n"],
         "funding": _f(r["funding"])}
        for r in qs.values("department_id", "department__code").annotate(
            n=Count("id"), funding=Sum("amount_pkr", filter=Q(category__in=FUNDING_CATEGORIES))).order_by("-n")
    ]
    scope_split = list(qs.exclude(scope_level="").values("scope_level").annotate(n=Count("id")))
    funding_split = [
        {"funding_source": r["funding_source"], "n": r["n"], "amount": _f(r["amount"])}
        for r in qs.exclude(funding_source="").values("funding_source").annotate(n=Count("id"),
                                                                                  amount=Sum("amount_pkr"))
    ]
    top_people = [
        {"person_id": r["owner_id"], "name": r["owner__full_name"], "department": r["owner__department__code"],
         "n": r["n"], "funding": _f(r["funding"])}
        for r in qs.exclude(owner__isnull=True).values("owner_id", "owner__full_name", "owner__department__code")
        .annotate(n=Count("id"), funding=Sum("amount_pkr", filter=Q(category__in=FUNDING_CATEGORIES)))
        .order_by("-n")[:15]
    ]
    top_orgs = [
        {"organization_id": r["organization_id"], "name": r["organization__name"], "n": r["n"],
         "amount": _f(r["amount"])}
        for r in qs.exclude(organization__isnull=True).values("organization_id", "organization__name")
        .annotate(n=Count("id"), amount=Sum("amount_pkr")).order_by("-n")[:15]
    ]
    return {"kpis": kpi_strip(qs), "by_category": by_category, "by_faculty": by_faculty,
            "by_department": by_department, "scope_split": scope_split, "funding_split": funding_split,
            "top_people": top_people, "top_organizations": top_orgs}


def yearly_trend(user) -> list[dict]:
    qs = visible_submissions(user).exclude(status__in=[S.DRAFT, S.REJECTED])
    out = []
    for c in ReportingCycle.objects.order_by("year"):
        cq = qs.filter(cycle=c)
        out.append({"cycle": c.pk, "label": c.label, "year": c.year, "items": cq.count(),
                    "funding": _f(cq.filter(category__in=FUNDING_CATEGORIES).aggregate(v=Sum("amount_pkr"))["v"]),
                    **{p["key"]: cq.filter(pillar=p["key"]).count() for p in PILLARS}})
    return out


def money(v) -> Decimal:
    return Decimal(str(v or 0))
