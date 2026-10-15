import json
import mimetypes

from django.db.models import Prefetch, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import ActivityAction
from audit.services import record_activity
from org.models import ReportingCycle
from oric_backend.errors import InsufficientPermissionError, SubmissionLockedError
from people.models import Person
from rbac.viewsets import RBACViewSetMixin

from . import services
from .access import can_add, can_delete, can_edit, can_view, proxy_people, visible_submissions
from .filters import SubmissionFilter
from .models import Contributor, EvidenceFile, SavedView, Submission
from .registry import CATEGORY_BY_KEY, public_schema
from .serializers import (
    SavedViewSerializer,
    SubmissionDetailSerializer,
    SubmissionListSerializer,
    SubmissionWriteSerializer,
    TransitionSerializer,
)
from .validation import file_fields, validate_upload

LIST_RELATED = ("cycle", "department", "faculty", "owner", "organization", "submitted_by__person")


class FormSchemaView(APIView):
    """Pillars + every category definition (drives the SPA's dynamic forms)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(public_schema())


def detail_queryset():
    return Submission.objects.select_related(*LIST_RELATED, "verified_by__person", "lineage").prefetch_related(
        Prefetch("contributors", queryset=Contributor.objects.select_related("person__department", "person__user")),
        "files", "events__actor__person", "next_stages",
    )


class SubmissionViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    """Activity records. Scoping is own-data + capability scope (submissions/access.py).

    Create / update accept JSON, or multipart with ``payload`` (JSON string) and one
    file per file field (named after the field).
    """

    capability_map = {
        "list": None, "retrieve": None, "create": None, "partial_update": None, "destroy": None,
        "transition": None, "advance": None, "bulk_transition": "submission.verify", "proxy_people": None,
        "can_add": None, "people_search": None,
    }
    self_scoped_actions = {"list", "retrieve", "create", "partial_update", "destroy", "transition", "advance",
                           "proxy_people", "can_add", "people_search"}
    scope_queryset_by_capability = False
    filterset_class = SubmissionFilter
    ordering_fields = ["event_date", "updated_at", "created_at", "amount_pkr", "title", "status", "category",
                       "owner__full_name", "department__code"]
    ordering = ["-updated_at"]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        from .access import own_q

        qs = Submission.objects.select_related(*LIST_RELATED)
        if self.request.query_params.get("mine") in ("1", "true"):
            return qs.filter(own_q(self.request.user))
        # Drafts are private to whoever is writing them.
        return visible_submissions(self.request.user, qs).exclude(
            Q(status=Submission.Status.DRAFT) & ~own_q(self.request.user))

    def get_serializer_class(self):
        return SubmissionDetailSerializer if self.action == "retrieve" else SubmissionListSerializer

    def retrieve(self, request, *args, **kwargs):
        sub = self.get_object()
        return Response(self._detail(sub))

    # --- write -------------------------------------------------------------------
    def _payload(self, request):
        raw = request.data.get("payload") if "payload" in request.data else request.data
        if isinstance(raw, str):
            try:
                raw = json.loads(raw or "{}")
            except json.JSONDecodeError:
                raise ValidationError({"payload": "Must be a JSON object."})
        ser = SubmissionWriteSerializer(data=raw)
        ser.is_valid(raise_exception=True)
        out = dict(ser.validated_data)
        out["_keys"] = set(raw.keys()) if hasattr(raw, "keys") else set()
        return out

    def _uploads(self, request, category):
        uploads = {}
        for f in file_fields(category):
            upload = request.FILES.get(f["name"])
            if upload:
                validate_upload(upload)
                uploads[f["name"]] = upload
        return uploads

    def _owner(self, d):
        if d.get("owner"):
            return get_object_or_404(Person.objects.select_related("department__faculty"), pk=d["owner"])
        return None

    def create(self, request, *args, **kwargs):
        d = self._payload(request)
        if d["category"] not in CATEGORY_BY_KEY:
            raise ValidationError({"category": "Unknown category."})
        owner = self._owner(d)
        lead = _lead_person_id(d["category"], d.get("people") or [])
        target = Person.objects.filter(pk=lead).first() if lead else owner
        if not can_add(request.user, category=d["category"], person=target):
            raise InsufficientPermissionError(required_permission="submission.add_on_behalf",
                                              message="You can't record this for that person.")
        cycle = ReportingCycle.objects.filter(pk=d["cycle"]).first() if d.get("cycle") else None
        sub = services.save_submission(
            request.user, category=d["category"], data=d.get("data") or {}, people=d.get("people") or [],
            owner=owner, cycle=cycle, uploads=self._uploads(request, d["category"]), draft=not d.get("submit"),
        )
        if d.get("submit"):
            services.transition(request.user, sub, "submit")
        return Response(self._detail(sub), status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        sub = self.get_object()
        if not can_edit(request.user, sub):
            raise SubmissionLockedError() if can_view(request.user, sub) else InsufficientPermissionError(
                required_permission="submission.change")
        d = self._payload(request)
        owner = self._owner(d) or sub.owner
        cycle = ReportingCycle.objects.filter(pk=d["cycle"]).first() if d.get("cycle") else sub.cycle
        services.save_submission(
            request.user, instance=sub, category=sub.category, data={**(sub.data or {}), **(d.get("data") or {})},
            people=d.get("people") if "people" in d["_keys"] else [
                {"role": c.role, "person_id": c.person_id, "name": c.name, "designation": c.designation,
                 "affiliation": c.affiliation} for c in sub.contributors.all()],
            owner=owner, cycle=cycle, uploads=self._uploads(request, sub.category),
            draft=sub.status in (Submission.Status.DRAFT, Submission.Status.RETURNED) and not d.get("submit"),
        )
        sub.refresh_from_db()
        if d.get("submit") and sub.status in Submission.EDITABLE_STATUSES:
            services.transition(request.user, sub, "submit")
        return Response(self._detail(sub))

    def destroy(self, request, *args, **kwargs):
        sub = self.get_object()
        if not can_delete(request.user, sub):
            raise InsufficientPermissionError(required_permission="submission.delete")
        sub.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # --- workflow ----------------------------------------------------------------
    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        sub = self.get_object()
        ser = TransitionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        services.transition(request.user, sub, ser.validated_data["action"], ser.validated_data["comment"])
        return Response(self._detail(sub))

    @action(detail=False, methods=["post"], url_path="bulk-transition")
    def bulk_transition(self, request):
        ids = request.data.get("ids") or []
        act = request.data.get("action")
        comment = request.data.get("comment") or ""
        done, failed = [], []
        for sub in self.get_queryset().filter(pk__in=ids):
            try:
                services.transition(request.user, sub, act, comment)
                done.append(sub.pk)
            except Exception as exc:  # noqa: BLE001 - report per row
                failed.append({"id": sub.pk, "error": str(getattr(exc, "detail", exc))})
        return Response({"done": done, "failed": failed})

    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        sub = self.get_object()
        if not can_view(request.user, sub):
            raise InsufficientPermissionError(required_permission="submission.view")
        nxt = request.data.get("category")
        target = sub.owner
        if not can_add(request.user, category=nxt or sub.category, person=target):
            raise InsufficientPermissionError(required_permission="submission.add")
        new = services.advance(request.user, sub, nxt)
        return Response(self._detail(new), status=status.HTTP_201_CREATED)

    # --- helpers for the form ------------------------------------------------------
    @action(detail=False, methods=["get"], url_path="proxy-people")
    def proxy_people(self, request):
        q = (request.query_params.get("q") or "").strip()
        qs = proxy_people(request.user).select_related("department").filter(is_faculty=True)
        if q:
            qs = qs.filter(full_name__icontains=q)
        return Response([
            {"id": p.pk, "full_name": p.full_name, "designation": p.designation,
             "department_code": p.department.code if p.department_id else None,
             "avatar": p.avatar.url if p.avatar else None}
            for p in qs.order_by("full_name")[:50]
        ])

    @action(detail=False, methods=["get"], url_path="people")
    def people_search(self, request):
        """NED directory lookup for contributor pickers (names, designations, departments are public)."""
        q = (request.query_params.get("q") or "").strip()
        qs = Person.objects.select_related("department").filter(is_faculty=True)
        if q:
            from django.db.models import Q

            qs = qs.filter(Q(full_name__icontains=q) | Q(aliases__icontains=q) | Q(department__code__iexact=q))
        return Response([
            {"id": p.pk, "full_name": p.full_name, "designation": p.designation,
             "department_code": p.department.code if p.department_id else None,
             "avatar": p.avatar.url if p.avatar else None}
            for p in qs.order_by("full_name")[:30]
        ])

    @action(detail=False, methods=["get"], url_path="can-add")
    def can_add(self, request):
        """Categories the user may record for themselves / on behalf / as ORIC."""
        user = request.user
        own = getattr(user, "person", None) if hasattr(user, "person") else None
        out = {}
        for key, c in CATEGORY_BY_KEY.items():
            out[key] = {
                "self": can_add(user, category=key, person=own) if not c["oric_only"] else False,
                "oric": c["oric_only"] and can_add(user, category=key),
            }
        return Response({"categories": out, "proxy": proxy_people(user).exclude(user=user).exists()})

    def _detail(self, sub):
        return SubmissionDetailSerializer(detail_queryset().get(pk=sub.pk), context={"request": self.request}).data


def _lead_person_id(category, people):
    from .registry import lead_slot

    slot = lead_slot(CATEGORY_BY_KEY[category])
    if not slot:
        return None
    for p in people:
        if p.get("role") == slot["role"] and (p.get("person_id") or p.get("person")):
            return int(p.get("person_id") or p.get("person"))
    return None


class SavedViewViewSet(viewsets.ModelViewSet):
    serializer_class = SavedViewSerializer
    http_method_names = ["get", "post", "patch", "delete"]
    pagination_class = None

    def get_queryset(self):
        return SavedView.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class EvidenceDownloadView(APIView):
    """Permission-checked evidence download."""

    envelope = False

    def get(self, request, pk):
        ev = get_object_or_404(EvidenceFile.objects.select_related("submission"), pk=pk)
        if not can_view(request.user, ev.submission):
            raise InsufficientPermissionError(required_permission="submission.view")
        record_activity(ActivityAction.DOWNLOAD, request=request, target=ev,
                        description=f"Downloaded {ev.original_name}")
        ctype = ev.content_type or mimetypes.guess_type(ev.original_name)[0] or "application/octet-stream"
        inline = request.query_params.get("inline") in ("1", "true")
        resp = FileResponse(ev.file.open("rb"), content_type=ctype, as_attachment=not inline,
                            filename=ev.original_name)
        resp["X-Content-Type-Options"] = "nosniff"
        return resp
