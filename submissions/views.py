import json
import mimetypes

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import ActivityAction
from audit.services import record_activity
from oric_backend.errors import (
    CycleClosedError,
    DomainAPIError,
    InsufficientPermissionError,
    SubmissionLockedError,
)
from org.models import Department, ReportingCycle
from rbac.viewsets import RBACViewSetMixin

from . import services
from .access import can_delete, can_edit, can_view, visible_submissions
from .models import EvidenceFile, SectionEntry, Submission
from .registry import SECTION_PILLAR, public_schema
from .serializers import (
    SectionEntrySerializer,
    SubmissionCreateSerializer,
    SubmissionDetailSerializer,
    SubmissionListSerializer,
    SubmissionUpdateSerializer,
    TransitionSerializer,
)
from .validation import file_fields, validate_counts, validate_entry_data, validate_upload


class FormSchemaView(APIView):
    """Every pillar, count and sub-form definition (drives the SPA's dynamic forms)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(public_schema())


class SubmissionViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    """Annual pillar returns.

    Scoping is own-data + capability scope (submissions/access.py), so list /
    retrieve / update / destroy / transition need no blanket capability; their
    object-level rules run in the handlers. ``self_scoped_actions`` documents
    that for the RBAC coverage guard.
    """

    capability_map = {
        "list": None,
        "retrieve": None,
        "create": "submission.add",
        "partial_update": None,
        "destroy": None,
        "transition": None,
    }
    self_scoped_actions = {"list", "retrieve", "partial_update", "destroy", "transition"}
    scope_queryset_by_capability = False
    filterset_fields = {"pillar": ["exact"], "status": ["exact", "in"], "cycle": ["exact"],
                        "cycle__year": ["exact"], "department": ["exact"], "owner": ["exact"]}
    search_fields = ["faculty_name", "faculty_email", "designation", "department__name"]
    ordering_fields = ["updated_at", "submitted_at", "faculty_name", "status", "created_at"]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        qs = Submission.objects.select_related("cycle", "department", "owner", "reviewed_by").annotate(
            entry_count=Count("entries")
        )
        if self.request.query_params.get("mine") in ("1", "true"):
            return qs.filter(owner=self.request.user)
        return visible_submissions(self.request.user, qs)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return SubmissionDetailSerializer
        if self.action == "create":
            return SubmissionCreateSerializer
        if self.action == "partial_update":
            return SubmissionUpdateSerializer
        return SubmissionListSerializer

    def retrieve(self, request, *args, **kwargs):
        sub = self.get_object()
        sub = Submission.objects.select_related("cycle", "department", "owner", "reviewed_by").prefetch_related(
            "entries__files", "events__actor"
        ).annotate(entry_count=Count("entries")).get(pk=sub.pk)
        return Response(SubmissionDetailSerializer(sub, context={"request": request}).data)

    def create(self, request, *args, **kwargs):
        user = request.user
        ser = SubmissionCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        cycle = d.get("cycle") or ReportingCycle.current()
        if cycle is None:
            raise DomainAPIError(code="NO_CYCLE", http_status=409, message="No reporting cycle is open yet.")
        if not cycle.accepts_submissions:
            raise CycleClosedError()
        department = d.get("department") or user.department
        if department is None:
            raise ValidationError({"department": "Choose your department."})
        existing = Submission.objects.filter(pillar=d["pillar"], cycle=cycle, owner=user).first()
        if existing:
            raise DomainAPIError(code="DUPLICATE_SUBMISSION", http_status=409,
                                 message="You already have a return for this pillar and year.",
                                 details={"submission_id": existing.pk})
        try:
            sub = Submission.objects.create(
                pillar=d["pillar"], cycle=cycle, owner=user, department=department,
                faculty_name=d.get("faculty_name") or user.full_name,
                faculty_email=d.get("faculty_email") or user.email,
                designation=d.get("designation") or user.designation,
                counts=validate_counts(d["pillar"], d.get("counts") or {}),
            )
        except IntegrityError:
            raise DomainAPIError(code="DUPLICATE_SUBMISSION", http_status=409,
                                 message="You already have a return for this pillar and year.")
        return Response(self._detail(sub), status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        sub = self.get_object()
        self._require_edit(sub)
        ser = SubmissionUpdateSerializer(sub, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        if "counts" in ser.validated_data:
            ser.validated_data["counts"] = validate_counts(sub.pillar, ser.validated_data["counts"])
        ser.save()
        return Response(self._detail(sub))

    def destroy(self, request, *args, **kwargs):
        sub = self.get_object()
        if not can_delete(request.user, sub):
            raise InsufficientPermissionError(required_permission="submission.delete")
        sub.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        sub = self.get_object()
        ser = TransitionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        services.transition(request.user, sub, ser.validated_data["action"], ser.validated_data["comment"])
        return Response(self._detail(sub))

    # helpers -------------------------------------------------------------------
    def _detail(self, sub):
        sub = Submission.objects.select_related("cycle", "department", "owner", "reviewed_by").prefetch_related(
            "entries__files", "events__actor"
        ).annotate(entry_count=Count("entries")).get(pk=sub.pk)
        return SubmissionDetailSerializer(sub, context={"request": self.request}).data

    def _require_edit(self, sub):
        if can_edit(self.request.user, sub):
            return
        if sub.owner_id == self.request.user.id:
            if not sub.cycle.accepts_submissions:
                raise CycleClosedError()
            raise SubmissionLockedError()
        raise InsufficientPermissionError(required_permission="submission.change")


class SectionEntryViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    """Entries (legacy sub-form rows). Multipart: ``data`` = JSON object, files keyed by field name."""

    serializer_class = SectionEntrySerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    capability_map = {"list": None, "retrieve": None, "create": None, "partial_update": None, "destroy": None}
    self_scoped_actions = {"list", "retrieve", "create", "partial_update", "destroy"}
    scope_queryset_by_capability = False
    filterset_fields = ["submission", "section"]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        visible = visible_submissions(self.request.user).values("pk")
        return SectionEntry.objects.filter(submission__in=visible).select_related("submission").prefetch_related(
            "files"
        )

    def _parse(self, request):
        raw = request.data.get("data", {})
        if isinstance(raw, str):
            try:
                raw = json.loads(raw or "{}")
            except json.JSONDecodeError:
                raise ValidationError({"data": "Must be a JSON object."})
        if not isinstance(raw, dict):
            raise ValidationError({"data": "Must be a JSON object."})
        return raw

    def _uploads(self, request, section):
        uploads = {}
        for f in file_fields(section):
            upload = request.FILES.get(f["name"])
            if upload:
                validate_upload(upload)
                uploads[f["name"]] = upload
        return uploads

    def _store(self, entry, uploads):
        for field, upload in uploads.items():
            EvidenceFile.objects.filter(entry=entry, field=field).delete()
            EvidenceFile.objects.create(
                entry=entry, field=field, file=upload, original_name=upload.name[:255], size=upload.size,
                content_type=getattr(upload, "content_type", "") or "", uploaded_by=self.request.user,
            )

    def _require_edit(self, sub):
        if can_edit(self.request.user, sub):
            return
        if sub.owner_id == self.request.user.id:
            raise CycleClosedError() if not sub.cycle.accepts_submissions else SubmissionLockedError()
        raise InsufficientPermissionError(required_permission="submission.change")

    def create(self, request, *args, **kwargs):
        try:
            sub = visible_submissions(request.user).get(pk=request.data.get("submission"))
        except (Submission.DoesNotExist, ValueError, TypeError):
            raise NotFound("Return not found.")
        self._require_edit(sub)
        section = request.data.get("section")
        if SECTION_PILLAR.get(section) != sub.pillar:
            raise ValidationError({"section": "This section doesn't belong to this pillar."})
        uploads = self._uploads(request, section)
        data = validate_entry_data(section, self._parse(request), existing_files=set(), incoming_files=set(uploads))
        with transaction.atomic():
            entry = SectionEntry.objects.create(submission=sub, section=section, data=data, created_by=request.user)
            self._store(entry, uploads)
            sub.save(update_fields=["updated_at"])
        return Response(self.get_serializer(entry).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        entry = self.get_object()
        self._require_edit(entry.submission)
        uploads = self._uploads(request, entry.section)
        incoming = self._parse(request)
        merged = {**entry.data, **incoming}
        existing = set(entry.files.values_list("field", flat=True))
        data = validate_entry_data(entry.section, merged, existing_files=existing, incoming_files=set(uploads))
        with transaction.atomic():
            entry.data = data
            entry.save()
            self._store(entry, uploads)
            entry.submission.save(update_fields=["updated_at"])
        entry.refresh_from_db()
        return Response(self.get_serializer(entry).data)

    def destroy(self, request, *args, **kwargs):
        entry = self.get_object()
        self._require_edit(entry.submission)
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EvidenceDownloadView(APIView):
    """Permission-checked evidence download (legacy served /Uploads/<guid> publicly)."""

    envelope = False

    def get(self, request, pk):
        ev = get_object_or_404(EvidenceFile.objects.select_related("entry__submission"), pk=pk)
        if not can_view(request.user, ev.entry.submission):
            raise InsufficientPermissionError(required_permission="submission.view")
        record_activity(ActivityAction.DOWNLOAD, request=request, target=ev,
                        description=f"Downloaded {ev.original_name}")
        ctype = ev.content_type or mimetypes.guess_type(ev.original_name)[0] or "application/octet-stream"
        inline = request.query_params.get("inline") in ("1", "true")
        resp = FileResponse(ev.file.open("rb"), content_type=ctype, as_attachment=not inline,
                            filename=ev.original_name)
        resp["X-Content-Type-Options"] = "nosniff"
        return resp
