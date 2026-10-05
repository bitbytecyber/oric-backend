"""
Capability checks.

Mirrors sis_backend/rbac/utils.py. Two rules carried over deliberately:

1. Queries START FROM RoleAssignment so the role, its capability and its scope
   are matched on the *same row* (chaining filters across multi-valued joins
   leaked access across campuses in sis_backend once).
2. A check without a department (``department_id=None``) means "holds the key in
   ANY scope". Row isolation therefore comes from queryset scoping
   (``capability_scope_q``), which every list/detail endpoint applies.
"""
from __future__ import annotations

from django.db.models import Q

from .models import RoleAssignment

UNMAPPED = "__unmapped__"
ALL = "all"


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
        qs = qs.filter(Q(department_id=department_id) | Q(department__isnull=True))
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


def capability_scopes(user, capability_key: str) -> list[tuple[int | None, list[str]]]:
    """[(department_id or None=all, pillars or []=all), …] for every active assignment granting the key."""
    memo = user.__dict__.setdefault("_rbac_scopes", {})
    if capability_key in memo:
        return memo[capability_key]
    rows = (
        _active_assignments(user)
        .filter(role__capabilities__key=capability_key)
        .values_list("department_id", "role__pillars")
        .distinct()
    )
    scopes = [(dept, list(pillars or [])) for dept, pillars in rows]
    memo[capability_key] = scopes
    return scopes


def capability_department_ids(user, capability_key: str):
    """``"all"`` when any granting assignment is global, else the list of department ids."""
    if user.is_superuser:
        return ALL
    scopes = capability_scopes(user, capability_key)
    if any(dept is None for dept, _ in scopes):
        return ALL
    return sorted({dept for dept, _ in scopes})


def capability_scope_q(user, capability_key: str, *, department_field: str | None = "department_id",
                       pillar_field: str | None = None) -> Q | None:
    """Q selecting rows the user may act on with this key.

    Returns ``None`` for unrestricted access, ``Q(pk__in=[])`` for none.
    Each assignment contributes (department AND pillar) — same-row semantics.
    """
    if user.is_superuser:
        return None
    scopes = capability_scopes(user, capability_key)
    if not scopes:
        return Q(pk__in=[])
    q = Q(pk__in=[])
    for dept, pillars in scopes:
        part = Q()
        if dept is not None and department_field:
            part &= Q(**{department_field: dept})
        if pillars and pillar_field:
            part &= Q(**{f"{pillar_field}__in": pillars})
        if not part:  # unrestricted assignment
            return None
        q |= part
    return q


def user_can_on(user, capability_key: str, *, department_id: int | None, pillar: str | None = None) -> bool:
    """Object-level check against one row's department / pillar."""
    if user.is_superuser:
        return True
    for dept, pillars in capability_scopes(user, capability_key):
        if dept is not None and dept != department_id:
            continue
        if pillars and pillar is not None and pillar not in pillars:
            continue
        return True
    return False


def users_with_capability(capability_key: str, *, department_id: int | None = None, pillar: str | None = None):
    """Active users holding the key in scope of a department/pillar (for notifications)."""
    from django.contrib.auth import get_user_model

    qs = RoleAssignment.objects.filter(is_active=True, user__is_active=True, role__capabilities__key=capability_key)
    if department_id is not None:
        qs = qs.filter(Q(department_id=department_id) | Q(department__isnull=True))
    ids = set()
    for user_id, pillars in qs.values_list("user_id", "role__pillars"):
        if pillar and pillars and pillar not in pillars:
            continue
        ids.add(user_id)
    return get_user_model().objects.filter(pk__in=ids, is_active=True)
