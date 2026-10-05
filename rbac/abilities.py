"""`GET /api/v1/me/abilities/` payload — CASL rules for the frontend (sis_backend shape,
with ``department_ids`` + ``pillars`` in place of ``campus_ids``)."""
from __future__ import annotations

import hashlib
import json

from django.core.cache import cache

from .cache import ABILITIES_TTL, abilities_cache_key, rbac_version
from .capability_catalog import CAPABILITY_ACTION_TO_CASL, CAPABILITY_BY_KEY
from .models import RoleAssignment
from .utils import capability_scopes, user_capability_keys


def build_capabilities_flat(user) -> list[dict]:
    out = []
    for key in sorted(user_capability_keys(user)):
        scopes = capability_scopes(user, key)
        global_scope = any(d is None for d, _ in scopes)
        unrestricted_pillars = any(not p for _, p in scopes)
        out.append({
            "key": key,
            "department_ids": "all" if global_scope else sorted({d for d, _ in scopes}),
            "pillars": "all" if unrestricted_pillars else sorted({x for _, p in scopes for x in p}),
        })
    return out


def build_rules(user, caps: list[dict]) -> list[dict]:
    if user.is_superuser:
        return [{"action": "manage", "subject": "all"}]
    rules = []
    for cap in caps:
        meta = CAPABILITY_BY_KEY.get(cap["key"])
        if not meta:
            continue
        action = CAPABILITY_ACTION_TO_CASL.get(meta.action, meta.action)
        conditions = {}
        if cap["department_ids"] != "all":
            conditions["department_id"] = {"$in": cap["department_ids"]}
        if cap["pillars"] != "all":
            conditions["pillar"] = {"$in": cap["pillars"]}
        rule = {"action": action, "subject": meta.subject}
        if conditions:
            rule["conditions"] = conditions
        rules.append(rule)
    return rules


def build_abilities_payload(user) -> dict:
    key = abilities_cache_key(user.pk)
    cached = cache.get(key)
    if cached:
        return cached
    caps = build_capabilities_flat(user) if not user.is_superuser else [
        {"key": k, "department_ids": "all", "pillars": "all"} for k in sorted(CAPABILITY_BY_KEY)
    ]
    rules = build_rules(user, caps)
    roles = [
        {"slug": a.role.slug, "name": a.role.name, "department_id": a.department_id,
         "department_name": a.department.name if a.department_id else None, "pillars": a.role.pillars}
        for a in RoleAssignment.objects.filter(user=user, is_active=True).select_related("role", "department")
    ]
    digest = hashlib.sha1(json.dumps(rules, sort_keys=True).encode()).hexdigest()[:12]
    payload = {
        "version": f"{rbac_version()}:{digest}",
        "is_superuser": user.is_superuser,
        "roles": roles,
        "capabilities": caps,
        "rules": rules,
    }
    cache.set(key, payload, ABILITIES_TTL)
    return payload
