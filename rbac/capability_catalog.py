"""
Code-first capability catalog — the single source of truth for "who may do what".

Same design as sis_backend/rbac/capability_catalog.py:
  * key format ``"{resource}.{action}"`` (snake_case), module is metadata only;
  * ``_cap`` / ``_crud`` builders; CASL subject/action maps for the frontend;
  * ``ROLE_DEFS`` built-in roles with wildcard patterns.

Scoping dimension differs: sis_backend scopes assignments by *campus*; ORIC
scopes them by *department* (RoleAssignment.department, NULL = all departments)
and roles may additionally be limited to *pillars* (AccessRole.pillars, empty =
all) so e.g. the IP manager only reviews Innovation & Commercialization returns.

Adding a capability: add it here, then ship a data migration that calls
``sync_capabilities()`` and ``grant_missing_role_capabilities`` (see
rbac/migrations/0002_seed_catalog.py). A key with no DB row is never granted.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityDef:
    key: str
    module: str
    resource: str
    action: str
    name: str
    description: str = ""
    subject: str = ""
    is_dangerous: bool = False


CRUD_ACTIONS = ("view", "add", "change", "delete")
ACTION_LABELS = {
    "view": "View",
    "add": "Create",
    "change": "Edit",
    "delete": "Delete",
    "review": "Review",
    "approve": "Approve / reject",
    "export": "Export",
    "set_password": "Set password",
    "deactivate": "Deactivate",
    "activate": "Activate",
    "manage": "Manage",
    "view_admin": "View admin dashboard",
}


def _pascal(resource: str) -> str:
    return "".join(part.capitalize() for part in resource.split("_"))


def _cap(module, resource, action, *, description="", subject="", is_dangerous=False, name="") -> CapabilityDef:
    label = name or f"{ACTION_LABELS.get(action, action.replace('_', ' ').title())} {resource.replace('_', ' ')}"
    return CapabilityDef(
        key=f"{resource}.{action}",
        module=module,
        resource=resource,
        action=action,
        name=label,
        description=description,
        subject=subject or _pascal(resource),
        is_dangerous=is_dangerous,
    )


def _crud(module, resource, *, extra=(), skip=(), dangerous=("delete",), descriptions=None) -> list[CapabilityDef]:
    descriptions = descriptions or {}
    out = []
    for action in (*CRUD_ACTIONS, *extra):
        if action in skip:
            continue
        out.append(_cap(module, resource, action, is_dangerous=action in dangerous,
                        description=descriptions.get(action, "")))
    return out


def build_capability_catalog() -> list[CapabilityDef]:
    caps: list[CapabilityDef] = []

    # --- Submissions (pillar returns) -------------------------------------------
    caps += _crud(
        "submissions", "submission", extra=("review", "approve", "export"),
        descriptions={
            "view": "See other people's returns (within the assignment's department / the role's pillars). "
                    "Everyone can always see their own.",
            "add": "File your own annual return (faculty).",
            "change": "Edit someone else's return, e.g. ORIC staff correcting data.",
            "delete": "Delete a return and all its entries and evidence.",
            "review": "Start review and return a submission to its owner for revision.",
            "approve": "Approve or reject a submission, or reopen a decided one.",
            "export": "Download returns as CSV / Excel.",
        },
    )

    # --- Reports -------------------------------------------------------------------
    caps += [
        _cap("reports", "report", "view", description="Year-wise scorecard dashboards across departments."),
        _cap("reports", "report", "export", description="Export scorecard tables."),
        _cap("reports", "dashboard", "view_admin", description="Institution-wide KPIs on the home dashboard."),
    ]

    # --- Organisation -----------------------------------------------------------------
    caps += _crud("org", "department")
    caps += _crud("org", "reporting_cycle", descriptions={
        "change": "Open / close a reporting year and move its deadline.",
    })
    caps += _crud("org", "team_member")
    caps += [
        _cap("org", "contact_message", "view", description="Read messages sent through the contact form."),
        _cap("org", "contact_message", "change", description="Mark contact messages as handled."),
    ]

    # --- People -------------------------------------------------------------------------
    caps += _crud("people", "user", extra=("set_password", "deactivate"),
                  dangerous=("delete", "set_password", "deactivate"))

    # --- RBAC ---------------------------------------------------------------------------
    caps += _crud("rbac", "role")
    caps.append(_cap("rbac", "capability", "view"))
    caps += _crud("rbac", "role_assignment", extra=("activate", "deactivate"))
    caps.append(_cap("rbac", "rbac", "manage", is_dangerous=True,
                     description="Manage roles and assignments across every department (super-admin)."))

    # --- Audit ----------------------------------------------------------------------------
    caps.append(_cap("audit", "audit", "view", description="Read the audit trail (row changes, sign-ins, exports)."))
    return caps


CAPABILITY_CATALOG: list[CapabilityDef] = build_capability_catalog()
CAPABILITY_KEYS: frozenset[str] = frozenset(c.key for c in CAPABILITY_CATALOG)
CAPABILITY_BY_KEY: dict[str, CapabilityDef] = {c.key: c for c in CAPABILITY_CATALOG}

CAPABILITY_ACTION_TO_CASL = {"view": "read", "add": "create", "change": "update", "delete": "delete", "manage": "manage"}
RESOURCE_TO_SUBJECT = {c.resource: c.subject for c in CAPABILITY_CATALOG}

# Never handed out through wildcard patterns; must be granted explicitly.
NEVER_AUTO_GRANTED_CAPABILITIES = frozenset({"rbac.manage"})


def expand_patterns(patterns: list[str], *, allow_never: bool = False) -> set[str]:
    keys = set()
    for pattern in patterns:
        keys |= {k for k in CAPABILITY_KEYS if fnmatch.fnmatchcase(k, pattern)}
    if not allow_never:
        keys -= {k for k in NEVER_AUTO_GRANTED_CAPABILITIES if k not in patterns}
    return keys


# Self-service basics every staff/faculty role gets.
FOUNDATION = ["department.view", "reporting_cycle.view", "team_member.view"]

ORIC_STAFF = [
    *FOUNDATION,
    "submission.view", "submission.change", "submission.review", "submission.approve", "submission.export",
    "report.*", "dashboard.view_admin", "user.view",
]

ROLE_DEFS: list[dict] = [
    {
        "slug": "admin",
        "name": "System administrator",
        "description": "Full access including role management.",
        "is_system": True,
        "patterns": ["*", "rbac.manage"],
    },
    {
        "slug": "oric_director",
        "name": "Director ORIC",
        "description": "Everything except super-admin role management.",
        "is_system": True,
        "patterns": ["*"],
    },
    {
        "slug": "oric_manager",
        "name": "ORIC manager",
        "description": "Reviews and approves returns for all pillars, runs reports, maintains team & cycles.",
        "is_system": True,
        "patterns": [*ORIC_STAFF, "reporting_cycle.change", "team_member.*", "contact_message.*", "audit.view"],
    },
    {
        "slug": "research_ops_manager",
        "name": "Manager — Research Operations & Development",
        "description": "Reviews Research Excellence returns.",
        "is_system": True,
        "pillars": ["RE"],
        "patterns": ORIC_STAFF,
    },
    {
        "slug": "ip_manager",
        "name": "Manager — Intellectual Property",
        "description": "Reviews Innovation & Commercialization returns.",
        "is_system": True,
        "pillars": ["IC"],
        "patterns": ORIC_STAFF,
    },
    {
        "slug": "tech_transfer_manager",
        "name": "Manager — Tech Transfer & University-Industry Linkage",
        "description": "Reviews Innovation & Commercialization and Research Excellence returns.",
        "is_system": True,
        "pillars": ["IC", "RE"],
        "patterns": ORIC_STAFF,
    },
    {
        "slug": "incubation_manager",
        "name": "Manager — Business Incubation",
        "description": "Reviews Sustainability & Capacity Building (startups) returns.",
        "is_system": True,
        "pillars": ["SCB"],
        "patterns": ORIC_STAFF,
    },
    {
        "slug": "department_focal",
        "name": "Department focal person",
        "description": "Assign per department: checks that department's returns before ORIC review.",
        "is_system": True,
        "patterns": [*FOUNDATION, "submission.view", "submission.review", "submission.export", "report.view",
                     "dashboard.view_admin", "user.view"],
    },
    {
        "slug": "faculty",
        "name": "Faculty member",
        "description": "Files their own annual returns.",
        "is_system": True,
        "patterns": [*FOUNDATION, "submission.add"],
    },
    {
        "slug": "auditor",
        "name": "Auditor / viewer",
        "description": "Read-only access to returns, reports and the audit trail.",
        "is_system": True,
        "patterns": [*FOUNDATION, "submission.view", "submission.export", "report.*", "dashboard.view_admin",
                     "user.view", "audit.view"],
    },
]
