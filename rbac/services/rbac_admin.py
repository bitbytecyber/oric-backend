"""RBAC admin business rules: privilege-escalation, scope, self-lockout and system-role guards."""
from __future__ import annotations

from oric_backend.errors import (
    InsufficientPermissionError,
    PrivilegeEscalationError,
    SelfLockoutError,
    SystemRoleProtectedError,
)
from rbac.models import Capability, RoleAssignment
from rbac.utils import ALL, capability_department_ids, user_capability_keys

MANAGE = "rbac.manage"


def actor_capability_keys(actor) -> set[str]:
    if actor.is_superuser:
        return set(Capability.objects.values_list("key", flat=True))
    return set(user_capability_keys(actor))


def validate_capability_grant(actor, keys: set[str]) -> None:
    if actor.is_superuser:
        return
    missing = set(keys) - actor_capability_keys(actor)
    if missing:
        raise PrivilegeEscalationError(details={"missing_capabilities": sorted(missing)})


def _check_department_scope(actor, department_id: int | None, key: str) -> None:
    if actor.is_superuser:
        return
    scope = capability_department_ids(actor, key)
    if scope == ALL:
        return
    if department_id is None or department_id not in scope:
        raise InsufficientPermissionError(
            required_permission=key,
            message="You can only assign roles within your own department(s).",
        )


def _holds_manage_elsewhere(actor, exclude_pk=None) -> bool:
    qs = RoleAssignment.objects.filter(user=actor, is_active=True, role__capabilities__key=MANAGE)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def validate_assignment_create(actor, *, role, department_id: int | None) -> None:
    validate_capability_grant(actor, set(role.capabilities.values_list("key", flat=True)))
    _check_department_scope(actor, department_id, "role_assignment.add")


def validate_assignment_change(actor, assignment, *, new_role=None, new_department_id=..., is_active=None) -> None:
    if actor.is_superuser:
        return
    role = new_role or assignment.role
    dept = assignment.department_id if new_department_id is ... else new_department_id
    validate_capability_grant(actor, set(role.capabilities.values_list("key", flat=True)))
    _check_department_scope(actor, dept, "role_assignment.change")
    removing_manage = (
        assignment.user_id == actor.id
        and assignment.role.capabilities.filter(key=MANAGE).exists()
        and (is_active is False or (new_role is not None and not new_role.capabilities.filter(key=MANAGE).exists()))
    )
    if removing_manage and not _holds_manage_elsewhere(actor, exclude_pk=assignment.pk):
        raise SelfLockoutError()


def validate_assignment_delete(actor, assignment) -> None:
    validate_assignment_change(actor, assignment, is_active=False)


def validate_role_capabilities_update(actor, role, new_keys: set[str]) -> None:
    validate_capability_grant(actor, new_keys)
    if actor.is_superuser:
        return
    if MANAGE not in new_keys and RoleAssignment.objects.filter(
        user=actor, role=role, is_active=True
    ).exists() and role.capabilities.filter(key=MANAGE).exists() and not _holds_manage_elsewhere_via_other_role(
        actor, role
    ):
        raise SelfLockoutError(message="Cannot remove rbac.manage from a role you rely on.")


def _holds_manage_elsewhere_via_other_role(actor, role) -> bool:
    return RoleAssignment.objects.filter(user=actor, is_active=True, role__capabilities__key=MANAGE).exclude(
        role=role
    ).exists()


def validate_role_update(actor, role, data: dict) -> None:
    if role.is_system and "slug" in data and data["slug"] != role.slug:
        raise SystemRoleProtectedError()


def validate_role_delete(actor, role) -> None:
    if role.is_system:
        raise SystemRoleProtectedError()
    if not actor.is_superuser and RoleAssignment.objects.filter(user=actor, role=role, is_active=True).exists():
        raise SelfLockoutError(message="You cannot delete a role you are assigned to.")
