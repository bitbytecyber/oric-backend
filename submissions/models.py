"""One ``Submission`` = one activity (a grant proposal, a patent, an MoU …).

Faculty add them any time in the fiscal year; Chairmen / Deans / ORIC can add
them on someone's behalf (``submitted_by`` != owner's user). ORIC verifies.
Only *verified* submissions count on the HEC scorecard by default.
"""
import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

from .registry import CATEGORY_BY_KEY, CATEGORY_CHOICES, PILLAR_CHOICES


class Submission(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        VERIFIED = "verified", "Verified"
        RETURNED = "returned", "Returned"
        REJECTED = "rejected", "Rejected"

    class Source(models.TextChoices):
        PORTAL = "portal", "Portal"
        EXCEL = "excel_import", "HEC workbook import"
        FORM = "form_import", "Google Form import"
        CSV = "csv_import", "CSV import"

    class Scope(models.TextChoices):
        NATIONAL = "National", "National"
        INTERNATIONAL = "International", "International"

    class Funding(models.TextChoices):
        HEC = "HEC", "HEC"
        NON_HEC = "NON_HEC", "Non-HEC"
        JOINT = "JOINT", "Joint"

    EDITABLE_STATUSES = (Status.DRAFT, Status.RETURNED)

    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, db_index=True)
    pillar = models.CharField(max_length=4, choices=PILLAR_CHOICES, db_index=True)
    cycle = models.ForeignKey("org.ReportingCycle", on_delete=models.PROTECT, related_name="submissions")

    owner = models.ForeignKey("people.Person", null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="submissions", help_text="PI / lead. Empty for unmatched imports.")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="submissions_entered")
    department = models.ForeignKey("org.Department", null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="submissions", help_text="Owner's department at submission time.")
    faculty = models.ForeignKey("org.Faculty", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="submissions")
    departments = models.ManyToManyField("org.Department", blank=True, related_name="linked_submissions",
                                         help_text="Owner's + every NED contributor's department (for scoping).")

    # Promoted from ``data`` (see registry title_field/date_field/…) for filtering, sorting and the scorecard.
    title = models.CharField(max_length=500, blank=True)
    event_date = models.DateField(null=True, blank=True, db_index=True)
    amount_pkr = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    scope_level = models.CharField(max_length=13, choices=Scope.choices, blank=True)
    funding_source = models.CharField(max_length=8, choices=Funding.choices, blank=True)
    organization = models.ForeignKey("org.Organization", null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="submissions")

    data = models.JSONField(default=dict, blank=True)
    evidence_links = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="verified_submissions")
    verified_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(blank=True)

    lineage = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="next_stages",
                                help_text="Earlier stage of the same project (submitted → approved → completed).")

    source = models.CharField(max_length=14, choices=Source.choices, default=Source.PORTAL, db_index=True)
    import_batch = models.ForeignKey("imports.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="submissions")
    import_ref = models.CharField(max_length=60, blank=True, help_text="Sheet!row the record came from.")
    needs_match = models.BooleanField(default=False, db_index=True,
                                      help_text="Imported, but the PI / department could not be matched yet.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-event_date", "-updated_at"]
        indexes = [
            models.Index(fields=["cycle", "category", "status"]),
            models.Index(fields=["department", "cycle"]),
            models.Index(fields=["faculty", "cycle"]),
        ]

    def __str__(self):
        return f"{self.category_def['short']} · {self.title or self.pk}"

    @property
    def category_def(self) -> dict:
        return CATEGORY_BY_KEY[self.category]

    @property
    def is_editable(self) -> bool:
        return self.status in self.EDITABLE_STATUSES

    # --- promotion ------------------------------------------------------------
    def promote(self) -> None:
        """Copy the registry-declared fields of ``data`` onto the typed columns."""
        import datetime

        c = self.category_def
        d = self.data or {}
        self.pillar = c["pillar"]
        if c["title_field"]:
            self.title = str(d.get(c["title_field"]) or "")[:500]
        elif not self.title:
            self.title = c["short"]
        raw_date = d.get(c["date_field"]) if c["date_field"] else None
        if raw_date:
            try:
                self.event_date = datetime.date.fromisoformat(str(raw_date)[:10])
            except ValueError:
                pass
        amount = d.get(c["amount_field"]) if c["amount_field"] else None
        if amount not in (None, ""):
            try:
                v = Decimal(str(amount))
                self.amount_pkr = v * Decimal(1_000_000) if c["amount_unit"] == "M" else v
            except Exception:  # noqa: BLE001 - malformed numbers stay empty
                self.amount_pkr = None
        else:
            self.amount_pkr = None
        scope = d.get(c["scope_field"]) if c["scope_field"] else None
        self.scope_level = scope if scope in self.Scope.values else ""
        self.funding_source = c["funding_source"] or ""
        link = d.get("evidence_link")
        if link and link not in (self.evidence_links or []):
            self.evidence_links = [*(self.evidence_links or []), link]

    def sync_departments(self) -> None:
        ids = {self.department_id} if self.department_id else set()
        ids |= set(
            self.contributors.filter(person__department__isnull=False).values_list("person__department_id", flat=True)
        )
        self.departments.set(ids)


class Contributor(models.Model):
    """A person attached to a submission: PI, Co-PI, inventor, winner … NED staff are linked by ``person``."""

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="contributors")
    role = models.CharField(max_length=20)
    person = models.ForeignKey("people.Person", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="contributions")
    name = models.CharField(max_length=255, blank=True, help_text="As written (external people / unmatched).")
    designation = models.CharField(max_length=120, blank=True)
    affiliation = models.CharField(max_length=255, blank=True, help_text="Department / university / company.")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self) -> str:
        return self.person.full_name if self.person_id else self.name


def evidence_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    sub = instance.submission
    return f"evidence/{sub.cycle.year}/{sub.category}/{uuid.uuid4().hex}{ext}"


class EvidenceFile(models.Model):
    """File attached to a file-type field. Served only through an authenticated view."""

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="files")
    field = models.CharField(max_length=60)
    file = models.FileField(upload_to=evidence_upload_to)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["field", "uploaded_at"]
        constraints = [models.UniqueConstraint(fields=["submission", "field"], name="one_file_per_submission_field")]


class ReviewEvent(models.Model):
    """Status-change history of a submission (who moved it, from what, to what, why)."""

    class Action(models.TextChoices):
        CREATE = "create", "Created"
        SUBMIT = "submit", "Submitted"
        VERIFY = "verify", "Verified"
        RETURN = "return", "Returned for revision"
        REJECT = "reject", "Rejected"
        REOPEN = "reopen", "Reopened"
        COMMENT = "comment", "Comment"
        IMPORT = "import", "Imported"

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=10, choices=Action.choices)
    from_status = models.CharField(max_length=10, blank=True)
    to_status = models.CharField(max_length=10, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class SavedView(models.Model):
    """A named set of list filters a user saved (Submissions table / Explore)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_views")
    name = models.CharField(max_length=80)
    filters = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="uniq_saved_view_name")]
