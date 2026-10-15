"""Directory import (faculties, departments, people, ORIC staff) and leadership role sync.

Source of truth: ``org/seed/*.csv`` (built by ``tools/build_directory.py``), or the
same four CSVs uploaded in the Import Center. Import is idempotent: rows are
upserted by code (faculty / department) or email (people), and a dry run reports
exactly what would change.

Leadership roles are *derived*: Faculty.dean → ``dean`` scoped to that faculty,
Department.chair / co_chairs → ``chairman`` scoped to that department, every
teaching person → ``faculty``. ``sync_leadership_roles`` reconciles those
``auto`` assignments; hand-made assignments are never touched.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.db import transaction

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
FILES = ("faculties.csv", "departments.csv", "people.csv", "oric_staff.csv")


@dataclass
class Diff:
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    unchanged: int = 0
    errors: list = field(default_factory=list)

    def as_dict(self):
        return {"created": len(self.created), "updated": len(self.updated), "unchanged": self.unchanged,
                "errors": self.errors[:200], "created_items": self.created[:200], "updated_items": self.updated[:200]}


def _rows(text: str | None) -> list[dict]:
    if not text:
        return []
    text = text.lstrip("﻿")
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(io.StringIO(text))]


def read_seed_dir(path: Path = SEED_DIR) -> dict[str, str]:
    return {name: (path / name).read_text(encoding="utf-8") for name in FILES if (path / name).exists()}


def _bool(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def _apply(obj, values: dict) -> list[str]:
    changed = []
    for k, v in values.items():
        if getattr(obj, k) != v:
            setattr(obj, k, v)
            changed.append(k)
    return changed


class _Rollback(Exception):
    pass


def import_directory(files: dict[str, str], *, dry_run: bool = False, password: str | None = None) -> dict:
    """Upsert the directory from CSV texts keyed by file name. Returns a per-file diff."""
    result: dict = {}
    try:
        with transaction.atomic():
            result = _import(files, password=password, dry_run=dry_run)
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    result["dry_run"] = dry_run
    return result


SEED_PHOTOS = "people/avatars/seed"  # under MEDIA_ROOT; filled by tools/scrape_photos.py, copied on deploy


def _attach_photo(person, name: str, dry_run: bool) -> bool:
    """Link the seed portrait MEDIA_ROOT/people/avatars/seed/<name> as the avatar.

    The file is referenced in place, not copied. Photos a person uploaded themselves are never replaced;
    an earlier seed link is updated.
    """
    if not name:
        return False
    target = f"{SEED_PHOTOS}/{name}"
    current = person.avatar.name if person.avatar else ""
    if current == target or (current and not current.startswith("people/avatars/seed")):
        return False
    if not (Path(settings.MEDIA_ROOT) / target).is_file():
        return False
    if not dry_run:
        person.avatar.name = target
        person.save(update_fields=["avatar"])
    return True


def _import(files: dict[str, str], *, password: str | None, dry_run: bool = False) -> dict:
    from org.models import Department, Faculty, TeamMember
    from people.models import Person, User
    from people.services.profile import provision_user
    from rbac.models import AccessRole, RoleAssignment

    out = {}
    password = password or getattr(settings, "ORIC_DEMO_PASSWORD", None) or None

    # --- faculties (dean resolved after people) ---------------------------------------
    fac_rows = _rows(files.get("faculties.csv"))
    d = Diff()
    for i, r in enumerate(fac_rows):
        if not r.get("code") or not r.get("name"):
            d.errors.append(f"faculties.csv row {i + 2}: code and name are required")
            continue
        obj = Faculty.objects.filter(code=r["code"]).first()
        vals = {"name": r["name"], "short_name": r.get("short_name", ""), "order": i}
        if obj is None:
            Faculty.objects.create(code=r["code"], **vals)
            d.created.append(r["code"])
        elif _apply(obj, vals):
            obj.save()
            d.updated.append(r["code"])
        else:
            d.unchanged += 1
    out["faculties"] = d

    # --- departments --------------------------------------------------------------------
    d = Diff()
    dept_rows = _rows(files.get("departments.csv"))
    faculties = {f.code: f for f in Faculty.objects.all()}
    for i, r in enumerate(dept_rows):
        if not r.get("code") or not r.get("name"):
            d.errors.append(f"departments.csv row {i + 2}: code and name are required")
            continue
        fac = faculties.get(r.get("faculty_code", ""))
        if r.get("faculty_code") and not fac:
            d.errors.append(f"departments.csv row {i + 2}: unknown faculty_code {r['faculty_code']}")
        vals = {"name": r["name"], "faculty": fac, "website": r.get("website", ""), "is_active": True}
        obj = Department.objects.filter(code=r["code"]).first() or Department.objects.filter(name=r["name"]).first()
        if obj is None:
            Department.objects.create(code=r["code"], **vals)
            d.created.append(r["code"])
        else:
            ch = _apply(obj, {**vals, "code": r["code"]})
            if ch:
                obj.save()
                d.updated.append(f"{r['code']} ({', '.join(ch)})")
            else:
                d.unchanged += 1
    out["departments"] = d

    # --- people -------------------------------------------------------------------------------
    d = Diff()
    depts = {x.code: x for x in Department.objects.all()}
    staff_rows = _rows(files.get("oric_staff.csv"))
    people_rows = _rows(files.get("people.csv"))
    seen_emails = {r.get("email", "").lower() for r in people_rows}
    for r in staff_rows:  # ORIC staff that are not also faculty become non-teaching people
        if r.get("email") and r["email"].lower() not in seen_emails:
            people_rows.append({"email": r["email"], "full_name": r.get("full_name", ""),
                                "designation": r.get("title", ""), "department_code": r.get("department_code", ""),
                                "is_phd": "1" if "Dr." in r.get("full_name", "") else "0",
                                "email_source": "oric", "source": "oric_staff", "is_faculty": "0"})
    photos = 0
    for i, r in enumerate(people_rows):
        email = (r.get("email") or "").lower()
        if not email or not r.get("full_name"):
            d.errors.append(f"people.csv row {i + 2}: email and full_name are required")
            continue
        dept = depts.get(r.get("department_code", ""))
        if r.get("department_code") and not dept:
            d.errors.append(f"people.csv row {i + 2}: unknown department_code {r['department_code']}")
        aliases = [a.strip() for a in (r.get("aliases") or "").split(";") if a.strip()]
        person_vals = {
            "full_name": r["full_name"], "designation": r.get("designation", ""), "department": dept,
            "is_phd": _bool(r.get("is_phd", "")), "aliases": aliases,
            "email_source": r.get("email_source", ""), "source": r.get("source", ""),
            "is_faculty": r.get("is_faculty", "1") not in {"0", "false", "no"},
            "phone": r.get("phone", ""),
        }
        if r.get("employee_id"):
            person_vals["employee_id"] = r["employee_id"]
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = provision_user(email=email, full_name=r["full_name"], password=password,
                                  designation=r.get("designation", ""), department=dept,
                                  must_change_password=bool(password))
            person = user.person
            _apply(person, person_vals)
            person.save()
            d.created.append(email)
        else:
            person = Person.objects.filter(user=user).first() or Person(user=user)
            ch = _apply(person, person_vals)
            if ch or person.pk is None:
                person.save()
                d.updated.append(f"{email} ({', '.join(ch)})")
            else:
                d.unchanged += 1
        photos += _attach_photo(person, r.get("photo", ""), dry_run)
    out["people"] = d

    # --- leadership links ------------------------------------------------------------------
    d = Diff()
    by_email = {p.user.email.lower(): p for p in Person.objects.select_related("user").filter(user__isnull=False)}
    for r in fac_rows:
        fac = Faculty.objects.filter(code=r.get("code")).first()
        if not fac:
            continue
        dean = by_email.get((r.get("dean_email") or "").lower())
        if r.get("dean_email") and not dean:
            d.errors.append(f"faculty {fac.code}: dean {r['dean_email']} not in people.csv")
        if fac.dean_id != (dean.pk if dean else None):
            fac.dean = dean
            fac.save(update_fields=["dean"])
            d.updated.append(f"{fac.code} dean")
    for r in dept_rows:
        dept = Department.objects.filter(code=r.get("code")).first()
        if not dept:
            continue
        chair = by_email.get((r.get("chair_email") or "").lower())
        if r.get("chair_email") and not chair:
            d.errors.append(f"department {dept.code}: chair {r['chair_email']} not in people.csv")
        if dept.chair_id != (chair.pk if chair else None):
            dept.chair = chair
            dept.save(update_fields=["chair"])
            d.updated.append(f"{dept.code} chair")
        co = [by_email[e.strip().lower()] for e in (r.get("co_chair_emails") or "").split(";")
              if e.strip() and e.strip().lower() in by_email]
        if set(dept.co_chairs.values_list("pk", flat=True)) != {p.pk for p in co}:
            dept.co_chairs.set(co)
            d.updated.append(f"{dept.code} co-chairs")
    out["leadership"] = d

    # --- ORIC staff roles + team page ---------------------------------------------------------
    d = Diff()
    roles = {r.slug: r for r in AccessRole.objects.all()}
    for i, r in enumerate(staff_rows):
        user = User.objects.filter(email__iexact=r.get("email", "")).first()
        role = roles.get(r.get("role", ""))
        if not user:
            continue
        if role and r.get("role") != "oric_staff":
            _, created = RoleAssignment.objects.get_or_create(
                user=user, role=role, department=None, faculty=None, is_active=True,
                defaults={"note": "ORIC staff (directory)"})
            if created:
                d.created.append(f"{user.email} → {role.slug}")
        TeamMember.objects.update_or_create(
            name=r.get("full_name", ""),
            defaults={"title": r.get("title", ""), "email": r.get("email", "") if "placeholder" not in r.get(
                "email", "") else "", "order": int(r.get("order") or i)})
    out["oric_staff"] = d

    sync = sync_leadership_roles()
    out = {k: v.as_dict() for k, v in out.items()}
    out["photos"] = {"attached": photos}
    out["roles"] = sync
    return out


def sync_leadership_roles() -> dict:
    """Reconcile ``auto`` role assignments with the directory (dean / chairman / faculty)."""
    from org.models import Department, Faculty
    from people.models import Person
    from rbac.models import AccessRole, RoleAssignment

    roles = {r.slug: r for r in AccessRole.objects.filter(slug__in=["dean", "chairman", "faculty"])}
    if len(roles) < 3:
        return {"skipped": "roles not seeded"}
    wanted: set[tuple] = set()
    for f in Faculty.objects.filter(dean__user__isnull=False).select_related("dean"):
        wanted.add((f.dean.user_id, roles["dean"].pk, None, f.pk))
    for dept in Department.objects.prefetch_related("co_chairs").select_related("chair"):
        for p in [dept.chair, *dept.co_chairs.all()]:
            if p and p.user_id:
                wanted.add((p.user_id, roles["chairman"].pk, dept.pk, None))
    for uid in Person.objects.filter(is_faculty=True, user__isnull=False).values_list("user_id", flat=True):
        wanted.add((uid, roles["faculty"].pk, None, None))

    have = {
        (a.user_id, a.role_id, a.department_id, a.faculty_id): a
        for a in RoleAssignment.objects.filter(auto=True, role__in=roles.values(), is_active=True)
    }
    created = removed = 0
    for key in wanted - set(have):
        uid, rid, dept_id, fac_id = key
        exists = RoleAssignment.objects.filter(user_id=uid, role_id=rid, department_id=dept_id, faculty_id=fac_id,
                                               is_active=True).exists()
        if not exists:
            RoleAssignment.objects.create(user_id=uid, role_id=rid, department_id=dept_id, faculty_id=fac_id,
                                          auto=True, note="From directory")
            created += 1
    for key in set(have) - wanted:
        have[key].delete()
        removed += 1
    if created or removed:
        from rbac.cache import bump_rbac_version

        bump_rbac_version()
    return {"created": created, "removed": removed}
