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


def subject_params(request) -> tuple[str, int] | None:
    """``?level=person|department|faculty&id=…`` (activity report subject), validated."""
    level, obj_id = request.query_params.get("level"), request.query_params.get("id")
    if not level and not obj_id:
        return None
    if level not in services.SUMMARY_LEVELS or not str(obj_id or "").isdigit():
        raise ValidationError({"level": "Use level=person|department|faculty with a numeric id."})
    return level, int(obj_id)


def filtered_submissions(request, *, default_current_cycle=False, subject=None):
    """Visible submissions narrowed by the shared SubmissionFilter query params
    (``level``/``id`` of an activity report narrow to that person / department / faculty)."""
    qs = visible_submissions(request.user, Submission.objects.all())
    if request.query_params.get("mine") in ("1", "true"):
        from submissions.access import own_q

        qs = Submission.objects.filter(own_q(request.user))
    params = request.query_params.copy()
    params.pop("id", None)
    subject = subject or subject_params(request)
    if subject:
        params.setlist(subject[0], [str(subject[1])])
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


def _check_subject(request, subject):
    """Without ``submission.view`` a report can only be about yourself."""
    from oric_backend.errors import InsufficientPermissionError
    from rbac.utils import user_has_capability

    if request.user.is_superuser or user_has_capability(request.user, "submission.view"):
        return
    person = getattr(request.user, "person", None)
    if not (subject and subject[0] == "person" and person and person.pk == subject[1]):
        raise InsufficientPermissionError(required_permission="submission.view")


def summary_data(request) -> tuple[dict, object]:
    from django.core.exceptions import ObjectDoesNotExist

    subject = subject_params(request)
    if subject is None:
        person = getattr(request.user, "person", None)
        if person is None:
            raise ValidationError({"level": "Choose a person, department or faculty."})
        subject = ("person", person.pk)
    _check_subject(request, subject)
    try:
        subj = services.summary_subject(*subject)
    except ObjectDoesNotExist:
        raise ValidationError({"id": "Unknown person, department or faculty."})
    qs = filtered_submissions(request, default_current_cycle=True, subject=subject)
    if "status" not in request.query_params:
        qs = qs.exclude(status=Submission.Status.REJECTED)
    cycles = services.parse_cycles(request.query_params)
    return {"subject": subj, **services.summary(qs, cycles)}, qs


class SummaryView(CapabilityAPIViewMixin, APIView):
    """Multi-year activity report: ``?level=person|department|faculty&id=…&cycle=a,b,c``.

    Category × fiscal-year counts and amounts, drafts and rejected records left out. Without
    ``level``/``id`` the report is about the signed-in person; without ``submission.view`` only that is allowed.
    """

    required_capability = None
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data, _ = summary_data(request)
        return Response(data)


class ExportView(CapabilityAPIViewMixin, APIView):
    """``?format=csv|xlsx|xlsx_by_category|xlsx_summary|zip&columns=a,b&<any submission filter>``

    ``xlsx_summary`` is the multi-year activity report (``level``/``id``/``cycle`` as for /reports/summary/).

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
        stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
        name = "oric-submissions"
        if fmt == "xlsx_summary":
            data, qs = summary_data(request)
            qs = exports.prepare(qs)
            name = "oric-activity-report"
        else:
            qs = exports.prepare(filtered_submissions(request))
        count = qs.count()
        if fmt == "xlsx_summary":
            body = exports.to_xlsx_summary(qs, data)
            ctype, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
        elif fmt == "csv":
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
        resp["Content-Disposition"] = f'attachment; filename="{name}-{stamp}.{ext}"'
        return resp


class ExportColumnsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"columns": [{"key": k, "label": v[0]} for k, v in exports.BASE_COLUMNS.items()],
                         "default": exports.DEFAULT_COLUMNS})


class BosReportView(CapabilityAPIViewMixin, APIView):
    """Annex-A department report for its BOS: ``?department=&cycle=&include_pending=1&export_format=xlsx``."""

    required_capability = None
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from org.models import Department, ReportingCycle

        from . import bos

        p = request.query_params

        def pk(name):
            v = p.get(name) or ""
            if v and not v.isdigit():
                raise ValidationError({name: "Must be a number."})
            return int(v or 0)

        department = Department.objects.filter(pk=pk("department")).first()
        if department is None:
            raise ValidationError({"department": "Choose a department."})
        cycle = ReportingCycle.objects.filter(pk=pk("cycle")).first() or ReportingCycle.current()
        if cycle is None:
            raise ValidationError({"cycle": "Choose a fiscal year."})
        report = bos.compute(visible_submissions(request.user), department, cycle,
                             include_pending=p.get("include_pending") in ("1", "true"))
        if (p.get("export_format") or p.get("fmt")) != "xlsx":
            return Response(report)
        record_export(request, description=f"Exported Annex-A BOS report ({department.code}, {cycle.label})",
                      count=sum(len(r["records"]) for r in report["rows"]))
        resp = HttpResponse(bos.workbook(report),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = (f'attachment; filename="annex-a-bos-{department.code or department.pk}-'
                                       f'{cycle.label.replace("FY ", "")}.xlsx"')
        return resp
