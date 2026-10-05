"""Explicit allowlist for the coverage-guard test (rbac/tests/test_coverage_guard.py).

Every /api/v1/ route must either resolve to a capability key or be listed here.
"""

# No authentication at all.
PUBLIC_ROUTE_NAMES = {
    "public-site",
    "contact-create",
    "forms-schema",
}

# Authenticated, self-service: always allowed for a signed-in user; data is the user's own.
AUTHENTICATED_EXEMPT_ROUTE_NAMES = {
    "me-profile",
    "me-activity",
    "me-abilities",
    "me-home",
    "notifications-list",
    "notifications-detail",
    "notifications-mark-read",
    "notifications-mark-all-read",
    "notifications-unread-count",
}
