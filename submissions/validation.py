"""Validate entry/count payloads against the form registry."""
import datetime
import re
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError

from .registry import DEPARTMENTS, PILLAR_BY_KEY, SECTION_BY_KEY

URL_RE = re.compile(r"^(https?://|doi:|10\.)\S+$", re.I)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALLOWED_EVIDENCE_TYPES = {
    "application/pdf", "image/png", "image/jpeg", "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024


def file_fields(section_key: str) -> list[dict]:
    return [f for f in SECTION_BY_KEY[section_key]["fields"] if f["type"] == "file"]


def clean_value(field: dict, raw):
    """Return the normalised value or raise ValueError with a human message."""
    t = field["type"]
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    if isinstance(raw, str):
        raw = raw.strip()
    if t in ("text", "textarea"):
        return str(raw)[:5000]
    if t == "email":
        if not EMAIL_RE.match(str(raw)):
            raise ValueError("Enter a valid email address.")
        return str(raw).lower()
    if t == "url":
        if not URL_RE.match(str(raw)):
            raise ValueError("Enter a valid link (http(s)://… or a DOI).")
        return str(raw)
    if t == "date":
        try:
            return datetime.date.fromisoformat(str(raw)[:10]).isoformat()
        except ValueError:
            raise ValueError("Enter a valid date (YYYY-MM-DD).")
    if t == "int":
        try:
            v = int(str(raw))
        except ValueError:
            raise ValueError("Enter a whole number.")
        if v < 0:
            raise ValueError("Cannot be negative.")
        return v
    if t == "decimal":
        try:
            v = Decimal(str(raw).replace(",", ""))
        except InvalidOperation:
            raise ValueError("Enter a number.")
        if v < 0:
            raise ValueError("Cannot be negative.")
        return float(v)
    if t == "department":
        if raw not in DEPARTMENTS:
            raise ValueError("Pick a department from the list.")
        return raw
    if t in ("select", "radio"):
        options = field.get("options") or []
        if raw in options:
            return raw
        # radio with "Other" accepts free text
        if field.get("other") and isinstance(raw, str) and raw:
            return raw[:200]
        raise ValueError(f"Choose one of: {', '.join(options)}.")
    return raw


def validate_entry_data(section_key: str, data: dict, *, existing_files: set[str], incoming_files: set[str],
                        partial: bool = False) -> dict:
    if section_key not in SECTION_BY_KEY:
        raise ValidationError({"section": "Unknown section."})
    section = SECTION_BY_KEY[section_key]
    errors, cleaned = {}, {}
    for f in section["fields"]:
        name = f["name"]
        if f["type"] == "file":
            if f["required"] and name not in existing_files and name not in incoming_files and not partial:
                errors[name] = "This file is required."
            continue
        if partial and name not in data:
            continue
        try:
            value = clean_value(f, data.get(name))
        except ValueError as exc:
            errors[name] = str(exc)
            continue
        if value is None and f["required"]:
            errors[name] = "This field is required."
            continue
        cleaned[name] = value

    # cross-field rules
    s, e = cleaned.get("start_date"), cleaned.get("end_date")
    if s and e and e < s:
        errors["end_date"] = "End date cannot be before the start date."
    if section_key == "B2" and cleaned.get("filed_or_granted") == "Granted":
        if not cleaned.get("granting_authority") and not partial:
            errors["granting_authority"] = "Required when the patent is granted."
    if errors:
        raise ValidationError(errors)
    return cleaned


def validate_counts(pillar: str, counts: dict) -> dict:
    p = PILLAR_BY_KEY[pillar]
    errors, cleaned = {}, {}
    for f in p["counts"]:
        raw = counts.get(f["name"], 0)
        try:
            v = int(raw or 0)
            if v < 0 or v > 999:
                raise ValueError
            cleaned[f["name"]] = v
        except (TypeError, ValueError):
            errors[f["name"]] = "Enter a whole number between 0 and 999."
    if errors:
        raise ValidationError({"counts": errors})
    return cleaned


def validate_upload(f):
    if f.size > MAX_EVIDENCE_BYTES:
        raise ValidationError(f"{f.name}: file is larger than 10 MB.")
    ctype = getattr(f, "content_type", "") or ""
    if ctype not in ALLOWED_EVIDENCE_TYPES:
        raise ValidationError(f"{f.name}: only PDF, Word or image files are accepted.")
