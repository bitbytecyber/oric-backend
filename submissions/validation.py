"""Validate submission payloads against the category registry."""
import datetime
import re
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError

from .registry import CATEGORY_BY_KEY

URL_RE = re.compile(r"^(https?://|doi:|10\.)\S+$", re.I)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALLOWED_EVIDENCE_TYPES = {
    "application/pdf", "image/png", "image/jpeg", "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024


def file_fields(category: str) -> list[dict]:
    return [f for f in CATEGORY_BY_KEY[category]["fields"] if f["type"] == "file"]


def clean_value(field: dict, raw):
    """Return the normalised value or raise ValueError with a human message."""
    t = field["type"]
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    if isinstance(raw, str):
        raw = raw.strip()
    if t in ("text", "textarea", "org"):
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
    if t in ("select", "radio"):
        options = field.get("options") or []
        if raw in options:
            return raw
        # radio with "Other" accepts free text
        if field.get("other") and isinstance(raw, str) and raw:
            return raw[:200]
        raise ValueError(f"Choose one of: {', '.join(options)}.")
    return raw


def validate_data(category: str, data: dict, *, existing_files: set[str] = frozenset(),
                  incoming_files: set[str] = frozenset(), draft: bool = False) -> dict:
    """Clean ``data`` for ``category``. ``draft=True`` skips "required" checks (drafts may be incomplete)."""
    if category not in CATEGORY_BY_KEY:
        raise ValidationError({"category": "Unknown category."})
    c = CATEGORY_BY_KEY[category]
    errors, cleaned = {}, {}
    for f in c["fields"]:
        name = f["name"]
        if f["type"] == "file":
            if f["required"] and not draft and name not in existing_files and name not in incoming_files                     and not data.get("evidence_link"):
                errors[name] = "Attach the file or paste an evidence link."
            continue
        try:
            value = clean_value(f, data.get(name))
        except ValueError as exc:
            errors[name] = str(exc)
            continue
        if value is None:
            if f["required"] and not draft:
                errors[name] = "This field is required."
            continue
        cleaned[name] = value

    s, e = cleaned.get("start_date"), cleaned.get("end_date")
    if s and e and e < s:
        errors["end_date"] = "End date cannot be before the start date."
    if errors:
        raise ValidationError({"data": errors})
    return cleaned


def validate_people(category: str, people: list[dict], *, draft: bool = False) -> list[dict]:
    """``people`` = [{role, person_id?, name?, designation?, affiliation?}] matching the category's slots."""
    c = CATEGORY_BY_KEY[category]
    slots = {p["role"]: p for p in c["people"]}
    out, errors = [], {}
    for i, raw in enumerate(people or []):
        role = raw.get("role")
        slot = slots.get(role)
        if not slot:
            errors[str(i)] = f"Unknown role '{role}' for this category."
            continue
        pid = raw.get("person_id") or raw.get("person")
        name = (raw.get("name") or "").strip()
        if not pid and not name:
            continue
        if not pid and not slot["external"] and not slot["lead"]:
            errors[str(i)] = f"{slot['label']} must be a NED colleague."
            continue
        out.append({"role": role, "person_id": int(pid) if pid else None, "name": name[:255],
                    "designation": (raw.get("designation") or "")[:120],
                    "affiliation": (raw.get("affiliation") or "")[:255]})
    for role, slot in slots.items():
        n = sum(1 for p in out if p["role"] == role)
        if not slot["many"] and n > 1:
            errors[role] = f"Only one {slot['label']}."
        if slot["required"] and not slot["lead"] and n == 0 and not draft:
            errors[role] = f"{slot['label']} is required."
    if errors:
        raise ValidationError({"people": errors})
    return out


def validate_upload(f):
    if f.size > MAX_EVIDENCE_BYTES:
        raise ValidationError(f"{f.name}: file is larger than 10 MB.")
    ctype = getattr(f, "content_type", "") or ""
    if ctype not in ALLOWED_EVIDENCE_TYPES:
        raise ValidationError(f"{f.name}: only PDF, Word or image files are accepted.")
