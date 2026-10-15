from django.conf import settings
from django.db import models


class ImportBatch(models.Model):
    """One uploaded file (directory CSV, HEC workbook, form responses, category CSV) and its outcome."""

    class Kind(models.TextChoices):
        DIRECTORY = "directory", "Directory CSVs"
        HEC_WORKBOOK = "hec_workbook", "HEC scorecard workbook"
        FORM_RESPONSES = "form_responses", "Google Form responses"
        CATEGORY_CSV = "category_csv", "Category CSV / XLSX"

    class Status(models.TextChoices):
        DRY_RUN = "dry_run", "Dry run"
        APPLIED = "applied", "Applied"
        FAILED = "failed", "Failed"
        ROLLED_BACK = "rolled_back", "Rolled back"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRY_RUN)
    file = models.FileField(upload_to="imports/%Y/%m/", blank=True)
    original_name = models.CharField(max_length=255, blank=True)
    cycle = models.ForeignKey("org.ReportingCycle", null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="import_batches")
    options = models.JSONField(default=dict, blank=True)
    stats = models.JSONField(default=dict, blank=True)
    log = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.original_name} · {self.created_at:%Y-%m-%d}"


class ImportRow(models.Model):
    """One source row. ``unmatched`` rows form the review queue ORIC resolves."""

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        UNMATCHED = "unmatched", "Needs matching"
        RESOLVED = "resolved", "Resolved"
        SKIPPED = "skipped", "Skipped"
        ERROR = "error", "Error"

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    ref = models.CharField(max_length=60, help_text="Sheet!row")
    table = models.CharField(max_length=30, blank=True, help_text="Excel table code, e.g. B.vi")
    category = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, db_index=True)
    raw = models.JSONField(default=dict)
    parsed = models.JSONField(default=dict, blank=True)
    message = models.TextField(blank=True)
    person_text = models.CharField(max_length=500, blank=True, help_text="Name string that failed to match.")
    suggestions = models.JSONField(default=list, blank=True, help_text="[{person_id, name, department, score}]")
    submission = models.ForeignKey("submissions.Submission", null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="import_rows")
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["batch", "id"]
