from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from oric_backend.errors import DomainAPIError
from rbac.viewsets import RBACViewSetMixin

from .models import ContactMessage, Department, Faculty, Organization, ReportingCycle, TeamMember
from .serializers import (
    ContactCreateSerializer,
    ContactMessageSerializer,
    DepartmentSerializer,
    FacultySerializer,
    OrganizationSerializer,
    ReportingCycleSerializer,
    TeamMemberSerializer,
)
from .services.directory import sync_leadership_roles

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
        last = None
        prev = ReportingCycle.objects.exclude(status=ReportingCycle.Status.OPEN).filter(
            submissions__isnull=False).distinct().order_by("-year").first()
        if prev:
            from scorecard.engine import compute

            sc = compute(prev)
            last = {"label": prev.label, "total": sc["total"], "category": sc["category"]["category"],
                    "sections": [{"key": x["key"], "title": x["title"], "score": x["score"], "max": x["max"]}
                                 for x in sc["sections"]]}
        return Response({
            "last_scorecard": last,
            "team": TeamMemberSerializer(TeamMember.objects.filter(is_active=True), many=True,
                                         context={"request": request}).data,
            "scorecard": SCORECARD_HIGHLIGHTS,
            "vision": VISION,
            "current_cycle": ReportingCycleSerializer(cycle).data if cycle else None,
            "contact": {"address": "ORIC, NED University of Engineering & Technology, University Road, Karachi",
                        "email": settings.ORIC_INBOX_EMAIL},
        })


class FacultyViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    serializer_class = FacultySerializer
    capability_resource = "faculty"
    search_fields = ["name", "code"]
    http_method_names = ["get", "post", "patch", "delete"]
    pagination_class = None

    def get_queryset(self):
        return Faculty.objects.select_related("dean__user").annotate(
            department_count=Count("departments", distinct=True),
            member_count=Count("departments__members", filter=Q(departments__members__is_faculty=True),
                               distinct=True),
        ).order_by("order", "name")

    def perform_create(self, serializer):
        serializer.save()
        sync_leadership_roles()

    def perform_update(self, serializer):
        serializer.save()
        sync_leadership_roles()

    def perform_destroy(self, instance):
        if instance.departments.exists():
            raise DomainAPIError(code="FACULTY_IN_USE", http_status=409,
                                 message="This faculty still has departments; move them first.")
        instance.delete()


class DepartmentViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    serializer_class = DepartmentSerializer
    capability_resource = "department"
    search_fields = ["name", "code", "faculty__name"]
    filterset_fields = ["is_active", "faculty"]
    http_method_names = ["get", "post", "patch", "delete"]
    pagination_class = None

    def get_queryset(self):
        # explicit order: Meta.ordering is ignored on GROUP BY (annotated) queries
        return (Department.objects.select_related("faculty", "chair__user").prefetch_related("co_chairs__user")
                .annotate(member_count=Count("members", filter=Q(members__is_faculty=True))).order_by("name"))

    def perform_create(self, serializer):
        serializer.save()
        sync_leadership_roles()

    def perform_update(self, serializer):
        serializer.save()
        sync_leadership_roles()

    def perform_destroy(self, instance):
        if instance.submissions.exists() or instance.members.exists():
            raise DomainAPIError(code="DEPARTMENT_IN_USE", http_status=409,
                                 message="This department has people or returns; deactivate it instead.")
        instance.delete()


class OrganizationViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    """External bodies (funders, companies, partners): autocomplete + merge."""

    serializer_class = OrganizationSerializer
    capability_resource = "organization"
    capability_map = {"merge": "organization.change"}
    search_fields = ["name"]
    filterset_fields = ["kind"]
    ordering_fields = ["name", "submission_count"]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        return Organization.objects.annotate(submission_count=Count("submissions")).order_by("name")

    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        """Merge this organization into ``into`` (aliases kept, submissions re-pointed)."""
        src = self.get_object()
        dst = Organization.objects.get(pk=request.data.get("into"))
        if src.pk == dst.pk:
            raise DomainAPIError(code="SAME_ORG", http_status=400, message="Pick a different organization.")
        dst.aliases = sorted({*dst.aliases, *src.aliases, src.name} - {dst.name})
        dst.save(update_fields=["aliases"])
        src.submissions.update(organization=dst)
        src.delete()
        return Response(OrganizationSerializer(dst).data)


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
