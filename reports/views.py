from django.http import HttpResponse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_export
from rbac.viewsets import CapabilityAPIViewMixin
from submissions.access import visible_submissions
from submissions.filters import SubmissionFilter
from submissions.models import Submission

from . import exports, services


def filtered_submissions(request, *, default_current_cycle=False):
    """Visible submissions narrowed by the shared SubmissionFilter query params."""
    qs = visible_submissions(request.user, Submission.objects.all())
    if request.query_params.get("mine") in ("1", "true"):
        from submissions.access import own_q

        qs = Submission.objects.filter(own_q(request.user))
    params = request.query_params.copy()
    if default_current_cycle and not any(k in params for k in ("cycle", "year", "year_from", "year_to")):
        params.setlist("cycle", [str(c) for c in services.parse_cycles({})])
    if "status" not in params and request.query_params.get("include_drafts") not in ("1", "true"):
        qs = qs.exclude(status=Submission.Status.DRAFT)
    f = SubmissionFilter(params, queryset=qs, request=request)
    if not f.is_valid():
        raise ValidationError(f.errors)
    return f.qs


class HomeView(APIView):
    """Role-aware home dashboard."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cid = request.query_params.get("cycle")
        return Response(services.home(request.user, int(cid) if cid and cid.isdigit() else None))


class ExploreView(CapabilityAPIViewMixin, APIView):
    """Drill-down: ?level=university|faculty|department|person&id=…&cycle=1,2"""

    required_capability = None
    permission_classes = [IsAuthenticated]

    def get(self, request):
        root = services.view_root(request.user)
        level = request.query_params.get("level") or root["level"]
        obj_id = request.query_params.get("id") or root.get("id")
        if level == "self":
            person = getattr(request.user, "person", None)
            level, obj_id = "person", person.pk if person else None
        cycles = services.parse_cycles(request.query_params)
        try:
            data = services.explore(request.user, level=level, obj_id=int(obj_id) if obj_id else None,
                                    cycles=cycles)
        except Exception as exc:  # noqa: BLE001
            from django.core.exceptions import ObjectDoesNotExist

            if isinstance(exc, (ObjectDoesNotExist, ValueError, TypeError)):
                raise ValidationError({"level": "Unknown level or id."})
            raise
        data["root"] = root
        return Response(data)


class AnalyticsView(CapabilityAPIViewMixin, APIView):
    required_capability = "report.view"

    def get(self, request):
        qs = filtered_submissions(request, default_current_cycle=True)
        data = services.analytics(request.user, [], filters_qs=qs)
        data["trend"] = services.yearly_trend(request.user)
        return Response(data)


class ExportView(CapabilityAPIViewMixin, APIView):
    """``?format=csv|xlsx|xlsx_by_category|zip&columns=a,b&<any submission filter>``

    Faculty can export their own records (``mine=1``) without ``submission.export``.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from oric_backend.errors import InsufficientPermissionError
        from rbac.utils import user_has_capability

        mine = request.query_params.get("mine") in ("1", "true")
        if not mine and not user_has_capability(request.user, "submission.export"):
            raise InsufficientPermissionError(required_permission="submission.export")
        fmt = request.query_params.get("export_format") or request.query_params.get("fmt") or "xlsx"
        columns = [c for c in (request.query_params.get("columns") or "").split(",") if c]
        qs = exports.prepare(filtered_submissions(request))
        stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
        count = qs.count()
        if fmt == "csv":
            body, ctype, ext = exports.to_csv(qs, columns), "text/csv; charset=utf-8", "csv"
        elif fmt == "xlsx_by_category":
            body = exports.to_xlsx_by_category(qs)
            ctype, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
        elif fmt == "zip":
            body, ctype, ext = exports.evidence_zip(qs), "application/zip", "zip"
        else:
            body = exports.to_xlsx(qs, columns)
            ctype, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
        record_export(request, description=f"Exported {count} submissions as {fmt}", count=count)
        resp = HttpResponse(body, content_type=ctype)
        resp["Content-Disposition"] = f'attachment; filename="oric-submissions-{stamp}.{ext}"'
        return resp


class ExportColumnsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"columns": [{"key": k, "label": v[0]} for k, v in exports.BASE_COLUMNS.items()],
                         "default": exports.DEFAULT_COLUMNS})
