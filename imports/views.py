import os
import tempfile

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from org.models import Department, ReportingCycle
from org.services.directory import FILES, import_directory
from people.models import Person
from rbac.viewsets import RBACViewSetMixin
from submissions.models import Submission
from submissions.registry import CATEGORY_BY_KEY

from .models import ImportBatch, ImportRow
from .services import category_csv
from .services.hec_workbook import import_workbook


class ImportBatchSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    cycle_label = serializers.CharField(source="cycle.label", read_only=True, default=None)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    unmatched = serializers.IntegerField(read_only=True, default=0)
    total_rows = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = ImportBatch
        fields = ["id", "kind", "kind_label", "status", "original_name", "cycle", "cycle_label", "options", "stats",
                  "log", "created_by_name", "created_at", "unmatched", "total_rows"]


class ImportRowSerializer(serializers.ModelSerializer):
    submission_title = serializers.CharField(source="submission.title", read_only=True, default=None)
    category_label = serializers.SerializerMethodField()
    batch_name = serializers.CharField(source="batch.original_name", read_only=True)

    class Meta:
        model = ImportRow
        fields = ["id", "batch", "batch_name", "ref", "table", "category", "category_label", "status", "raw",
                  "parsed", "message", "person_text", "suggestions", "submission", "submission_title",
                  "resolved_at"]

    def get_category_label(self, obj):
        c = CATEGORY_BY_KEY.get(obj.category)
        return c["short"] if c else ""


class _Rollback(Exception):
    pass


class ImportBatchViewSet(RBACViewSetMixin, viewsets.ModelViewSet):
    """Upload + history. POST multipart: kind, cycle, dry_run, file / files (directory), category."""

    serializer_class = ImportBatchSerializer
    capability_resource = "import"
    capability_map = {"list": "import.view", "retrieve": "import.view", "create": "import.run",
                      "destroy": "import.run", "template": "import.view"}
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "delete"]

    def get_queryset(self):
        return ImportBatch.objects.select_related("cycle", "created_by__person").annotate(
            unmatched=Count("rows", filter=Q(rows__status=ImportRow.Status.UNMATCHED)),
            total_rows=Count("rows"))

    def create(self, request, *args, **kwargs):
        kind = request.data.get("kind")
        dry = str(request.data.get("dry_run", "")).lower() in ("1", "true")
        cycle = ReportingCycle.objects.filter(pk=request.data.get("cycle")).first() or ReportingCycle.current()
        if kind == ImportBatch.Kind.DIRECTORY:
            files = {}
            for f in request.FILES.getlist("files") or request.FILES.values():
                name = os.path.basename(f.name).lower()
                if name in FILES:
                    files[name] = f.read().decode("utf-8-sig", errors="replace")
            if not files:
                raise ValidationError({"files": f"Upload one or more of: {', '.join(FILES)}."})
            result = import_directory(files, dry_run=dry)
            if dry:
                return Response({"dry_run": True, "result": result})
            batch = ImportBatch.objects.create(kind=kind, status=ImportBatch.Status.APPLIED,
                                               original_name=", ".join(sorted(files)), created_by=request.user,
                                               stats=result)
            return Response(self.get_serializer(self.get_queryset().get(pk=batch.pk)).data, status=201)

        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "Choose a file."})
        if kind == ImportBatch.Kind.HEC_WORKBOOK:
            replace = str(request.data.get("replace", "true")).lower() in ("1", "true")
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                for chunk in upload.chunks():
                    tmp.write(chunk)
                path = tmp.name
            try:
                if dry:
                    stats = {}
                    try:
                        with transaction.atomic():
                            batch = ImportBatch.objects.create(kind=kind, original_name=upload.name, cycle=cycle,
                                                               created_by=request.user, options={"replace": replace})
                            stats = import_workbook(batch, path, replace=replace, user=request.user)
                            log = batch.log
                            raise _Rollback
                    except _Rollback:
                        pass
                    return Response({"dry_run": True, "result": stats, "log": log})
                batch = ImportBatch.objects.create(kind=kind, original_name=upload.name, cycle=cycle,
                                                   created_by=request.user, options={"replace": replace})
                upload.seek(0)
                batch.file.save(upload.name, upload, save=True)
                import_workbook(batch, path, replace=replace, user=request.user)
            finally:
                os.unlink(path)
            return Response(self.get_serializer(self.get_queryset().get(pk=batch.pk)).data, status=201)

        if kind in (ImportBatch.Kind.CATEGORY_CSV, ImportBatch.Kind.FORM_RESPONSES):
            category = request.data.get("category")
            if category not in CATEGORY_BY_KEY:
                raise ValidationError({"category": "Pick a category."})
            rows = category_csv.read_table(upload.name, upload.read())
            if not rows:
                raise ValidationError({"file": "The file has no data rows."})
            batch = ImportBatch.objects.create(kind=kind, original_name=upload.name, cycle=cycle,
                                               created_by=request.user, options={"category": category})
            stats = category_csv.import_category(batch, category, rows, user=request.user, dry_run=dry)
            if dry:
                batch.delete()
                return Response({"dry_run": True, "result": stats})
            upload.seek(0)
            batch.file.save(upload.name, upload, save=False)
            batch.stats, batch.status = stats, ImportBatch.Status.APPLIED
            batch.save()
            return Response(self.get_serializer(self.get_queryset().get(pk=batch.pk)).data, status=201)
        raise ValidationError({"kind": "Unknown import kind."})

    def destroy(self, request, *args, **kwargs):
        """Roll back: delete every submission this batch created."""
        batch = self.get_object()
        n = Submission.objects.filter(import_batch=batch).count()
        Submission.objects.filter(import_batch=batch).delete()
        batch.status = ImportBatch.Status.ROLLED_BACK
        batch.save(update_fields=["status"])
        return Response({"deleted_submissions": n})

    @action(detail=False, methods=["get"])
    def template(self, request):
        category = request.query_params.get("category")
        if category not in CATEGORY_BY_KEY:
            raise ValidationError({"category": "Unknown category."})
        resp = HttpResponse(category_csv.template_csv(category), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="template-{category}.csv"'
        return resp


class ResolveSerializer(serializers.Serializer):
    person = serializers.IntegerField(required=False, allow_null=True)
    create = serializers.DictField(required=False)
    ignore = serializers.BooleanField(required=False, default=False)
    apply_to_same_name = serializers.BooleanField(required=False, default=True)


class ImportRowViewSet(RBACViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """The unmatched queue (``?status=unmatched``) and per-batch row log."""

    serializer_class = ImportRowSerializer
    capability_map = {"list": "import.view", "retrieve": "import.view", "resolve": "import.run"}
    filterset_fields = ["batch", "status", "category", "table"]
    search_fields = ["person_text", "ref"]

    def get_queryset(self):
        return ImportRow.objects.select_related("batch", "submission").order_by("person_text", "id")

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        row = self.get_object()
        ser = ResolveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        rows = [row]
        if d["apply_to_same_name"] and row.person_text:
            rows = list(ImportRow.objects.filter(status=ImportRow.Status.UNMATCHED, person_text=row.person_text))
        with transaction.atomic():
            if d["ignore"]:
                for r in rows:
                    r.status, r.resolved_by, r.resolved_at = ImportRow.Status.SKIPPED, request.user, timezone.now()
                    r.save()
                    if r.submission_id:
                        Submission.objects.filter(pk=r.submission_id).update(needs_match=False)
                return Response({"resolved": len(rows)})
            person = None
            if d.get("person"):
                person = Person.objects.select_related("department__faculty").get(pk=d["person"])
            elif d.get("create"):
                c = d["create"]
                dept = Department.objects.filter(pk=c.get("department")).first()
                person = Person.objects.create(full_name=c.get("full_name") or row.person_text[:255],
                                               designation=c.get("designation", ""), department=dept,
                                               is_phd="dr" in (c.get("full_name") or "").lower(), source="import")
            else:
                raise ValidationError({"person": "Pick a person, create one, or ignore."})
            spelled = row.parsed.get("_lead_name") or row.person_text.split(",")[0].strip()
            if spelled and spelled != person.full_name and spelled not in (person.aliases or []):
                person.aliases = [*(person.aliases or []), spelled[:255]]
                person.save(update_fields=["aliases"])
            for r in rows:
                sub = r.submission
                if sub:
                    sub.owner = person
                    sub.department = person.department
                    sub.faculty = person.department.faculty if person.department_id else None
                    sub.needs_match = False
                    sub.save()
                    lead = sub.contributors.filter(order=0).first()
                    if lead:
                        lead.person, lead.name = person, ""
                        lead.save()
                    sub.sync_departments()
                r.status, r.resolved_by, r.resolved_at = ImportRow.Status.RESOLVED, request.user, timezone.now()
                r.save()
        return Response({"resolved": len(rows), "person": {"id": person.pk, "full_name": person.full_name}})
