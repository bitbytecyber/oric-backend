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

    # --- Submissions (one activity record each) ----------------------------------------
    caps += _crud(
        "submissions", "submission", extra=("verify", "export", "add_on_behalf", "add_oric"),
        dangerous=("delete",),
        descriptions={
            "view": "See other people's submissions (within the assignment's faculty / department and the role's "
                    "pillars / categories). Everyone always sees their own and those they contributed to.",
            "add": "Record your own activities (faculty).",
            "add_on_behalf": "Record an activity for someone else in your scope (Chairman, Dean, ORIC).",
            "add_oric": "Record institution-level ORIC data (policies, IRB, revenue, grant opportunities ...).",
            "change": "Edit someone else's submission, e.g. ORIC staff correcting data.",
            "delete": "Delete a submission and its evidence.",
            "verify": "Verify, return or reject submissions (ORIC).",
            "export": "Download submissions as CSV / Excel / HEC workbook.",
        },
    )

    # --- Reports / scorecard ----------------------------------------------------------------
    caps += [
        _cap("reports", "report", "view", description="Dashboards and drill-down analytics."),
        _cap("reports", "report", "export", description="Export report tables."),
        _cap("reports", "dashboard", "view_admin", description="Scope KPIs on the home dashboard."),
        _cap("scorecard", "scorecard", "view", description="HEC ORIC scorecard (computed live)."),
        _cap("scorecard", "scorecard", "override", description="Override reported numbers / scores on the scorecard."),
        _cap("scorecard", "institution_profile", "view", description="Index-A institution profile."),
        _cap("scorecard", "institution_profile", "change", description="Edit the Index-A institution profile."),
    ]

    # --- Import ---------------------------------------------------------------------------------
    caps += [
        _cap("imports", "import", "view", description="See import batches and the unmatched queue."),
        _cap("imports", "import", "run", is_dangerous=True,
             description="Upload directory CSVs, HEC workbooks and form responses; resolve unmatched rows."),
    ]

    # --- Organisation -----------------------------------------------------------------
    caps += _crud("org", "faculty")
    caps += _crud("org", "department")
    caps += _crud("org", "organization")
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
FOUNDATION = ["faculty.view", "department.view", "reporting_cycle.view", "team_member.view", "organization.view"]

ORIC_STAFF = [
    *FOUNDATION,
    "submission.view", "submission.change", "submission.verify", "submission.export", "submission.add_on_behalf",
    "submission.add_oric", "report.*", "dashboard.view_admin", "scorecard.view", "institution_profile.view",
    "user.view", "organization.*", "import.view",
]
LEADERSHIP = [
    *FOUNDATION,
    "submission.view", "submission.export", "submission.add_on_behalf", "report.*", "dashboard.view_admin",
    "scorecard.view",
]

IP_CATEGORIES = ["ip_disclosure", "patent", "licensing_negotiation", "license_signed", "licensing_revenue", "policy",
                 "prototype", "creative_product"]
TECH_TRANSFER_CATEGORIES = ["contract_research", "consultancy_opportunity", "consultancy_contract", "research_link",
                            "collaboration_agreement", "industry_visit", "policy_advocacy", "civic_engagement",
                            "award", "licensing_negotiation", "license_signed", "exhibition"]
RESEARCH_OPS_CATEGORIES = ["grant_opportunity", "grant_hec_submitted", "grant_hec_approved", "grant_hec_completed",
                           "grant_nonhec_submitted", "grant_nonhec_approved", "grant_nonhec_completed",
                           "joint_submitted", "joint_approved", "joint_completed", "irb_review", "asrb_liaison",
                           "publication", "research_revenue", "training_oric", "training_external",
                           "training_oric_staff", "strategic_plan"]

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
        "description": "Sees and manages everything except super-admin role management.",
        "is_system": True,
        "patterns": ["*"],
    },
    {
        "slug": "oric_manager",
        "name": "ORIC manager (all categories)",
        "description": "Verifies every category, runs reports & imports, maintains directory, team & fiscal years.",
        "is_system": True,
        "patterns": [*ORIC_STAFF, "import.run", "scorecard.override", "institution_profile.change",
                     "reporting_cycle.change", "team_member.*", "contact_message.*", "audit.view",
                     "faculty.*", "department.*", "user.add", "user.change"],
    },
    {
        "slug": "research_ops_manager",
        "name": "Manager — Research Operations & Development",
        "description": "Verifies research grants, IRB, publications, trainings and research revenue.",
        "is_system": True,
        "categories": RESEARCH_OPS_CATEGORIES,
        "patterns": ORIC_STAFF,
    },
    {
        "slug": "ip_manager",
        "name": "Manager — Intellectual Property",
        "description": "Verifies IP disclosures, patents, licensing, prototypes and policies.",
        "is_system": True,
        "categories": IP_CATEGORIES,
        "patterns": ORIC_STAFF,
    },
    {
        "slug": "tech_transfer_manager",
        "name": "Manager — Tech Transfer & University-Industry Linkage",
        "description": "Verifies contract research, consultancy, linkages, agreements, visits and awards.",
        "is_system": True,
        "categories": TECH_TRANSFER_CATEGORIES,
        "patterns": ORIC_STAFF,
    },
    {
        "slug": "incubation_manager",
        "name": "Manager — Business Incubation",
        "description": "Verifies BIC data: startups, spin-offs, startup funding and entrepreneurship events.",
        "is_system": True,
        "pillars": ["BIC"],
        "patterns": ORIC_STAFF,
    },
    {
        "slug": "dean",
        "name": "Dean",
        "description": "Assign per faculty: sees, exports and submits on behalf of everyone in the faculty.",
        "is_system": True,
        "patterns": LEADERSHIP,
    },
    {
        "slug": "chairman",
        "name": "Chairman / Co-Chair",
        "description": "Assign per department: sees, exports and submits on behalf of department members.",
        "is_system": True,
        "patterns": LEADERSHIP,
    },
    {
        "slug": "faculty",
        "name": "Faculty member",
        "description": "Records their own activities.",
        "is_system": True,
        "patterns": [*FOUNDATION, "submission.add"],
    },
    {
        "slug": "auditor",
        "name": "Auditor / viewer",
        "description": "Read-only access to submissions, reports, scorecard and the audit trail.",
        "is_system": True,
        "patterns": [*FOUNDATION, "submission.view", "submission.export", "report.*", "dashboard.view_admin",
                     "scorecard.view", "institution_profile.view", "user.view", "audit.view", "import.view"],
    },
]
