import os
import uuid

from django.conf import settings
from django.db import models

from .registry import PILLARS, SECTION_BY_KEY, section_count_fields

PILLAR_CHOICES = [(p["key"], p["name"]) for p in PILLARS]
SECTION_CHOICES = [(k, f'{k} · {s["title"]}') for k, s in SECTION_BY_KEY.items()]


class Submission(models.Model):
    """One faculty member's annual return for one pillar (legacy RicForm1/2/3 header)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        RETURNED = "returned", "Returned for revision"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    EDITABLE_STATUSES = (Status.DRAFT, Status.RETURNED)

    pillar = models.CharField(max_length=3, choices=PILLAR_CHOICES)
    cycle = models.ForeignKey("org.ReportingCycle", on_delete=models.PROTECT, related_name="submissions")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="submissions")
    department = models.ForeignKey("org.Department", on_delete=models.PROTECT, related_name="submissions")

    # Snapshot of the faculty details printed on the return (legacy header fields).
    faculty_name = models.CharField(max_length=150)
    faculty_email = models.EmailField()
    designation = models.CharField(max_length=120, blank=True)

    counts = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)

    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_submissions"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["pillar", "cycle", "owner"], name="one_submission_per_pillar_cycle_owner"),
        ]
        indexes = [models.Index(fields=["pillar", "status"]), models.Index(fields=["department", "cycle"])]

    def __str__(self):
        return f"{self.get_pillar_display()} · {self.faculty_name} · {self.cycle}"

    @property
    def is_editable(self) -> bool:
        return self.status in self.EDITABLE_STATUSES

    def entry_progress(self) -> list[dict]:
        """Declared (counts) vs provided (entries) per section — legacy never reconciled these."""
        from .registry import PILLAR_BY_KEY

        provided = dict(self.entries.values("section").annotate(n=models.Count("id")).values_list("section", "n"))
        rows = []
        for s in PILLAR_BY_KEY[self.pillar]["sections"]:
            declared = sum(int(self.counts.get(f) or 0) for f in section_count_fields(s))
            rows.append({
                "section": s["key"],
                "title": s["title"],
                "declared": declared,
                "provided": provided.get(s["key"], 0),
            })
        return rows

    def missing_entries(self) -> list[dict]:
        return [r for r in self.entry_progress() if r["provided"] < r["declared"]]


class SectionEntry(models.Model):
    """One activity record inside a submission (legacy sub-form row, e.g. one HEC grant proposal)."""

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="entries")
    section = models.CharField(max_length=4, choices=SECTION_CHOICES)
    data = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section", "created_at"]
        indexes = [models.Index(fields=["section"])]

    def __str__(self):
        return f"{self.section} #{self.pk}"

    @property
    def section_def(self):
        return SECTION_BY_KEY[self.section]

    @property
    def amount(self):
        field = self.section_def.get("amount_field")
        if not field:
            return None
        try:
            return float(self.data.get(field) or 0)
        except (TypeError, ValueError):
            return 0.0


def evidence_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    sub = instance.entry.submission
    return f"evidence/{sub.cycle.year}/{sub.pillar}/{instance.entry.section}/{uuid.uuid4().hex}{ext}"


class EvidenceFile(models.Model):
    """File attached to a file-type field of an entry. Served only through an authenticated view."""

    entry = models.ForeignKey(SectionEntry, on_delete=models.CASCADE, related_name="files")
    field = models.CharField(max_length=60)
    file = models.FileField(upload_to=evidence_upload_to)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["field", "uploaded_at"]
        constraints = [models.UniqueConstraint(fields=["entry", "field"], name="one_file_per_entry_field")]


class ReviewEvent(models.Model):
    """Status-change history of a submission (who moved it, from what, to what, why)."""

    class Action(models.TextChoices):
        SUBMIT = "submit", "Submitted"
        START_REVIEW = "start_review", "Review started"
        RETURN = "return", "Returned for revision"
        APPROVE = "approve", "Approved"
        REJECT = "reject", "Rejected"
        REOPEN = "reopen", "Reopened"
        COMMENT = "comment", "Comment"

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=15, choices=Action.choices)
    from_status = models.CharField(max_length=15, blank=True)
    to_status = models.CharField(max_length=15, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
