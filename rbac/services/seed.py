"""Idempotent catalog sync + role seeding (used by migrations and `seed_rbac`)."""
from __future__ import annotations

from django.db import transaction

from rbac.capability_catalog import CAPABILITY_CATALOG, ROLE_DEFS, expand_patterns


def sync_capabilities(Capability=None) -> int:
    """update_or_create one Capability row per catalog entry; returns the count."""
    if Capability is None:
        from rbac.models import Capability
    for c in CAPABILITY_CATALOG:
        Capability.objects.update_or_create(
            key=c.key,
            defaults={"name": c.name, "description": c.description, "module": c.module, "resource": c.resource,
                      "action": c.action, "is_dangerous": c.is_dangerous},
        )
    return len(CAPABILITY_CATALOG)


def role_keys(role_def: dict) -> set[str]:
    patterns = role_def["patterns"]
    return expand_patterns(patterns, allow_never="rbac.manage" in patterns)


@transaction.atomic
def seed_roles(*, reconcile: bool = True, AccessRole=None, Capability=None, RoleCapability=None) -> None:
    """Upsert built-in roles. ``reconcile=True`` also removes grants not in the catalog definition
    (destructive for hand-added grants on system roles); ``False`` is additive only."""
    if AccessRole is None:
        from rbac.models import AccessRole, Capability, RoleCapability
    caps = {c.key: c for c in Capability.objects.all()}
    for rd in ROLE_DEFS:
        role, _ = AccessRole.objects.update_or_create(
            slug=rd["slug"],
            defaults={"name": rd["name"], "description": rd.get("description", ""),
                      "is_system": rd.get("is_system", True), "pillars": rd.get("pillars", [])},
        )
        wanted = {k for k in role_keys(rd) if k in caps}
        have = set(RoleCapability.objects.filter(role=role).values_list("capability__key", flat=True))
        RoleCapability.objects.bulk_create(
            [RoleCapability(role=role, capability=caps[k]) for k in wanted - have], ignore_conflicts=True
        )
        if reconcile and have - wanted:
            RoleCapability.objects.filter(role=role, capability__key__in=have - wanted).delete()


def grant_missing_role_capabilities() -> None:
    seed_roles(reconcile=False)
