import copy
import mimetypes
import uuid

from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_export
from org.models import ReportingCycle
from rbac.viewsets import CapabilityAPIViewMixin

from . import engine, hec_workbook
from .kpis import KPI_BY_CODE
from .models import (OPERATION_KEYS, STAFF_CARRY_DOC_TYPES, STAFF_ITEM, InstitutionEvidence, InstitutionProfile,
                     KpiOverride)


def _cycle(request):
    cid = request.query_params.get("cycle") or request.data.get("cycle") if hasattr(request, "data") else None
    if cid:
        return get_object_or_404(ReportingCycle, pk=cid)
    cur = ReportingCycle.current()
    if not cur:
        from oric_backend.errors import DomainAPIError

        raise DomainAPIError(code="NO_CYCLE", http_status=409, message="No fiscal year is configured.")
    return cur


def _int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


class ScorecardView(CapabilityAPIViewMixin, APIView):
    """``?cycle=&include_pending=1&faculty=&department=``"""

    required_capability = "scorecard.view"

    def get(self, request):
        cycle = _cycle(request)
        data = engine.compute(cycle, include_pending=request.query_params.get("include_pending") in ("1", "true"),
                              faculty_id=_int(request.query_params.get("faculty")),
                              department_id=_int(request.query_params.get("department")))
        return Response({**data, "framework": cycle.framework, "framework_label": cycle.get_framework_display()})


class AsSubmittedView(CapabilityAPIViewMixin, APIView):
    """The Score Card exactly as filed in the year's HEC workbook (any template), from its latest import.
    ``?cycle=`` → ``{card: null}`` when the year has no workbook import."""

    required_capability = "scorecard.view"

    def get(self, request):
        from imports.models import ImportBatch

        cycle = _cycle(request)
        # the newest full import: table-only re-runs (stats["only"]) don't stand for the year's filed Score Card
        batch = (ImportBatch.objects.filter(cycle=cycle, kind=ImportBatch.Kind.HEC_WORKBOOK,
                                            status=ImportBatch.Status.APPLIED)
                 .exclude(stats__has_key="only").order_by("-created_at").first())
        card = (batch.stats.get("as_submitted") or None) if batch else None
        return Response({
            "cycle": cycle.pk, "cycle_label": cycle.label, "framework": cycle.framework,
            "framework_label": cycle.get_framework_display(), "card": card,
            "batch": batch.pk if batch else None, "file": batch.original_name if batch else None,
            "imported_at": batch.created_at if batch else None,
            # e.g. FY 2025-26 workbook whose Score Card still says "Reported Numbers (FY 2024-25)"
            "reported_fy_mismatch": bool(card and card.get("reported_fy") and card["reported_fy"] != cycle.label),
        })


class OverrideSerializer(serializers.Serializer):
    cycle = serializers.IntegerField()
    kpi = serializers.CharField()
    reported = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, allow_null=True)
    score = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    hec_score = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True)

    def validate_kpi(self, v):
        if v not in KPI_BY_CODE:
            raise serializers.ValidationError("Unknown KPI.")
        return v

    def validate(self, attrs):
        kpi = KPI_BY_CODE[attrs["kpi"]]
        for k in ("score", "hec_score"):
            if attrs.get(k) is not None and not (0 <= float(attrs[k]) <= kpi["max"]):
                raise serializers.ValidationError({k: f"Must be between 0 and {kpi['max']}."})
        return attrs


class OverrideView(CapabilityAPIViewMixin, APIView):
    required_capability = "scorecard.override"

    def post(self, request):
        ser = OverrideSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        obj, _ = KpiOverride.objects.get_or_create(cycle_id=d["cycle"], kpi=d["kpi"])
        for k in ("reported", "score", "hec_score", "note"):
            if k in d:
                setattr(obj, k, d[k])
        obj.updated_by = request.user
        if obj.reported is None and obj.score is None and obj.hec_score is None and not obj.note:
            obj.delete()
        else:
            obj.save()
        return Response({"ok": True})


def ensure_staff_ids(staff) -> bool:
    """Give every staff row a stable ``id`` (evidence hangs off it). Returns True when a row was changed."""
    changed = False
    for row in staff if isinstance(staff, list) else []:
        if isinstance(row, dict) and not row.get("id"):
            row["id"] = uuid.uuid4().hex
            changed = True
    return changed


def _delete_evidence(qs):
    for ev in qs:
        if ev.file:
            ev.file.delete(save=False)
        ev.delete()


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = InstitutionProfile
        fields = ["cycle", "details", "staff", "operations", "updated_at"]
        read_only_fields = ["cycle", "updated_at"]

    def validate_staff(self, rows):
        """Keep the ids of existing rows, mint ids for new ones.

        A row sent without an id is matched to an unclaimed existing row with the same name and position
        (older clients), otherwise it is new.
        """
        if not isinstance(rows, list):
            raise serializers.ValidationError("Expected a list of rows.")
        existing = [r for r in (self.instance.staff if self.instance else []) or [] if isinstance(r, dict)]
        known = {r.get("id") for r in existing if r.get("id")}
        used, out = set(), []
        for row in rows:
            if not isinstance(row, dict):
                raise serializers.ValidationError("Each row must be an object.")
            row = dict(row)
            rid = row.get("id")
            if not (isinstance(rid, str) and rid in known and rid not in used):
                rid = next((r["id"] for r in existing
                            if r.get("id") and r["id"] not in used and not row.get("id")
                            and r.get("name") == row.get("name") and r.get("position") == row.get("position")),
                           None)
            row["id"] = rid or uuid.uuid4().hex
            used.add(row["id"])
            out.append(row)
        return out


class InstitutionProfileView(CapabilityAPIViewMixin, APIView):
    required_capability = "institution_profile.view"  # PATCH needs institution_profile.change

    def get_required_capability(self, request):
        return "institution_profile.view" if request.method == "GET" else "institution_profile.change"

    def get(self, request):
        cycle = _cycle(request)
        obj, _ = InstitutionProfile.objects.get_or_create(cycle=cycle)
        if ensure_staff_ids(obj.staff):  # rows written by the HEC workbook import carry no id yet
            InstitutionProfile.objects.filter(pk=obj.pk).update(staff=obj.staff)
        return Response({**ProfileSerializer(obj).data, "cycle_label": cycle.label,
                         "phd_faculty_count": cycle.phd_faculty_count,
                         "sanctioned_faculty_posts": cycle.sanctioned_faculty_posts,
                         "existing_faculty_count": cycle.existing_faculty_count})

    def patch(self, request):
        cycle = _cycle(request)
        obj, _ = InstitutionProfile.objects.get_or_create(cycle=cycle)
        ser = ProfileSerializer(obj, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save(updated_by=request.user)
        if "staff" in ser.validated_data:  # evidence of removed staff rows goes with them
            keep = [r["id"] for r in obj.staff]
            _delete_evidence(InstitutionEvidence.objects.filter(cycle=cycle, item_key=STAFF_ITEM)
                             .exclude(staff_id__in=keep))
        changed = []
        for k in ("phd_faculty_count", "sanctioned_faculty_posts", "existing_faculty_count"):
            if k in request.data:
                setattr(cycle, k, _int(request.data.get(k)))
                changed.append(k)
        if changed:
            cycle.save(update_fields=changed)
        return self.get(request)


class CloneProfileView(CapabilityAPIViewMixin, APIView):
    """Copy another fiscal year's Index-A (details, ORIC staff, operations, faculty strength) into ``to``.

    Overwrites the target year's profile. Staff CVs and appointment letters follow their rows (files are
    duplicated, so either year can delete its own); operations evidence belongs to its year and is not copied.
    Nothing else (records, overrides) is touched.
    """

    required_capability = "institution_profile.change"

    def post(self, request):
        src = get_object_or_404(ReportingCycle, pk=request.data.get("from_cycle"))
        dst = get_object_or_404(ReportingCycle, pk=request.data.get("to_cycle"))
        if src.pk == dst.pk:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"from_cycle": "Pick a different fiscal year to copy from."})
        source = InstitutionProfile.objects.filter(cycle=src).first()
        target, _ = InstitutionProfile.objects.get_or_create(cycle=dst)
        target.details = copy.deepcopy(source.details) if source else {}
        target.staff = copy.deepcopy(source.staff) if source else []
        target.operations = copy.deepcopy(source.operations) if source else {}
        target.updated_by = request.user
        with transaction.atomic():
            if source and ensure_staff_ids(source.staff):
                InstitutionProfile.objects.filter(pk=source.pk).update(staff=source.staff)
                target.staff = copy.deepcopy(source.staff)
            target.save()
            _delete_evidence(InstitutionEvidence.objects.filter(cycle=dst, item_key=STAFF_ITEM))
            ids = [r["id"] for r in target.staff if isinstance(r, dict) and r.get("id")]
            for ev in InstitutionEvidence.objects.filter(cycle=src, item_key=STAFF_ITEM, staff_id__in=ids,
                                                         doc_type__in=STAFF_CARRY_DOC_TYPES):
                _copy_evidence(ev, dst, request.user)
        for k in ("phd_faculty_count", "sanctioned_faculty_posts", "existing_faculty_count"):
            setattr(dst, k, getattr(src, k))
        dst.save(update_fields=["phd_faculty_count", "sanctioned_faculty_posts", "existing_faculty_count"])
        from audit.models import ActivityAction
        from audit.services import record_activity

        record_activity(ActivityAction.OTHER, request=request, target=target,
                        description=f"Copied Index-A from {src.label} to {dst.label}")
        return Response({"ok": True, "from": src.label, "to": dst.label})


def _copy_evidence(ev, cycle, user):
    dup = InstitutionEvidence(cycle=cycle, item_key=ev.item_key, staff_id=ev.staff_id, doc_type=ev.doc_type,
                              url=ev.url, label=ev.label, original_name=ev.original_name, size=ev.size,
                              content_type=ev.content_type, uploaded_by=ev.uploaded_by or user)
    if ev.file:
        with ev.file.open("rb") as fh:
            dup.file.save(ev.original_name or ev.file.name, ContentFile(fh.read()), save=False)
    dup.save()
    return dup


class EvidenceSerializer(serializers.ModelSerializer):
    kind = serializers.SerializerMethodField()
    doc_type_label = serializers.CharField(source="get_doc_type_display", read_only=True)
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = InstitutionEvidence
        fields = ["id", "cycle", "item_key", "staff_id", "doc_type", "doc_type_label", "kind", "label", "url",
                  "original_name", "size", "content_type", "uploaded_by_name", "uploaded_at"]

    def get_kind(self, obj):
        return "file" if obj.file else "link"

    def get_uploaded_by_name(self, obj):
        u = obj.uploaded_by
        return (u.full_name or u.email) if u else ""


class EvidenceInputSerializer(serializers.Serializer):
    item_key = serializers.ChoiceField(choices=[*OPERATION_KEYS, STAFF_ITEM])
    staff_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=64)
    doc_type = serializers.ChoiceField(choices=InstitutionEvidence.DocType.choices,
                                       default=InstitutionEvidence.DocType.OTHER)
    label = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")
    url = serializers.URLField(required=False, allow_blank=True, max_length=1000, default="")

    def validate(self, attrs):
        if attrs["item_key"] == STAFF_ITEM:
            if not attrs.get("staff_id"):
                raise serializers.ValidationError({"staff_id": "Pick the staff row this document belongs to."})
            if attrs["staff_id"] not in self.context["staff_ids"]:
                raise serializers.ValidationError({"staff_id": "Unknown staff row; save the staff table first."})
        else:
            attrs["staff_id"] = None
        return attrs


class InstitutionEvidenceView(CapabilityAPIViewMixin, APIView):
    """``GET ?cycle=[&item_key=]`` lists a year's Index-A evidence. ``POST`` (multipart) adds files and/or a link:
    ``cycle, item_key, staff_id?, doc_type, label?, url?, file*`` (one evidence row per file, plus one for the link).
    """

    required_capability = "institution_profile.view"  # POST needs institution_profile.change

    def get_required_capability(self, request):
        return "institution_profile.view" if request.method == "GET" else "institution_profile.change"

    def get(self, request):
        cycle = _cycle(request)
        qs = InstitutionEvidence.objects.filter(cycle=cycle).select_related("uploaded_by")
        if request.query_params.get("item_key"):
            qs = qs.filter(item_key=request.query_params["item_key"])
        return Response(EvidenceSerializer(qs, many=True).data)

    def post(self, request):
        from rest_framework.exceptions import ValidationError

        from submissions.validation import validate_upload

        cycle = _cycle(request)
        profile, _ = InstitutionProfile.objects.get_or_create(cycle=cycle)
        staff_ids = {r.get("id") for r in profile.staff or [] if isinstance(r, dict)}
        ser = EvidenceInputSerializer(data=request.data, context={"staff_ids": staff_ids})
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        files = request.FILES.getlist("file")
        if not files and not d["url"]:
            raise ValidationError({"file": "Attach a file or paste a link."})
        for f in files:
            validate_upload(f)
        base = dict(cycle=cycle, item_key=d["item_key"], staff_id=d["staff_id"], doc_type=d["doc_type"],
                    label=d["label"], uploaded_by=request.user)
        created = []
        with transaction.atomic():
            for f in files:
                ev = InstitutionEvidence(**base, original_name=f.name[:255], size=f.size,
                                         content_type=getattr(f, "content_type", "") or "")
                ev.file.save(f.name, f, save=False)
                ev.save()
                created.append(ev)
            if d["url"]:
                created.append(InstitutionEvidence.objects.create(**base, url=d["url"]))
        return Response(EvidenceSerializer(created, many=True).data, status=201)


class InstitutionEvidenceDetailView(CapabilityAPIViewMixin, APIView):
    required_capability = "institution_profile.change"

    def delete(self, request, pk):
        _delete_evidence([get_object_or_404(InstitutionEvidence, pk=pk)])
        return Response(status=204)


class InstitutionEvidenceDownloadView(CapabilityAPIViewMixin, APIView):
    """Permission-checked download of an Index-A evidence file (``?inline=1`` to view it in the browser)."""

    required_capability = "institution_profile.view"
    envelope = False

    def get(self, request, pk):
        from audit.models import ActivityAction
        from audit.services import record_activity

        ev = get_object_or_404(InstitutionEvidence, pk=pk)
        if not ev.file:
            raise Http404("This evidence is a link, not a file.")
        record_activity(ActivityAction.DOWNLOAD, request=request, target=ev,
                        description=f"Downloaded Index-A evidence {ev.original_name}")
        name = ev.original_name or ev.file.name.rsplit("/", 1)[-1]
        ctype = ev.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        inline = request.query_params.get("inline") in ("1", "true")
        resp = FileResponse(ev.file.open("rb"), content_type=ctype, as_attachment=not inline, filename=name)
        resp["X-Content-Type-Options"] = "nosniff"
        return resp


class HecWorkbookView(CapabilityAPIViewMixin, APIView):
    required_capability = "scorecard.view"

    def get(self, request):
        cycle = _cycle(request)
        body = hec_workbook.build(cycle, include_pending=request.query_params.get("include_pending") in ("1", "true"))
        record_export(request, description=f"HEC scorecard workbook {cycle.label}")
        resp = HttpResponse(body, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        stamp = timezone.localtime().strftime("%Y%m%d")
        resp["Content-Disposition"] = (f'attachment; filename="ORIC-Self-Assessment-Scorecard-'
                                       f'{cycle.label.replace(" ", "-")}-{stamp}.xlsx"')
        return resp
