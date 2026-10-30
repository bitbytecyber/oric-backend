import copy

from django.http import HttpResponse
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
from .models import InstitutionProfile, KpiOverride


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


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = InstitutionProfile
        fields = ["cycle", "details", "staff", "operations", "updated_at"]
        read_only_fields = ["cycle", "updated_at"]


class InstitutionProfileView(CapabilityAPIViewMixin, APIView):
    required_capability = "institution_profile.view"  # PATCH needs institution_profile.change

    def get_required_capability(self, request):
        return "institution_profile.view" if request.method == "GET" else "institution_profile.change"

    def get(self, request):
        cycle = _cycle(request)
        obj, _ = InstitutionProfile.objects.get_or_create(cycle=cycle)
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

    Overwrites the target year's profile; nothing else (records, overrides) is touched.
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
        target.save()
        for k in ("phd_faculty_count", "sanctioned_faculty_posts", "existing_faculty_count"):
            setattr(dst, k, getattr(src, k))
        dst.save(update_fields=["phd_faculty_count", "sanctioned_faculty_posts", "existing_faculty_count"])
        from audit.models import ActivityAction
        from audit.services import record_activity

        record_activity(ActivityAction.OTHER, request=request, target=target,
                        description=f"Copied Index-A from {src.label} to {dst.label}")
        return Response({"ok": True, "from": src.label, "to": dst.label})


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
