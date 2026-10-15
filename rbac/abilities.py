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
        global_scope = any(s.is_global for s in scopes)
        any_subject = any(s.any_subject for s in scopes)
        out.append({
            "key": key,
            "department_ids": "all" if global_scope else sorted({s.department_id for s in scopes if s.department_id}),
            "faculty_ids": "all" if global_scope else sorted({s.faculty_id for s in scopes if s.faculty_id}),
            "pillars": "all" if any_subject else sorted({x for s in scopes for x in s.pillars}),
            "categories": "all" if any_subject else sorted({x for s in scopes for x in s.categories}),
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
        if cap["department_ids"] != "all" and cap["department_ids"]:
            conditions["department_id"] = {"$in": cap["department_ids"]}
        if cap["faculty_ids"] != "all" and cap["faculty_ids"]:
            conditions["faculty_id"] = {"$in": cap["faculty_ids"]}
        if cap["pillars"] != "all" and cap["pillars"]:
            conditions["pillar"] = {"$in": cap["pillars"]}
        if cap["categories"] != "all" and cap["categories"]:
            conditions["category"] = {"$in": cap["categories"]}
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
        {"key": k, "department_ids": "all", "faculty_ids": "all", "pillars": "all", "categories": "all"}
        for k in sorted(CAPABILITY_BY_KEY)
    ]
    rules = build_rules(user, caps)
    roles = [
        {"slug": a.role.slug, "name": a.role.name, "department_id": a.department_id,
         "department_name": a.department.name if a.department_id else None,
         "faculty_id": a.faculty_id, "faculty_name": a.faculty.name if a.faculty_id else None,
         "pillars": a.role.pillars, "categories": a.role.categories}
        for a in RoleAssignment.objects.filter(user=user, is_active=True).select_related("role", "department",
                                                                                          "faculty")
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
