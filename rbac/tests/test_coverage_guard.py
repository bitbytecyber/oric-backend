"""Every /api/v1/ route must resolve to a capability, be self-scoped, or be allowlisted.

Port of sis_backend/rbac/tests/test_coverage_guard.py: a new endpoint that
forgets to declare its capability fails CI instead of silently being open.
"""
from django.test import SimpleTestCase
from django.urls import URLPattern, URLResolver, get_resolver

from rbac.public_routes import AUTHENTICATED_EXEMPT_ROUTE_NAMES, PUBLIC_ROUTE_NAMES
from rbac.utils import UNMAPPED

SELF_SCOPED_APIVIEWS = {"evidence-download"}  # object-level check inside the view


class _Req:
    method = "GET"
    query_params = {}
    data = {}
    user = None


def _walk(patterns, prefix=""):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern), p


class CoverageGuardTest(SimpleTestCase):
    def test_every_api_route_is_mapped(self):
        problems = []
        for route, pattern in _walk(get_resolver().url_patterns):
            if not route.startswith("api/v1/"):
                continue
            name = pattern.name or ""
            if name in PUBLIC_ROUTE_NAMES or name in AUTHENTICATED_EXEMPT_ROUTE_NAMES or name in SELF_SCOPED_APIVIEWS:
                continue
            cb = pattern.callback
            view_cls = getattr(cb, "cls", None)
            actions = getattr(cb, "actions", None)
            if view_cls is None:
                problems.append(f"{route} ({name}): not a DRF view")
                continue
            if actions:  # ViewSet route
                allowed = set(getattr(view_cls, "http_method_names", []))
                for action in {a for m, a in actions.items() if m in allowed}:
                    view = view_cls()
                    view.action = action
                    view.request = _Req()
                    if action in getattr(view_cls, "self_scoped_actions", set()):
                        continue
                    if not hasattr(view, "get_required_capability"):
                        problems.append(f"{route} [{action}] ({name}): no RBAC mixin")
                        continue
                    key = view.get_required_capability(_Req())
                    if not key or key == UNMAPPED:
                        problems.append(f"{route} [{action}] ({name}): unmapped")
            else:
                key = getattr(view_cls, "required_capability", None)
                if not key:
                    problems.append(f"{route} ({name}): APIView without required_capability")
        self.assertEqual(problems, [], "Unmapped API routes:\n" + "\n".join(problems))
