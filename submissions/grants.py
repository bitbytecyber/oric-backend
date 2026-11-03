"""Map free-text grant scheme / funding agency answers onto the dropdown values in the registry.

Older records (and the HEC workbooks) typed both into "Name of research grant", e.g. "NEDAASC 2023-24" or
"National Research Program for Universities (NRPU)". Anything that does not clearly map keeps its own text,
which the form shows as "Others…" with that text.
"""
from __future__ import annotations

import re

from .registry import FUNDING_AGENCIES, GRANT_SCHEMES

GRANT_CATEGORIES = frozenset(f"{p}_{s}" for p in ("grant_hec", "grant_nonhec", "joint")
                             for s in ("submitted", "approved", "completed"))

SCHEME_PATTERNS = [
    ("NRPU", r"\bnrpu\b|national research progra(m|mme) for universities"),
    ("GCF", r"\bgcf\b|grand challenge fund"),
    ("TTSF", r"\bttsf\b|technology transfer support fund"),
    ("TDF", r"\btdf\b|technology development fund"),
    ("ICRG", r"\bicrg\b|international collaborative research grant"),
    ("LCF", r"\blcf\b|local challenge fund"),
]
AGENCY_PATTERNS = [
    ("NEDAASC", r"nedaasc|ned alumi?ni? association (of )?southern california"),
    ("Sindh HEC", r"sindh\s*hec|sindh higher education|\bsrsp\b"),
    ("UNESCO", r"\bunesco\b"),
    ("European Commission", r"european commission|erasmus|horizon 2020|horizon europe|\beu\b"),
    ("MoST", r"\bmost\b|ministry of science"),
    ("HEC", r"\bhec\b|higher education commission|\bsrgp\b|\btrg\b"),
    ("NED", r"\bned\b.*(as&?rb|research grant|seed)|^as&?rb\b|seed fund(ing)? neduet|\bneduet\b|^ned\b"),
]


def _first(patterns, text: str) -> str | None:
    """First pattern in list order wins (NEDAASC before NED, Sindh HEC before HEC)."""
    return next((value for value, rx in patterns if re.search(rx, text, re.I)), None)


def scheme_for(name) -> str | None:
    return _first(SCHEME_PATTERNS, str(name or "").strip())


def agency_for(text) -> str | None:
    return _first(AGENCY_PATTERNS, str(text or "").strip())


def normalize_grant_data(category: str, data: dict) -> dict:
    """Return a copy of ``data`` with ``research_grant_name`` / ``funding_agency`` on dropdown values where clear."""
    if category not in GRANT_CATEGORIES:
        return data
    d = dict(data)
    name = (d.get("research_grant_name") or "").strip()
    agency = (d.get("funding_agency") or "").strip()
    scheme = scheme_for(name)
    if scheme and name not in GRANT_SCHEMES:
        d["research_grant_name"] = scheme
    if agency and agency not in FUNDING_AGENCIES:
        d["funding_agency"] = agency_for(agency) or agency
    elif not agency:
        guess = ("HEC" if scheme or category.startswith("grant_hec") else agency_for(name))
        if guess:
            d["funding_agency"] = guess
    return d
