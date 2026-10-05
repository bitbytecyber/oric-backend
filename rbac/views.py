from django.db import transaction
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from oric_backend.errors import DomainAPIError

from .abilities import build_abilities_payload
from .capability_catalog import CAPABILITY_CATALOG, ROLE_DEFS
from .models import AccessRole, Capability, RoleAssignment, RoleCapability
from .serializers import (
    AccessRoleSerializer,
    CapabilitySerializer,
    RoleAssignmentSerializer,
    RoleCapabilitiesSerializer,
)
from .services import rbac_admin
from .utils import ALL, capability_department_ids, user_has_capability
from .viewsets import CapabilityAPIViewMixin, RBACViewSetMixin


class MeAbilitiesView(APIView):
    """Effective capabilities + CASL rules for the signed-in user (self-service, no capability)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(build_abilities_payload(request.user))


class CapabilityCatalogView(CapabilityAPIViewMixin, APIView):
    """Catalog grouped by module, plus built-in role templates for the role editor."""

    required_capability = "capability.view"

    def get(self, request):
        caps = CapabilitySerializer(Capability.objects.all(), many=True).data
        modules: dict[str, list] = {}
        for c in caps:
            modules.setdefault(c["module"], []).append(c)
        order = list(dict.fromkeys(c.module for c in CAPABILITY_CATALOG))
        return Response({
            "modules": [{"module": m, "capabilities": modules.get(m, [])} for m in order],
            "templates": [{"slug": r["slug"], "name": r["name"], "pillars": r.get("pillars", [])} for r in ROLE_DEFS],
        })


class AccessRoleViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    serializer_class = AccessRoleSerializer
    capability_resource = "role"
    capability_map = {"capabilities": "role.view"}
    search_fields = ["name", "slug", "description"]
    ordering_fields = ["name", "slug"]
    http_method_names = ["get", "post", "patch", "put", "delete"]

    def get_queryset(self):
        return super().get_queryset().annotate(
            capability_count=Count("role_capabilities", distinct=True),
            assignment_count=Count("assignments", filter=Q(assignments__is_active=True), distinct=True),
        )

    queryset = AccessRole.objects.all()

    def get_required_capability(self, request):
        if self.action == "capabilities" and request.method == "PUT":
            return "role.change"
        return super().get_required_capability(request)

    def perform_create(self, serializer):
        serializer.save(is_system=False)

    def perform_update(self, serializer):
        rbac_admin.validate_role_update(self.request.user, serializer.instance, serializer.validated_data)
        serializer.save()

    def perform_destroy(self, instance):
        rbac_admin.validate_role_delete(self.request.user, instance)
        if instance.assignments.filter(is_active=True).exists():
            raise DomainAPIError(code="ROLE_IN_USE", http_status=409,
                                 message="Remove this role's active assignments before deleting it.")
        instance.delete()

    @action(detail=True, methods=["get", "put"])
    def capabilities(self, request, pk=None):
        role = self.get_object()
        if request.method == "GET":
            return Response({"capability_keys": sorted(role.capabilities.values_list("key", flat=True))})
        ser = RoleCapabilitiesSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        keys = set(ser.validated_data["capability_keys"])
        known = dict(Capability.objects.filter(key__in=keys).values_list("key", "id"))
        unknown = keys - set(known)
        if unknown:
            raise DomainAPIError(code="UNKNOWN_CAPABILITY", message="Unknown capability keys.",
                                 details={"unknown": sorted(unknown)})
        rbac_admin.validate_role_capabilities_update(request.user, role, keys)
        with transaction.atomic():
            RoleCapability.objects.filter(role=role).exclude(capability_id__in=known.values()).delete()
            have = set(RoleCapability.objects.filter(role=role).values_list("capability_id", flat=True))
            RoleCapability.objects.bulk_create(
                [RoleCapability(role=role, capability_id=cid) for cid in set(known.values()) - have]
            )
        return Response({"capability_keys": sorted(keys)})


class RoleAssignmentViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    serializer_class = RoleAssignmentSerializer
    capability_resource = "role_assignment"
    capability_map = {"activate": "role_assignment.activate", "deactivate": "role_assignment.deactivate"}
    filterset_fields = ["user", "role", "department", "is_active"]
    search_fields = ["user__email", "user__full_name", "role__name"]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        qs = RoleAssignment.objects.select_related("user", "role", "department", "granted_by")
        user = self.request.user
        if user.is_superuser or user_has_capability(user, "rbac.manage"):
            return qs
        scope = capability_department_ids(user, "role_assignment.view")
        if scope == ALL:
            return qs
        # Department-scoped admins see assignments in their departments (not global ones).
        return qs.filter(department_id__in=scope)

    def perform_create(self, serializer):
        d = serializer.validated_data
        rbac_admin.validate_assignment_create(
            self.request.user, role=d["role"], department_id=d["department"].pk if d.get("department") else None
        )
        serializer.save(granted_by=self.request.user)

    def perform_update(self, serializer):
        d = serializer.validated_data
        rbac_admin.validate_assignment_change(
            self.request.user, serializer.instance,
            new_role=d.get("role"),
            new_department_id=(d["department"].pk if d.get("department") else None) if "department" in d else ...,
            is_active=d.get("is_active"),
        )
        serializer.save()

    def perform_destroy(self, instance):
        rbac_admin.validate_assignment_delete(self.request.user, instance)
        instance.delete()

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        a = self.get_object()
        rbac_admin.validate_assignment_change(request.user, a, is_active=True)
        a.is_active = True
        a.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(a).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        a = self.get_object()
        rbac_admin.validate_assignment_change(request.user, a, is_active=False)
        a.is_active = False
        a.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(a).data, status=status.HTTP_200_OK)
