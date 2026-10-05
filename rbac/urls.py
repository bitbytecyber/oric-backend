from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import AccessRoleViewSet, CapabilityCatalogView, MeAbilitiesView, RoleAssignmentViewSet

router = SimpleRouter()
router.register("rbac/roles", AccessRoleViewSet, basename="rbac-roles")
router.register("rbac/assignments", RoleAssignmentViewSet, basename="rbac-assignments")

urlpatterns = [
    path("me/abilities/", MeAbilitiesView.as_view(), name="me-abilities"),
    path("rbac/capabilities/", CapabilityCatalogView.as_view(), name="rbac-capabilities"),
    *router.urls,
]
