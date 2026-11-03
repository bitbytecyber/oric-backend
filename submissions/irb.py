"""Fold stand-alone ``irb_review`` records into the proposal they reviewed ("Reviewed by IRB" flag)."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from django.core.files.base import ContentFile
from django.db import transaction

from .models import EvidenceFile, Submission

PROPOSAL_CATEGORIES = ["grant_hec_submitted", "grant_nonhec_submitted", "joint_submitted"]


def _norm(title) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(title or "").lower()).split())


def _find_proposal(irb: Submission, proposals: list[Submission]) -> Submission | None:
    key = _norm(irb.data.get("research_proposal_title") or irb.title)
    if len(key) < 8:
        return None
    exact = [p for p in proposals if _norm(p.data.get("research_proposal_title") or p.title) == key]
    if len(exact) > 1 and irb.owner_id:
        exact = [p for p in exact if p.owner_id == irb.owner_id] or exact
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    scored = sorted(((SequenceMatcher(None, key, _norm(p.data.get("research_proposal_title") or p.title)).ratio(), p)
                     for p in proposals), key=lambda x: -x[0])
    if scored and scored[0][0] >= 0.9 and (len(scored) == 1 or scored[0][0] - scored[1][0] > 0.03):
        return scored[0][1]
    return None


def merge_irb_reviews(*, cycle=None, apply=False) -> dict:
    """Set "Reviewed by IRB" on the matching proposal (same fiscal year) and mark the old record merged.

    Unmatched records stay as they are; KPI B.x keeps counting them (see ``scorecard.engine.irb_records``)."""
    irbs = Submission.objects.filter(category="irb_review").exclude(data__has_key="_merged_into")
    if cycle is not None:
        irbs = irbs.filter(cycle=cycle)
    report = {"matched": [], "unmatched": []}
    used: set[int] = set()
    with transaction.atomic():
        for irb in irbs.select_related("cycle").prefetch_related("files"):
            # one IRB record per proposal, and only between records in the same state, so that the scorecard
            # (which counts by status) gives B.x exactly the same value as before the merge
            proposals = [p for p in Submission.objects.filter(category__in=PROPOSAL_CATEGORIES, cycle=irb.cycle,
                                                              status=irb.status)
                         if p.pk not in used and p.data.get("irb_reviewed") != "Yes"]
            prop = _find_proposal(irb, proposals)
            row = {"irb": irb.pk, "cycle": irb.cycle.label, "title": irb.title}
            if not prop:
                report["unmatched"].append(row)
                continue
            used.add(prop.pk)
            report["matched"].append({**row, "proposal": prop.pk})
            if not apply:
                continue
            d = dict(prop.data)
            d["irb_reviewed"] = "Yes"
            for src, dst in (("review_date", "irb_review_date"), ("irb_decision", "irb_decision"),
                             ("evidence_link", "irb_minutes_link")):
                if irb.data.get(src) and not d.get(dst):
                    d[dst] = irb.data[src]
            prop.data = d
            prop.save(update_fields=["data"])
            old = next((f for f in irb.files.all() if f.field == "evidence"), None)
            if old and not prop.files.filter(field="irb_minutes").exists():
                try:
                    with old.file.open("rb") as fh:
                        content = ContentFile(fh.read(), name=old.original_name)
                    EvidenceFile.objects.create(submission=prop, field="irb_minutes", file=content,
                                                original_name=old.original_name, size=old.size,
                                                content_type=old.content_type)
                except OSError:
                    row["file_missing"] = True
            irb.data = {**irb.data, "_merged_into": prop.pk}
            irb.save(update_fields=["data"])
    return report
