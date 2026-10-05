"""People API. Sign-in, sessions, password change/reset, login-by-code and MFA are
django-allauth headless at ``/_allauth/browser/v1/`` (same as sis_backend); this module
only adds the profile and the People admin."""
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import ActivityAction, ActivityEvent
from audit.services import record_activity
from oric_backend.errors import DomainAPIError
from rbac.viewsets import RBACViewSetMixin

from .models import User
from .serializers import ProfileSerializer, UserAdminSerializer
from .services.profile import ensure_person_for_user


class ProfileMeView(APIView):
    """GET/PATCH the signed-in user's own profile (Person), incl. photo upload."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        return Response(ProfileSerializer(ensure_person_for_user(request.user), context={"request": request}).data)

    def patch(self, request):
        person = ensure_person_for_user(request.user)
        ser = ProfileSerializer(person, data=request.data, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)


class MeActivityView(APIView):
    """The user's own recent sign-ins and security events (no capability needed: own data)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        events = ActivityEvent.objects.filter(
            actor=request.user,
            action__in=[ActivityAction.LOGIN, ActivityAction.LOGOUT, ActivityAction.LOGIN_FAILED,
                        ActivityAction.PASSWORD_CHANGED, ActivityAction.PASSWORD_RESET],
        )[:15]
        return Response([
            {"id": e.id, "action": e.action, "description": e.description, "ip": e.remote_addr,
             "user_agent": e.user_agent, "timestamp": e.timestamp}
            for e in events
        ])


class SetPasswordSerializer(drf_serializers.Serializer):
    new_password = drf_serializers.CharField(trim_whitespace=False)


class UserViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    """People admin. Department-scoped: a department admin only sees their department's people."""

    queryset = User.objects.select_related("person__department").prefetch_related("role_assignments__role")
    serializer_class = UserAdminSerializer
    capability_resource = "user"
    capability_map = {"set_password": "user.set_password", "deactivate": "user.deactivate",
                      "activate": "user.deactivate", "social_accounts": "user.view",
                      "set_social_account_status": "user.change"}
    scope_department_field = "person__department_id"
    filterset_fields = {"person__department": ["exact"], "is_active": ["exact"]}
    search_fields = ["email", "person__full_name", "person__designation", "person__employee_id"]
    ordering_fields = ["person__full_name", "email", "last_login", "date_joined"]
    ordering = ["person__full_name"]
    http_method_names = ["get", "post", "patch", "delete"]

    def filter_queryset(self, qs):
        # Backwards-compatible ?department= filter used by the SPA.
        dep = self.request.query_params.get("department")
        if dep:
            qs = qs.filter(person__department_id=dep)
        return super().filter_queryset(qs)

    def perform_destroy(self, instance):
        if instance.pk == self.request.user.pk:
            raise DomainAPIError(code="SELF_DELETE", http_status=409, message="You cannot delete your own account.")
        if instance.submissions.exists():
            raise DomainAPIError(code="USER_HAS_SUBMISSIONS", http_status=409,
                                 message="This person has returns on file; deactivate the account instead.")
        instance.delete()

    @action(detail=True, methods=["post"])
    def set_password(self, request, pk=None):
        user = self.get_object()
        ser = SetPasswordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        validate_password(ser.validated_data["new_password"], user)
        user.set_password(ser.validated_data["new_password"])
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password", "updated_at"])
        record_activity(ActivityAction.PASSWORD_RESET, request=request, target=user,
                        description=f"Password set by admin for {user.email}")
        return Response({"detail": "Password set. The user must change it at next sign-in."})

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        if user.pk == request.user.pk:
            raise DomainAPIError(code="SELF_DEACTIVATE", http_status=409, message="You cannot deactivate yourself.")
        user.is_active = False
        user.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(user).data, status=status.HTTP_200_OK)

    # ---- linked sign-in identities (Google), sis_backend admin_social_accounts pattern ----------
    def _social_payload(self, user):
        from allauth.socialaccount.models import SocialAccount

        rows = []
        for acc in SocialAccount.objects.filter(user=user).select_related("status"):
            status = getattr(acc, "status", None)
            extra = acc.extra_data or {}
            rows.append({
                "id": acc.pk, "provider": acc.provider, "email": extra.get("email", ""),
                "name": extra.get("name", ""), "last_login": acc.last_login, "date_joined": acc.date_joined,
                "is_active": status.is_active if status else True,
                "deactivated_at": status.deactivated_at if status else None,
            })
        return rows

    @action(detail=True, methods=["get"])
    def social_accounts(self, request, pk=None):
        return Response(self._social_payload(self.get_object()))

    @action(detail=True, methods=["post"], url_path="social-accounts/status")
    def set_social_account_status(self, request, pk=None):
        from allauth.socialaccount.models import SocialAccount
        from django.utils import timezone

        from .models import SocialAccountStatus

        user = self.get_object()
        acc = SocialAccount.objects.filter(user=user, pk=request.data.get("id")).first()
        if acc is None:
            raise DomainAPIError(code="NOT_FOUND", http_status=404, message="That sign-in identity isn't linked here.")
        active = bool(request.data.get("is_active"))
        SocialAccountStatus.objects.update_or_create(
            social_account=acc,
            defaults={"is_active": active, "deactivated_at": None if active else timezone.now(),
                      "deactivated_by": None if active else request.user},
        )
        record_activity(ActivityAction.OTHER, request=request, target=user,
                        description=f"{acc.provider.title()} sign-in {'enabled' if active else 'disabled'} for {user.email}")
        return Response(self._social_payload(user))
