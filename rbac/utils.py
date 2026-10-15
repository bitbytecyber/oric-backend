"""
Capability checks.

Mirrors sis_backend/rbac/utils.py. Two rules carried over deliberately:

1. Queries START FROM RoleAssignment so the role, its capability and its scope
   are matched on the *same row* (chaining filters across multi-valued joins
   leaked access across campuses in sis_backend once).
2. A check without a department (``department_id=None``) means "holds the key in
   ANY scope". Row isolation therefore comes from queryset scoping
   (``capability_scope_q``), which every list/detail endpoint applies.

Scopes (one per active assignment granting a key):
  * organisational: ``department`` (Chairman) or ``faculty`` (Dean) or neither
    (global: ORIC);
  * subject: role ``pillars`` / ``categories`` (ORIC managers); a row matches when
    its pillar is in ``pillars`` OR its category is in ``categories``; both
    empty = every subject.
"""
from __future__ import annotations

from typing import NamedTuple

from django.db.models import Q

from .models import RoleAssignment

UNMAPPED = "__unmapped__"
ALL = "all"


class Scope(NamedTuple):
    department_id: int | None
    faculty_id: int | None
    pillars: tuple
    categories: tuple

    @property
    def is_global(self) -> bool:
        return self.department_id is None and self.faculty_id is None

    @property
    def any_subject(self) -> bool:
        return not self.pillars and not self.categories

    def subject_ok(self, pillar: str | None, category: str | None) -> bool:
        if self.any_subject:
            return True
        return (pillar is not None and pillar in self.pillars) or (category is not None and category in self.categories)


def _active_assignments(user):
    return RoleAssignment.objects.filter(user=user, is_active=True, user__is_active=True)


def user_capability_keys(user, *, department_id: int | None = None) -> frozenset[str]:
    """All keys the user holds (in any scope, or within one department). Memoised per user instance."""
    if not user or not user.is_authenticated:
        return frozenset()
    memo = user.__dict__.setdefault("_rbac_capability_keys", {})
    if department_id in memo:
        return memo[department_id]
    qs = _active_assignments(user)
    if department_id is not None:
        from org.models import Department

        fac = Department.objects.filter(pk=department_id).values_list("faculty_id", flat=True).first()
        qs = qs.filter(Q(department_id=department_id) | Q(faculty_id=fac, faculty__isnull=False)
                       | Q(department__isnull=True, faculty__isnull=True))
    keys = frozenset(
        qs.exclude(role__capabilities__key=None).values_list("role__capabilities__key", flat=True).distinct()
    )
    memo[department_id] = keys
    return keys


def forget_capabilities(user) -> None:
    user.__dict__.pop("_rbac_capability_keys", None)
    user.__dict__.pop("_rbac_scopes", None)


def user_has_capability(user, capability_key: str | None, *, department_id: int | None = None) -> bool:
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    if not capability_key or capability_key == UNMAPPED:
        return False
    return capability_key in user_capability_keys(user, department_id=department_id)


def capability_scopes(user, capability_key: str) -> list[Scope]:
    """Every active assignment scope granting the key."""
    memo = user.__dict__.setdefault("_rbac_scopes", {})
    if capability_key in memo:
        return memo[capability_key]
    rows = (
        _active_assignments(user)
        .filter(role__capabilities__key=capability_key)
        .values_list("department_id", "faculty_id", "role__pillars", "role__categories")
        .distinct()
    )
    scopes = list({Scope(d, f, tuple(sorted(p or [])), tuple(sorted(c or []))) for d, f, p, c in rows})
    memo[capability_key] = scopes
    return scopes


def capability_department_ids(user, capability_key: str):
    """``"all"`` when any granting assignment is global, else the list of department ids (faculty expanded)."""
    if user.is_superuser:
        return ALL
    scopes = capability_scopes(user, capability_key)
    if any(s.is_global for s in scopes):
        return ALL
    from org.models import Department

    ids = {s.department_id for s in scopes if s.department_id}
    fac_ids = {s.faculty_id for s in scopes if s.faculty_id}
    if fac_ids:
        ids |= set(Department.objects.filter(faculty_id__in=fac_ids).values_list("pk", flat=True))
    return sorted(ids)


def capability_scope_q(user, capability_key: str, *, department_field: str | None = "department_id",
                       faculty_field: str | None = None, pillar_field: str | None = None,
                       category_field: str | None = None, org_q=None) -> Q | None:
    """Q selecting rows the user may act on with this key.

    Returns ``None`` for unrestricted access, ``Q(pk__in=[])`` for none.
    Each assignment contributes (org scope AND subject scope) — same-row semantics.
    ``org_q(department_id=…, faculty_id=…)`` may replace the simple field lookups
    (submissions use it to match any contributor's department).
    """
    if user.is_superuser:
        return None
    scopes = capability_scopes(user, capability_key)
    if not scopes:
        return Q(pk__in=[])
    q = Q(pk__in=[])
    for s in scopes:
        part = Q()
        if not s.is_global:
            if org_q is not None:
                part &= org_q(department_id=s.department_id, faculty_id=s.faculty_id)
            elif s.department_id is not None and department_field:
                part &= Q(**{department_field: s.department_id})
            elif s.faculty_id is not None:
                field = faculty_field or (department_field.replace("_id", "") + "__faculty_id"
                                          if department_field else None)
                if field:
                    part &= Q(**{field: s.faculty_id})
        if not s.any_subject:
            subj = Q()
            if s.pillars and pillar_field:
                subj |= Q(**{f"{pillar_field}__in": s.pillars})
            if s.categories and category_field:
                subj |= Q(**{f"{category_field}__in": s.categories})
            if subj:
                part &= subj
        if not part:  # unrestricted assignment
            return None
        q |= part
    return q


def user_can_on(user, capability_key: str, *, department_ids=None, faculty_ids=None, pillar: str | None = None,
                category: str | None = None, department_id: int | None = None) -> bool:
    """Object-level check against one row's departments/faculties and subject."""
    if user.is_superuser:
        return True
    dept_ids = set(department_ids or ())
    if department_id is not None:
        dept_ids.add(department_id)
    fac_ids = set(faculty_ids or ())
    if dept_ids and not fac_ids:
        from org.models import Department

        fac_ids = set(Department.objects.filter(pk__in=dept_ids).values_list("faculty_id", flat=True)) - {None}
    for s in capability_scopes(user, capability_key):
        if s.department_id is not None and s.department_id not in dept_ids:
            continue
        if s.faculty_id is not None and s.faculty_id not in fac_ids:
            continue
        if not s.subject_ok(pillar, category):
            continue
        return True
    return False


def users_with_capability(capability_key: str, *, department_id: int | None = None, pillar: str | None = None,
                          category: str | None = None, global_only: bool = False):
    """Active users holding the key in scope of a department/subject (for notifications)."""
    from django.contrib.auth import get_user_model

    qs = RoleAssignment.objects.filter(is_active=True, user__is_active=True, role__capabilities__key=capability_key)
    if global_only:
        qs = qs.filter(department__isnull=True, faculty__isnull=True)
    elif department_id is not None:
        from org.models import Department

        fac = Department.objects.filter(pk=department_id).values_list("faculty_id", flat=True).first()
        qs = qs.filter(Q(department_id=department_id) | Q(faculty_id=fac, faculty__isnull=False)
                       | Q(department__isnull=True, faculty__isnull=True))
    ids = set()
    for user_id, pillars, cats in qs.values_list("user_id", "role__pillars", "role__categories"):
        s = Scope(None, None, tuple(pillars or []), tuple(cats or []))
        if (pillar or category) and not s.subject_ok(pillar, category):
            continue
        ids.add(user_id)
    return get_user_model().objects.filter(pk__in=ids, is_active=True)
