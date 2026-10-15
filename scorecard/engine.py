"""Compute the HEC scorecard for one fiscal year from submission records + Index-A profile."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum

from submissions.models import Submission

from .kpis import KPI_BY_CODE, KPIS, RANKING, SECTIONS
from .models import InstitutionProfile, KpiOverride

S = Submission.Status
PROPOSAL_CATEGORIES = ["grant_hec_submitted", "grant_nonhec_submitted", "joint_submitted"]


def band_score(bands, measure) -> float:
    if measure is None or measure <= 0:
        return 0.0
    score = 0.0
    for low, pts in bands:
        if measure >= low:
            score = pts
    return float(score)


def _base(cycle, *, include_pending: bool, faculty_id=None, department_id=None):
    statuses = [S.VERIFIED, S.SUBMITTED] if include_pending else [S.VERIFIED]
    qs = Submission.objects.filter(cycle=cycle, status__in=statuses)
    links = Submission.departments.through.objects
    if department_id:
        qs = qs.filter(Q(department_id=department_id)
                       | Q(pk__in=links.filter(department_id=department_id).values("submission_id")))
    elif faculty_id:
        qs = qs.filter(Q(faculty_id=faculty_id)
                       | Q(pk__in=links.filter(department__faculty_id=faculty_id).values("submission_id")))
    return qs


def _records(base, kpi):
    qs = base.filter(category__in=kpi["categories"])
    for k, v in kpi["filters"].items():
        qs = qs.filter(**{k: v})
    return qs


def _due(cycle, kpi, *, faculty_id=None, department_id=None):
    """Approved projects (any year, any non-draft status) whose end date falls in this fiscal year."""
    qs = Submission.objects.filter(category__in=kpi["categories"]).exclude(status__in=[S.DRAFT, S.REJECTED])
    qs = qs.filter(data__end_date__gte=cycle.starts_on.isoformat(), data__end_date__lte=cycle.ends_on.isoformat())
    if department_id:
        qs = qs.filter(department_id=department_id)
    elif faculty_id:
        qs = qs.filter(faculty_id=faculty_id)
    return qs


def _profile_score(kpi, profile: dict):
    v = profile.get(kpi["profile_key"])
    if kpi["bands"]:
        try:
            n = float(v or 0)
        except (TypeError, ValueError):
            n = 0
        return n, band_score(kpi["bands"], n)
    if kpi["profile_key"] == "database":
        val = {"portal": 2, "excel": 1}.get(str(v).lower(), 1 if v in (True, "yes", "Yes") else 0)
        return ("Customized portal" if val == 2 else "Excel / Access" if val == 1 else "No"), min(val, kpi["max"])
    yes = v in (True, "yes", "Yes", 1, "1")
    return ("Yes" if yes else "No"), (kpi["max"] if yes else 0.0)


def compute(cycle, *, include_pending=False, faculty_id=None, department_id=None, apply_overrides=True) -> dict:
    base = _base(cycle, include_pending=include_pending, faculty_id=faculty_id, department_id=department_id)
    profile_obj = InstitutionProfile.objects.filter(cycle=cycle).first()
    operations = profile_obj.operations if profile_obj else {}
    phd = cycle.phd_faculty_count or 0
    overrides = {o.kpi: o for o in KpiOverride.objects.filter(cycle=cycle)} if apply_overrides else {}
    scoped = bool(faculty_id or department_id)

    reported: dict[str, float] = {}
    rows = []
    proposals_count = base.filter(category__in=PROPOSAL_CATEGORIES).count()
    for kpi in KPIS:
        code = kpi["code"]
        measure = None
        unit = "count"
        if kpi["kind"] == "profile":
            value, score = _profile_score(kpi, operations)
            if scoped:
                value, score = None, 0.0
            rows.append(_row(kpi, value, None, score, overrides.get(code), unit="profile"))
            continue
        if kpi["kind"] == "due":
            value = _due(cycle, kpi, faculty_id=faculty_id, department_id=department_id).count()
        elif kpi["kind"] == "sum":
            value = float(_records(base, kpi).aggregate(v=Sum("amount_pkr"))["v"] or 0)
            unit = "pkr"
        else:
            value = _records(base, kpi).count()
        ov = overrides.get(code)
        if ov and ov.reported is not None and not scoped:
            value = float(ov.reported)
        reported[code] = value

        if kpi["kind"] == "exists":
            score = kpi["max"] if value else 0.0
        elif kpi["kind"] == "pct_phd":
            measure = (value / phd * 100) if phd else None
            score = band_score(kpi["bands"], measure)
            unit = "pct_phd"
        elif kpi["kind"] == "pct_of":
            denom = proposals_count if kpi["of"] == "proposals" else reported.get(kpi["of"], 0)
            measure = (value / denom * 100) if denom else None
            score = band_score(kpi["bands"], measure)
            unit = "pct_of"
        else:
            score = band_score(kpi["bands"], value) if kpi["bands"] else 0.0
        rows.append(_row(kpi, value, measure, min(score, kpi["max"]), ov, unit=unit))

    sections = []
    total = total_computed = 0.0
    for sec in SECTIONS:
        srows = [r for r in rows if r["section"] == sec["key"]]
        s = sum(r["score"] for r in srows if r["max"])
        c = sum(r["computed_score"] for r in srows if r["max"])
        hec = [r["hec_score"] for r in srows if r["max"] and r["hec_score"] is not None]
        sections.append({**sec, "score": round(s, 2), "computed": round(c, 2),
                         "hec_score": round(sum(hec), 2) if hec else None, "rows": srows})
        total += s
        total_computed += c
    category = next(r for r in RANKING if total >= r["min"])
    return {
        "cycle": {"id": cycle.pk, "label": cycle.label, "starts_on": cycle.starts_on, "ends_on": cycle.ends_on},
        "phd_faculty_count": phd, "include_pending": include_pending,
        "scope": {"faculty_id": faculty_id, "department_id": department_id},
        "total": round(total, 2), "total_computed": round(total_computed, 2), "max": 100,
        "category": category, "ranking": RANKING, "sections": sections,
    }


def _row(kpi, value, measure, score, ov, *, unit):
    final = float(ov.score) if ov and ov.score is not None else score
    return {
        "code": kpi["code"], "section": kpi["section"], "area": kpi["area"], "title": kpi["title"],
        "max": kpi["max"], "kind": kpi["kind"], "unit": unit, "categories": kpi["categories"],
        "filters": {k.replace("data__", ""): v for k, v in kpi["filters"].items()},
        "reported": value, "measure": round(measure, 2) if measure is not None else None,
        "bands": [{"from": lo, "score": pts} for lo, pts in kpi["bands"]], "rubric": kpi["rubric"],
        "computed_score": round(score, 2), "score": round(final, 2),
        "overridden": bool(ov and (ov.score is not None or ov.reported is not None)),
        "hec_score": float(ov.hec_score) if ov and ov.hec_score is not None else None,
        "note": ov.note if ov else "",
    }


def money(v) -> Decimal:
    return Decimal(str(v or 0))


__all__ = ["compute", "band_score", "KPI_BY_CODE"]
