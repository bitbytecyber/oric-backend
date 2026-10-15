"""Import an HEC "ORIC Self-Assessment Scorecard" workbook (Index-A/B/C/D) into submissions.

The workbook is a stack of titled tables per sheet. For every table we
  1. find its title row "(vi) Research Proposals Approved …" and the following "SN" header row,
  2. map each header cell to a registry field via ``TABLES[...]["columns"]`` (regex on header text),
  3. read data rows until the next title, skipping instruction / grand-total rows and turning
     "National …" / "International …" sub-heading rows into the scope of the rows below,
  4. clean values (amounts, dates, nulls), parse the PI / inventor cell and match it to a Person,
  5. create one *verified* Submission per row (``source=excel_import``) keeping the complete
     original row under ``data["_source"]`` so no data point is lost.

Rows whose people cannot be matched are still created (they count on the scorecard) but get
``needs_match=True`` and an ``ImportRow(status=unmatched)`` with suggestions for the review queue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from submissions.models import Contributor, ReviewEvent, Submission
from submissions.registry import CATEGORY_BY_KEY, lead_slot
from submissions.services import resolve_organization

from ..models import ImportBatch, ImportRow
from .normalize import (
    PersonMatcher,
    date_range,
    is_null,
    million,
    nat_int,
    rupees,
    split_people,
    text,
    to_date,
    to_number,
)

TITLE_RE = re.compile(r"^\s*\(([ivx]+(?:-[abc])?)\)\s*(.*)", re.I | re.S)

# Column target conventions:
#   field name              -> cleaned by the registry field type
#   "_pi" / "_lead"          -> lead contributor string (PI / inventor / winner)
#   "_copi"                  -> co-contributors string
#   "_duration"              -> "start to end" text -> start_date / end_date
#   "_evidence"              -> evidence link(s)
#   "_amount_rupees"         -> amount already in rupees (overrides the million column)
#   "_thematic_title"        -> "Thematic area and title" combined cell -> research_proposal_title
#   "_scope"                 -> National / International
#   "_date_duration"         -> "date and duration of agreement"
#   None                     -> kept only in data["_source"]
GRANT_COMMON = [
    (r"name of (joint )?research grant", "research_grant_name"),
    (r"name of co-?pi", "_copi"),
    (r"name (and details )?of pi|pi with designation", "_pi"),
    (r"thematic area and title", "_thematic_title"),
    (r"thematic area", "thematic_area"),
    (r"title of research proposal", "research_proposal_title"),
    (r"^duration", "_duration"),
    (r"collaborating partner", "collaborating_partners"),
    (r"co funding|co-funding", "co_funding_partners"),
    (r"national or international|national /\s*international|international or national", "_scope"),
    (r"annex", "_evidence"),
    (r"remarks", "remarks"),
    (r"key project deliverables", "key_project_deliverables"),
]

TABLES: dict[str, dict] = {
    # ---------------- Index-B -----------------------------------------------------------------
    "B.i": {"sheet": "Index-B", "label": "i", "category": "grant_opportunity", "columns": [
        (r"title of research grant opportunity", "opportunity_title"), (r"date of circulation", "circulation_date"),
        (r"national", "_scope"), (r"thematic", "thematic_area"), (r"title of research proposal",
                                                                  "research_proposal_title"),
        (r"starting date", "start_date"), (r"ending date", "end_date"),
        (r"collaborating", "collaborating_partners"), (r"co funding", "co_funding_partners"),
        (r"status", "award_status"), (r"remarks", "remarks"), (r"annex", "_evidence")]},
    "B.ii": {"sheet": "Index-B", "label": "ii", "category": "grant_hec_submitted", "columns": [
        (r"date of proposal submission", "proposal_submission_date"), (r"total funding requested",
                                                                       "total_funding_requested"),
        (r"^status", "status"), *GRANT_COMMON]},
    "B.iii": {"sheet": "Index-B", "label": "iii", "category": "grant_hec_approved", "columns": [
        (r"date of proposal approval", "proposal_approval_date"), (r"total funding approved",
                                                                   "total_funding_approved"),
        (r"oric overhead", "oric_overhead"), (r"date of approval", None), *GRANT_COMMON]},
    "B.iv": {"sheet": "Index-B", "label": "iv", "category": "grant_hec_completed", "columns": [
        (r"date of project completion", "project_completion_date"), (r"status of project", "project_status"),
        (r"total funding utilized", "total_funding_utilized"), (r"total funding released", "total_funding_released"),
        *GRANT_COMMON]},
    "B.v": {"sheet": "Index-B", "label": "v", "category": "grant_nonhec_submitted", "columns": [
        (r"date of proposal submission", "proposal_submission_date"), (r"total funding requested",
                                                                       "total_funding_requested"),
        (r"^status", "status"), *GRANT_COMMON]},
    "B.vi": {"sheet": "Index-B", "label": "vi", "category": "grant_nonhec_approved", "columns": [
        (r"date of proposal approval", "proposal_approval_date"), (r"total funding approved",
                                                                   "total_funding_approved"),
        (r"date of approval", None), *GRANT_COMMON]},
    "B.vii": {"sheet": "Index-B", "label": "vii", "category": "grant_nonhec_completed", "columns": [
        (r"name of research grant", "research_grant_name"),
        (r"date of project completion", "project_completion_date"),
        (r"total funding utilized", "total_funding_utilized"), (r"total funding released", "total_funding_released"),
        *GRANT_COMMON]},
    "B.viii-a": {"sheet": "Index-B", "label": "viii-a", "category": "joint_submitted", "columns": [
        (r"date of joint project submission", "submission_date"), (r"total funding requested",
                                                                   "total_funding_requested"),
        (r"status", "status"), *GRANT_COMMON]},
    "B.viii-b": {"sheet": "Index-B", "label": "viii-b", "category": "joint_approved", "columns": [
        (r"date of joint project approval", "approval_date"), (r"total funding approved", "total_funding_approved"),
        (r"status", "status"), *GRANT_COMMON]},
    "B.viii-c": {"sheet": "Index-B", "label": "viii-c", "category": "joint_completed", "columns": [
        (r"date of joint project completion", "completion_date"),
        (r"total funding utilized", "total_funding_utilized"), (r"total funding released", "total_funding_released"),
        (r"status of project", "project_status"), *GRANT_COMMON]},
    "B.x": {"sheet": "Index-B", "label": "x", "category": "irb_review", "columns": [
        (r"date of review", "review_date"), (r"total amount requested", "total_amount_requested"),
        (r"irb meeting decision", "irb_decision"), (r"key project expected", "key_deliverables"), *GRANT_COMMON]},
    "B.xi": {"sheet": "Index-B", "label": "xi", "category": "policy_advocacy", "columns": [
        (r"name of government body", "government_body_presented"), (r"date of presentation", "presentation_date"),
        (r"area advocated", "advocacy_area"), (r"^brief", "brief"), (r"coalition", "coalition_partners"),
        (r"issue verification", "research_status"), (r"advocacy tools", "advocacy_tools"),
        (r"name of pi", "_pi"), (r"^duration", "_duration"), (r"annex", "_evidence")]},
    "B.xii": {"sheet": "Index-B", "label": "xii", "category": "research_link", "columns": [
        (r"type of linkage", "linkage_type"), (r"date of mou", "mou_agreement_date"),
        (r"international or national|national", "_scope"),
        (r"host institution", "host_institution"), (r"collaborating agency", "collaborating_agency"),
        (r"field of study", "field_of_study"), (r"scope of collaboration", "scope_of_collaboration"),
        (r"salient features", "salient_features"), (r"annex", "_evidence")]},
    "B.xiii": {"sheet": "Index-B", "label": "xiii", "category": "contract_research", "scope": "National",
               "columns": [
                   (r"thematic areas and title", "_thematic_title"), (r"date of contract signed",
                                                                       "contract_signed_date"),
                   (r"name of co-pi", "_copi"), (r"name of pi", "_pi"), (r"sponsoring agency", "sponsoring_agency"),
                   (r"national", "_scope"), (r"counterpart from industry", "counterpart_industry"),
                   (r"^duration", "_duration"), (r"total amount approved", "total_amount_approved"),
                   (r"^__col_L$", "_amount_rupees"), (r"expected deliverables", "expected_deliverables"),
                   (r"date of contract$", None), (r"annex", "_evidence")]},
    "B.xvi": {"sheet": "Index-B", "label": "xvi", "category": "civic_engagement", "columns": [
        (r"title of event", "event_title"), (r"date of event", "event_date"),
        (r"component of community", "community_component"), (r"^outcome", "outcome"),
        (r"collaboration developed", "collaboration_developed"), (r"csos", "engaged_csos_ngos"),
        (r"sponsoring agency", "sponsoring_agency"), (r"arranged", "arranged_or_participated"),
        (r"dissemination", "dissemination_material"), (r"remarks", "remarks"), (r"annex", "_evidence")]},
    "B.xvii": {"sheet": "Index-B", "label": "xvii", "category": "consultancy_opportunity", "columns": [
        (r"title of project", "project_title"), (r"date of circulation|date of execution", "circulation_date"),
        (r"name of pi", "_pi"), (r"company details", "company_details"),
        (r"contract value", "contract_value"), (r"project timelines", "_duration"),
        (r"type of consultancy", "consultancy_type"), (r"key deliverables", "key_deliverables"),
        (r"oric percentage", None), (r"remarks", "remarks"), (r"annex", "_evidence")]},
    "B.xviii": {"sheet": "Index-B", "label": "xviii", "category": "consultancy_contract", "columns": [
        (r"title of project", "project_title"), (r"date of execution", "execution_date"),
        (r"name of pi", "_pi"), (r"company details", "company_details"),
        (r"contract value \(pkr millions\)", "contract_value"), (r"contract value \(pkr\)", "_amount_rupees"),
        (r"project timelines", "_duration"), (r"type of consultancy", "consultancy_type"),
        (r"key deliverables", "key_deliverables"), (r"oric percentage", "oric_percentage"),
        (r"remarks", "remarks"), (r"annex", "_evidence")]},
    "B.xix": {"sheet": "Index-B", "label": "xix", "category": "asrb_liaison", "columns": [
        (r"liaison developed with", "liaison_with"), (r"date of execution", "execution_date"),
        (r"annex", "_evidence")]},
    # ---------------- Index-C -----------------------------------------------------------------
    "C.i": {"sheet": "Index-C", "label": "i", "category": "policy", "fixed": {"policy_type": "Research policy"},
            "columns": [(r"title of", "policy_title"), (r"ref", "policy_ref_no"), (r"date of approval",
                                                                                   "approval_date"),
                        (r"approved by", "approved_by")]},
    "C.ii": {"sheet": "Index-C", "label": "ii", "category": "policy", "fixed": {"policy_type": "IP policy"},
             "columns": [(r"title of", "policy_title"), (r"ref", "policy_ref_no"), (r"date of approval",
                                                                                    "approval_date"),
                         (r"approved by", "approved_by")]},
    "C.iii": {"sheet": "Index-C", "label": "iii", "category": "policy", "fixed": {"policy_type": "Other policy"},
              "columns": [(r"title of", "policy_title"), (r"ref", "policy_ref_no"), (r"date of approval",
                                                                                     "approval_date"),
                          (r"approved by", "approved_by")]},
}

INVENTION = [
    (r"lead inventor", "_lead"), (r"title of invention", "invention_title"), (r"category of ip", "ip_category"),
    (r"development status", "development_status"), (r"key scientific", "key_scientific_aspects"),
    (r"commercial partner", "commercial_partner"), (r"financial support", "financial_support"),
    (r"national|international", "_scope"), (r"annex|^__col_L$", "_evidence"),
]
TABLES.update({
    "C.iv": {"sheet": "Index-C", "label": "iv", "category": "ip_disclosure", "columns": [
        (r"disclosure made with", "disclosure_made_with"), (r"previous disclosure", "previous_disclosure"),
        *INVENTION]},
    **{f"C.{lbl}": {"sheet": "Index-C", "label": lbl, "category": "patent",
                    "fixed": {"filed_or_granted": fg}, "scope": sc, "columns": [
                        (r"patent filed with|granting authority", "filed_with"), (r"date of filing", "filing_date"),
                        *INVENTION]}
       for lbl, fg, sc in [("v", "Filed", "National"), ("vi", "Granted", "National"),
                           ("vii", "Filed", "International"), ("viii", "Granted", "International")]},
    **{f"C.{lbl}": {"sheet": "Index-C", "label": lbl, "category": "licensing_negotiation", "scope": sc, "columns": [
        (r"field of use", "field_of_use"), (r"duration of agreement", "duration_of_agreement"),
        (r"licensee", "licensee"), (r"status of negotiation", "negotiation_status"), *INVENTION]}
       for lbl, sc in [("ix", "National"), ("xi", "International")]},
    **{f"C.{lbl}": {"sheet": "Index-C", "label": lbl, "category": "license_signed", "scope": sc, "columns": [
        (r"field of use", "field_of_use"), (r"date and duration", "_date_duration"), (r"licensee", "licensee"),
        (r"exclusive", "license_type"), *INVENTION]}
       for lbl, sc in [("x", "National"), ("xii", "International")]},
    "C.xiii": {"sheet": "Index-C", "label": "xiii", "category": "prototype", "columns": [
        (r"field of use", "field_of_use"), (r"industrial partner", "industrial_partner"), (r"remarks", "remarks"),
        *INVENTION]},
    "C.xiv": {"sheet": "Index-C", "label": "xiv", "category": "creative_product", "columns": [
        (r"^title", "title"), (r"department of lead|name.*lead", "_lead"), (r"^category", "product_category"),
        (r"national", "_scope"), (r"forum", "forum"), (r"^status", "status"),
        (r"financial support", "financial_support"), (r"field of use", "field_of_use"), (r"annex", "_evidence")]},
    "C.xv": {"sheet": "Index-C", "label": "xv", "category": "industry_visit", "columns": [
        (r"name of visitor", "visitor_name"), (r"date of visit", "visit_date"), (r"agenda", "agenda"),
        (r"annex|^__col_L$", "_evidence")]},
    "C.xvi": {"sheet": "Index-C", "label": "xvi", "category": "collaboration_agreement", "columns": [
        (r"type of linkage", "linkage_type"), (r"international or national|national", "_scope"),
        (r"host institution", "partner_institution"), (r"^duration", "duration"),
        (r"key initiatives", "key_initiatives"), (r"^field", "field"), (r"scope of collaboration",
                                                                        "scope_of_collaboration"),
        (r"establishment date", "establishment_date"), (r"financial support", "financial_support"),
        (r"annex", "_evidence")]},
    "C.xvii": {"sheet": "Index-C", "label": "xvii", "category": "award", "columns": [
        (r"title of award", "title"), (r"forum", "conferring_organization"), (r"award/ prize|award/prize|any award",
                                                                               "award_received"),
        (r"brief details", "work_details"), (r"prize money", "prize_money"), (r"award winner", "_lead"),
        (r"remarks", "remarks"), (r"annex", "_evidence")]},
    # ---------------- Index-D -----------------------------------------------------------------
    "D.i": {"sheet": "Index-D", "label": "i", "category": "research_revenue", "columns": [
        (r"name of research grant", "research_grant_name"), (r"national or international", "_scope_or_date"),
        (r"title of research proposal", "research_proposal_title"), (r"name and details of pi", "_pi"),
        (r"^duration", "_duration"), (r"total funding approved", "total_funding_approved"),
        (r"total funding released", "total_funding_released"),
        (r"overhead in approved", "oric_overhead_approved"), (r"overhead in released", "oric_overhead_released"),
        (r"remarks", "remarks"), (r"annex", "_evidence")]},
    "D.ii": {"sheet": "Index-D", "label": "ii", "category": "licensing_revenue", "columns": [
        (r"lead inventor", "_lead"), (r"title of invention", "invention_title"), (r"national", "_scope"),
        (r"date and duration", "_date_duration"), (r"licensee", "licensee"), (r"share percentages",
                                                                               "share_percentages"),
        (r"total amount", "total_amount"), (r"oric approved share", "oric_approved_share"),
        (r"oric received share", "oric_received_share"), (r"remarks", "remarks"), (r"annex", "_evidence")]},
    **{f"D.{lbl}": {"sheet": "Index-D", "label": lbl, "category": cat, "subheadings": True, "fixed": fixed,
                    "columns": [
                        (r"title of training|type of event", "title"), (r"date of event", "event_date"),
                        (r"no\. of participants", "participants"), (r"focus area", "focus_and_outcomes"),
                        (r"^organizer", "organizer"), (r"audience", "audience_type"),
                        (r"oric personnel", "oric_personnel"), (r"annex", "_evidence")]}
       for lbl, cat, fixed in [("iii", "training_oric", {"event_type": "Training"}),
                               ("iv", "training_external", {"event_type": "Training"}),
                               ("v", "exhibition", {"event_type": "Exhibition"}),
                               ("vi", "training_oric_staff", {"event_type": "Training"})]},
})

TABLES["B.xiv"] = {**TABLES["B.xiii"], "label": "xiv", "scope": "International"}

SKIP_TABLES = {"B.ix": "computed from B.vi (R&D funding volume)", "B.xv": "computed from B.xiii + B.xiv"}


@dataclass
class TableHit:
    key: str
    sheet: str
    title_row: int
    header_row: int
    end_row: int
    headers: dict = field(default_factory=dict)  # column letter -> header text


def locate_tables(wb) -> list[TableHit]:
    hits: list[TableHit] = []
    for sheet in ("Index-B", "Index-C", "Index-D"):
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        prefix = sheet[-1]
        titles = []
        for r in range(1, ws.max_row + 1):
            for c in (1, 2, 3):
                v = ws.cell(r, c).value
                if isinstance(v, str):
                    m = TITLE_RE.match(v)
                    if m:
                        titles.append((r, f"{prefix}.{m.group(1).lower()}"))
                    break
                if v not in (None, ""):
                    break
        for i, (row, key) in enumerate(titles):
            nxt = titles[i + 1][0] if i + 1 < len(titles) else ws.max_row + 1
            header_row = None
            for r in range(row + 1, min(row + 6, nxt)):
                if any(isinstance(ws.cell(r, c).value, str) and ws.cell(r, c).value.strip().upper() in
                       ("SN", "S.N", "S.NO", "S. NO", "SR. NO.") for c in (1, 2)):
                    header_row = r
                    break
            if header_row is None:
                continue
            headers = {}
            for c in range(1, ws.max_column + 1):
                v = ws.cell(header_row, c).value
                headers[get_column_letter(c)] = " ".join(str(v).split()) if v not in (None, "") else ""
            hits.append(TableHit(key, sheet, row, header_row, nxt - 1, headers))
    return hits


def _column_map(spec_cols, headers: dict) -> dict:
    out = {}
    used_targets = set()
    for col, head in headers.items():
        h = head.lower() if head else f"__col_{col}".lower()
        if h in ("sn", "s.n", "s.no", "sr. no.") or (not head and False):
            continue
        for pattern, target in spec_cols:
            pat = pattern.lower()
            if re.search(pat, h if head else f"__col_{col}".lower()):
                if target and target in used_targets and not target.startswith("_"):
                    continue
                out[col] = target
                if target:
                    used_targets.add(target)
                break
    return out


def _is_noise(values: list) -> bool:
    joined = " ".join(str(v) for v in values[:6] if v not in (None, "")).lower()
    if not joined.strip():
        return True
    return bool(re.search(r"grand total|^total\b|please add|add as many rows|sub total", joined))


def _subheading(values: list) -> str | None:
    filled = [v for v in values if v not in (None, "")]
    if 1 <= len(filled) <= 2 and isinstance(filled[0], str) and len(filled[0]) < 60:
        s = filled[0].lower()
        if "international" in s:
            return "International"
        if "national" in s:
            return "National"
    return None


@dataclass
class ImportResult:
    created: int = 0
    unmatched: int = 0
    skipped: int = 0
    errors: int = 0
    per_table: dict = field(default_factory=dict)
    log: list = field(default_factory=list)


def import_workbook(batch: ImportBatch, path: str, *, replace: bool = True, user=None) -> dict:
    wb = load_workbook(path, data_only=True, read_only=False)
    cycle = batch.cycle
    matcher = PersonMatcher()
    res = ImportResult()
    with transaction.atomic():
        if replace:
            Submission.objects.filter(cycle=cycle, source=Submission.Source.EXCEL).delete()
        _import_index_a(wb, cycle, user, res)
        hits = locate_tables(wb)
        seen = set()
        for hit in hits:
            if hit.key in SKIP_TABLES:
                res.log.append(f"{hit.key}: skipped ({SKIP_TABLES[hit.key]})")
                continue
            spec = TABLES.get(hit.key)
            if not spec or hit.key in seen:
                res.log.append(f"{hit.key}: no mapping, skipped")
                continue
            seen.add(hit.key)
            _import_table(batch, wb[hit.sheet], hit, spec, matcher, res, user)
        _import_strategic_plan(batch, wb, cycle, user, res)
        _sheet_scores(wb, res)
    stats = {"created": res.created, "unmatched": res.unmatched, "skipped": res.skipped, "errors": res.errors,
             "per_table": res.per_table, "sheet_scorecard": res.per_table.pop("_sheet_scorecard", {})}
    batch.stats = stats
    batch.log = "\n".join(res.log)
    batch.status = ImportBatch.Status.APPLIED
    batch.save()
    return stats


def _import_table(batch, ws, hit: TableHit, spec: dict, matcher, res: ImportResult, user):
    cat = CATEGORY_BY_KEY[spec["category"]]
    colmap = _column_map(spec["columns"], hit.headers)
    fields = {f["name"]: f for f in cat["fields"]}
    slot = lead_slot(cat)
    co_slot = next((p for p in cat["people"] if not p["lead"]), None)
    scope = spec.get("scope")
    count = 0
    for r in range(hit.header_row + 1, hit.end_row + 1):
        values = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
        if spec.get("subheadings"):
            sh = _subheading(values)
            if sh:
                scope = sh
                continue
        if _is_noise(values):
            continue
        letters = [get_column_letter(c) for c in range(1, ws.max_column + 1)]
        source = {}
        for col, v in zip(letters, values):
            if v in (None, ""):
                continue
            head = hit.headers.get(col) or f"col {col}"
            source[head] = text(v) if not isinstance(v, (int, float)) else v
        data: dict = dict(spec.get("fixed") or {})
        people_raw = {"lead": None, "co": None}
        evidence = []
        rupee_amount = None
        row_scope = scope
        for col, target in colmap.items():
            idx = letters.index(col)
            v = values[idx]
            if target is None or is_null(v):
                continue
            if target in ("_pi", "_lead"):
                people_raw["lead"] = v
            elif target == "_copi":
                people_raw["co"] = v
            elif target == "_duration":
                s, e = date_range(v)
                if s:
                    data.setdefault("start_date", s)
                if e:
                    data.setdefault("end_date", e)
            elif target == "_date_duration":
                d = to_date(v)
                if d:
                    data[cat["date_field"]] = d
                data["agreement_duration"] = text(v)
            elif target == "_evidence":
                evidence += re.findall(r"https?://\S+", str(v)) or ([text(v)] if text(v) else [])
            elif target == "_amount_rupees":
                rupee_amount = rupees(v)
            elif target == "_thematic_title":
                data["research_proposal_title"] = text(v)
            elif target == "_scope":
                row_scope = nat_int(v) or row_scope
            elif target == "_scope_or_date":
                row_scope = nat_int(v) or row_scope
                if not nat_int(v) and to_date(v):
                    data.setdefault("approval_date", to_date(v))
            elif target in fields:
                data[target] = _clean(fields[target], v, header=hit.headers.get(col, ""))
        if row_scope and "national_or_international" in fields:
            data["national_or_international"] = row_scope
        if cat["amount_field"] and rupee_amount is not None:
            if cat["amount_unit"] == "M":
                data[cat["amount_field"]] = round(rupee_amount / 1_000_000, 4)
            else:
                data[cat["amount_field"]] = rupee_amount
        if cat["date_field"] and not data.get(cat["date_field"]):
            data[cat["date_field"]] = data.get("start_date")
        data = {k: v for k, v in data.items() if v not in (None, "")}
        meaningful = [k for k in data if k not in (spec.get("fixed") or {}) and k != "national_or_international"]
        if not meaningful and not people_raw["lead"]:
            res.skipped += 1
            continue
        title_field = cat["title_field"]
        if title_field and not data.get(title_field):
            # tables without a title column: fall back to the first text value
            data[title_field] = next((text(v) for v in values[1:] if isinstance(v, str) and len(v) > 3), None)
        data["_source"] = source
        if evidence:
            data["evidence_link"] = evidence[0]

        # people
        contributors, owner, unmatched_text, suggestions = [], None, "", []
        leads = split_people(people_raw["lead"]) if people_raw["lead"] else []
        cos = split_people(people_raw["co"]) if people_raw["co"] else []
        if slot and leads:
            first, rest = leads[0], leads[1:]
            person, sugg = matcher.match(first["name"], first["dept_hint"])
            if person:
                owner = person
                contributors.append(Contributor(role=slot["role"], person=person, order=0))
            else:
                unmatched_text, suggestions = first["raw"], sugg
                contributors.append(Contributor(role=slot["role"], name=first["name"][:255],
                                                designation=first["designation"][:120],
                                                affiliation=first["dept_hint"][:255], order=0))
            cos = rest + cos
        if co_slot:
            for i, c in enumerate(cos, start=1):
                person, _ = matcher.match(c["name"], c["dept_hint"])
                contributors.append(Contributor(role=co_slot["role"], person=person,
                                                name="" if person else c["name"][:255],
                                                designation="" if person else c["designation"][:120],
                                                affiliation="" if person else c["dept_hint"][:255], order=i))
        needs_match = bool(slot and leads and owner is None)

        sub = Submission(category=cat["key"], cycle=batch.cycle, owner=owner, submitted_by=user, data=data,
                         status=Submission.Status.VERIFIED, source=Submission.Source.EXCEL, import_batch=batch,
                         import_ref=f"{hit.sheet}!{r}", needs_match=needs_match, verified_by=user,
                         verified_at=timezone.now(), submitted_at=timezone.now())
        if owner:
            sub.department = owner.department
            sub.faculty = owner.department.faculty if owner.department_id else None
        sub.promote()
        if not sub.event_date or not (batch.cycle.starts_on <= sub.event_date <= batch.cycle.ends_on):
            pass  # keep: the sheet says it belongs to this FY even when the typed date is off
        org_field = next((f["name"] for f in cat["fields"] if f["type"] == "org" and data.get(f["name"])), None)
        if org_field:
            sub.organization = resolve_organization(str(data[org_field])[:255])
        sub.save()
        for c in contributors:
            c.submission = sub
        Contributor.objects.bulk_create(contributors)
        sub.sync_departments()
        ReviewEvent.objects.create(submission=sub, actor=user, action=ReviewEvent.Action.IMPORT,
                                   to_status=sub.status, comment=f"{batch.original_name} {sub.import_ref}")
        ImportRow.objects.create(
            batch=batch, ref=sub.import_ref, table=hit.key, category=cat["key"],
            status=ImportRow.Status.UNMATCHED if needs_match else ImportRow.Status.CREATED,
            raw=source, parsed={k: v for k, v in data.items() if k != "_source"}, person_text=unmatched_text[:500],
            suggestions=suggestions, submission=sub)
        count += 1
        res.created += 1
        res.unmatched += int(needs_match)
    res.per_table[hit.key] = {"category": cat["key"], "rows": count,
                              "mapped_columns": {hit.headers.get(c) or c: t for c, t in colmap.items()}}
    res.log.append(f"{hit.key} ({hit.sheet} rows {hit.header_row + 1}-{hit.end_row}): {count} records")


def _clean(f: dict, v, *, header: str = ""):
    t = f["type"]
    if t == "date":
        return to_date(v)
    if t == "decimal":
        if "million" in header.lower() or "(pkr million" in f["label"].lower() or "pkr million" in f["label"].lower():
            return million(v)
        return rupees(v) if "pkr" in f["label"].lower() else to_number(v)
    if t == "int":
        n = to_number(v)
        return int(n) if n is not None else None
    if t in ("select", "radio"):
        s = text(v)
        if not s:
            return None
        for opt in f.get("options") or []:
            if s.lower() == opt.lower() or s.lower().startswith(opt.lower()):
                return opt
        if f["name"] == "national_or_international":
            return nat_int(s)
        return s
    return text(v)


# ---------------------------------------------------------------------------
# Index-A / Score Card / strategic plan
# ---------------------------------------------------------------------------
def _import_index_a(wb, cycle, user, res):
    from scorecard.models import InstitutionProfile

    if "Index-A" not in wb.sheetnames:
        return
    ws = wb["Index-A"]
    details = {}
    for r in range(1, 6):
        for c in range(2, ws.max_column, 2):  # label in B, D, F … value right next to it
            k, v = ws.cell(r, c).value, ws.cell(r, c + 1).value
            if isinstance(k, str) and k.strip() and not is_null(v):
                details[" ".join(k.split()).rstrip(" :")] = v if isinstance(v, (int, float)) else text(v)
    head_row = next((r for r in range(1, 20) if str(ws.cell(r, 1).value or "").strip().upper() == "SN"), 6)
    heads = {c: " ".join(str(ws.cell(head_row, c).value or "").split()).lower() for c in range(1, 16)}

    def col(word):
        return next((c for c, h in heads.items() if word in h), None)

    staff = []
    for r in range(head_row + 1, head_row + 30):
        name = ws.cell(r, col("name") or 4).value
        pos = ws.cell(r, col("position") or 2).value
        if is_null(name) and is_null(pos):
            if staff:
                break
            continue
        staff.append({
            "position": text(pos), "employment": text(ws.cell(r, col("full time") or 3).value), "name": text(name),
            "office_phone": text(ws.cell(r, col("office") or 5).value),
            "mobile": text(ws.cell(r, col("mobile") or 6).value), "email": text(ws.cell(r, col("email") or 7).value),
            "qualification_level": text(ws.cell(r, col("qualification level") or 8).value),
            "qualification_title": text(ws.cell(r, col("qualification title") or 9).value),
            "field_of_study": text(ws.cell(r, col("field of study") or 10).value),
            "appointment_date": to_date(ws.cell(r, col("date of appointment") or 12).value),
            "experience": text(ws.cell(r, col("total experience") or 14).value),
        })
    profile, _ = InstitutionProfile.objects.get_or_create(cycle=cycle)
    profile.details = details
    profile.staff = staff
    profile.operations = {**(profile.operations or {}), **_operations_from_score_card(wb)}
    profile.updated_by = user
    profile.save()
    for label, attr in ((r"phd faculty", "phd_faculty_count"), (r"sanctioned", "sanctioned_faculty_posts"),
                        (r"existing faculty", "existing_faculty_count")):
        v = next((v for k, v in details.items() if re.search(label, k.lower())), None)
        if isinstance(v, (int, float)):
            setattr(cycle, attr, int(v))
    cycle.save()
    res.log.append(f"Index-A: {len(details)} profile fields, {len(staff)} ORIC staff, PhD faculty = "
                   f"{cycle.phd_faculty_count}")


def _operations_from_score_card(wb) -> dict:
    if "Score Card" not in wb.sheetnames:
        return {}
    ws = wb["Score Card"]
    keys = {"i": "head", "ii": "manager_rm", "iii": "manager_ic", "iv": "support", "v": "steering_committee",
            "vi": "sc_meetings", "vii": "irb_meetings", "viii": "offices_ict", "ix": "webpage", "x": "database"}
    out = {}
    for r in range(5, 15):
        item = str(ws.cell(r, 2).value or "").strip().lower()
        v = ws.cell(r, 5).value
        if item in keys:
            k = keys[item]
            if k in ("sc_meetings", "irb_meetings"):
                out[k] = to_number(v) or 0
            elif k == "database":
                out[k] = "excel" if str(v).lower().startswith("y") else "no"
            else:
                out[k] = str(v).strip().lower().startswith("y")
    return out


def _sheet_scores(wb, res):
    """Keep the workbook's own reported numbers / self-scores for reconciliation in the UI."""
    if "Score Card" not in wb.sheetnames:
        return
    ws = wb["Score Card"]
    section = None
    out = {}
    for r in range(4, 66):
        a = str(ws.cell(r, 1).value or "").strip()
        if re.match(r"^[ABCD]\.?$", a):
            section = a[0]
            continue
        item = str(ws.cell(r, 2).value or "").strip()
        if not item or not section:
            continue
        reported = ws.cell(r, 6).value if section != "A" else ws.cell(r, 5).value
        if reported is None:
            reported = ws.cell(r, 5).value
        out[f"{section}.{item}"] = {"reported": reported, "max": ws.cell(r, 7).value, "score": ws.cell(r, 8).value}
    res.per_table["_sheet_scorecard"] = out


def _import_strategic_plan(batch, wb, cycle, user, res):
    if "Index-D" not in wb.sheetnames:
        return
    ws = wb["Index-D"]
    for r in range(1, 6):
        if str(ws.cell(r, 1).value or "").strip().lower() == "ia":
            title = text(ws.cell(r, 2).value) or "Five-Year Strategic Plan"
            link = next((str(ws.cell(r, c).value) for c in range(3, 8)
                         if str(ws.cell(r, c).value or "").startswith("http")), None)
            sub = Submission(category="strategic_plan", cycle=cycle, submitted_by=user, source=Submission.Source.EXCEL,
                             import_batch=batch, import_ref=f"Index-D!{r}", status=Submission.Status.VERIFIED,
                             data={"title": title, **({"evidence_link": link} if link else {}),
                                   "_source": {"row": [text(ws.cell(r, c).value) for c in range(1, 6)]}},
                             verified_at=timezone.now(), verified_by=user)
            sub.promote()
            sub.save()
            res.created += 1
            res.per_table["D.ia"] = {"category": "strategic_plan", "rows": 1}
            return
