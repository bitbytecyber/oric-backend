from rest_framework.permissions import IsAuthenticated

from .permissions import HasCapability
from .utils import UNMAPPED, capability_scope_q

DEFAULT_ACTION_MAP = {
    "list": "view",
    "retrieve": "view",
    "create": "add",
    "update": "change",
    "partial_update": "change",
    "destroy": "delete",
}


class RBACViewSetMixin:
    """Declare capabilities on a ViewSet (same contract as sis_backend).

    * ``capability_resource = "department"`` auto-maps list/retrieve → view,
      create → add, update/partial_update → change, destroy → delete.
    * ``capability_map`` overrides per action (including @action names).
    * Unknown actions resolve to ``__unmapped__`` → only superusers pass.
    * ``scope_department_field`` / ``scope_pillar_field``: when set, querysets
      are filtered to rows the user holds the action's key for.
    """

    capability_resource: str | None = None
    capability_map: dict[str, str] | None = None
    scope_department_field: str | None = None
    scope_pillar_field: str | None = None
    scope_queryset_by_capability = True
    department_param: str | None = None

    def get_required_capability(self, request):
        action = getattr(self, "action", None)
        if self.capability_map and action in self.capability_map:
            return self.capability_map[action]
        if self.capability_resource and action in DEFAULT_ACTION_MAP:
            return f"{self.capability_resource}.{DEFAULT_ACTION_MAP[action]}"
        if action is None and request.method == "OPTIONS":
            return None
        return UNMAPPED

    def get_permissions(self):
        return [IsAuthenticated(), HasCapability()]

    def get_queryset(self):
        return self.filter_queryset_by_capability(super().get_queryset())

    def filter_queryset_by_capability(self, qs):
        if not self.scope_queryset_by_capability:
            return qs
        if not (self.scope_department_field or self.scope_pillar_field):
            return qs
        key = self.get_required_capability(self.request)
        if not key or key == UNMAPPED:
            return qs
        q = capability_scope_q(self.request.user, key, department_field=self.scope_department_field,
                               pillar_field=self.scope_pillar_field)
        return qs if q is None else qs.filter(q)


class CapabilityAPIViewMixin:
    """For APIViews: set ``required_capability = "report.view"``."""

    required_capability: str | None = None
    department_param: str | None = None

    def get_permissions(self):
        return [IsAuthenticated(), HasCapability()]
