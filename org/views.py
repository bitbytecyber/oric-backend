from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Count
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from oric_backend.errors import DomainAPIError
from rbac.viewsets import RBACViewSetMixin

from .models import ContactMessage, Department, ReportingCycle, TeamMember
from .serializers import (
    ContactCreateSerializer,
    ContactMessageSerializer,
    DepartmentSerializer,
    ReportingCycleSerializer,
    TeamMemberSerializer,
)

# Legacy home/about pages carried these; kept as data so ORIC can edit them later.
SCORECARD_HIGHLIGHTS = [
    {"rank": "1st", "label": "Human Resources & Operations"},
    {"rank": "1st", "label": "Research Excellence", "note": "Highest among all universities"},
    {"rank": "1st", "label": "Sustainability & Capacity Building"},
    {"rank": "5th", "label": "Innovation & Commercialization"},
    {"rank": "Top 3", "label": "Overall ORIC Scorecard"},
]
VISION = (
    "ORIC aims to foster innovation, promote research and development, and contribute to creating a vibrant, "
    "entrepreneurial ecosystem within the community. Our vision is to create a culture of innovation and "
    "entrepreneurship by connecting industry with academia and driving positive social impact."
)


class PublicSiteView(APIView):
    """Login screen / about page content: team, scorecard highlights, current cycle. No auth."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        cycle = ReportingCycle.current()
        return Response({
            "team": TeamMemberSerializer(TeamMember.objects.filter(is_active=True), many=True,
                                         context={"request": request}).data,
            "scorecard": SCORECARD_HIGHLIGHTS,
            "vision": VISION,
            "current_cycle": ReportingCycleSerializer(cycle).data if cycle else None,
            "contact": {"address": "ORIC, NED University of Engineering & Technology, University Road, Karachi",
                        "email": settings.ORIC_INBOX_EMAIL},
        })


class DepartmentViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    serializer_class = DepartmentSerializer
    capability_resource = "department"
    search_fields = ["name", "code", "faculty"]
    filterset_fields = ["is_active"]
    http_method_names = ["get", "post", "patch", "delete"]
    pagination_class = None

    def get_queryset(self):
        # explicit order: Meta.ordering is ignored on GROUP BY (annotated) queries
        return Department.objects.annotate(member_count=Count("members")).order_by("name")

    def perform_destroy(self, instance):
        if instance.submissions.exists() or instance.members.exists():
            raise DomainAPIError(code="DEPARTMENT_IN_USE", http_status=409,
                                 message="This department has people or returns; deactivate it instead.")
        instance.delete()


class ReportingCycleViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    queryset = ReportingCycle.objects.all()
    serializer_class = ReportingCycleSerializer
    capability_resource = "reporting_cycle"
    http_method_names = ["get", "post", "patch", "delete"]
    pagination_class = None

    def perform_destroy(self, instance):
        if instance.submissions.exists():
            raise DomainAPIError(code="CYCLE_IN_USE", http_status=409,
                                 message="Returns were filed in this cycle; archive it instead.")
        instance.delete()


class TeamMemberViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    queryset = TeamMember.objects.all()
    serializer_class = TeamMemberSerializer
    capability_resource = "team_member"
    http_method_names = ["get", "post", "patch", "delete"]
    pagination_class = None


class ContactCreateView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "contact"

    def post(self, request):
        ser = ContactCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        msg = ser.save()
        send_mail(
            f"[ORIC portal] {msg.subject or 'New message'} — {msg.name}",
            f"From: {msg.name} <{msg.email}>\n\n{msg.message}",
            settings.DEFAULT_FROM_EMAIL,
            [settings.ORIC_INBOX_EMAIL],
            fail_silently=True,
        )
        return Response({"detail": "Thanks — ORIC will get back to you."}, status=201)


class ContactMessageViewSet(RBACViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = ContactMessage.objects.all()
    serializer_class = ContactMessageSerializer
    capability_resource = "contact_message"
    capability_map = {"mark_handled": "contact_message.change"}
    filterset_fields = ["handled"]
    search_fields = ["name", "email", "subject", "message"]

    @action(detail=True, methods=["post"])
    def mark_handled(self, request, pk=None):
        msg = self.get_object()
        msg.handled = bool(request.data.get("handled", True))
        msg.handled_by = request.user if msg.handled else None
        msg.save(update_fields=["handled", "handled_by"])
        return Response(self.get_serializer(msg).data)
