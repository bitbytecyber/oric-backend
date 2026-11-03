import os
import uuid

from django.conf import settings
from django.db import models


class InstitutionProfile(models.Model):
    """Index-A of the HEC workbook for one fiscal year: university details + ORIC human resource.

    ``details`` holds the key/value block (VC, Registrar, bank account, webpage …);
    ``staff`` the ORIC HR table rows; ``operations`` the Score Card section-A inputs
    (positions filled, steering committee / IRB meetings, ICT, webpage, database).
    """

    cycle = models.OneToOneField("org.ReportingCycle", on_delete=models.CASCADE, related_name="institution_profile")
    details = models.JSONField(default=dict, blank=True)
    staff = models.JSONField(default=list, blank=True)
    operations = models.JSONField(default=dict, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Institution profile · {self.cycle}"


class KpiOverride(models.Model):
    """Manual correction of one KPI for one fiscal year (reported number and/or self-assessed score)."""

    cycle = models.ForeignKey("org.ReportingCycle", on_delete=models.CASCADE, related_name="kpi_overrides")
    kpi = models.CharField(max_length=12)
    reported = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    hec_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True,
                                    help_text="Score as validated by HEC (entered after HEC review).")
    note = models.TextField(blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["cycle", "kpi"], name="uniq_kpi_override")]


OPERATION_KEYS = ("head", "manager_rm", "manager_ic", "support", "steering_committee", "sc_meetings",
                  "irb_meetings", "offices_ict", "webpage", "database")
STAFF_ITEM = "staff"
# Staff evidence that describes the person (not the year) and so follows the row into a cloned year.
STAFF_CARRY_DOC_TYPES = ("cv", "appointment_letter")


def institution_evidence_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"institution/{instance.cycle.year}/{instance.item_key}/{uuid.uuid4().hex}{ext}"


class InstitutionEvidence(models.Model):
    """A file or link backing one Index-A item: an operations key, or one ORIC staff row (``staff_id``).

    Files live under MEDIA_ROOT (never served publicly) and are downloaded through a capability-checked view.
    """

    class DocType(models.TextChoices):
        CV = "cv", "CV"
        APPOINTMENT_LETTER = "appointment_letter", "Appointment letter"
        NOTIFICATION = "notification", "Notification"
        MINUTES = "minutes", "Minutes"
        OTHER = "other", "Other"

    cycle = models.ForeignKey("org.ReportingCycle", on_delete=models.CASCADE, related_name="institution_evidence")
    item_key = models.CharField(max_length=40)
    staff_id = models.CharField(max_length=64, null=True, blank=True)
    doc_type = models.CharField(max_length=24, choices=DocType.choices, default=DocType.OTHER)
    file = models.FileField(upload_to=institution_evidence_upload_to, blank=True)
    url = models.URLField(max_length=1000, blank=True)
    label = models.CharField(max_length=255, blank=True)
    original_name = models.CharField(max_length=255, blank=True)
    size = models.PositiveIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["item_key", "staff_id", "uploaded_at", "pk"]
        indexes = [models.Index(fields=["cycle", "item_key"])]

    def __str__(self):
        return f"{self.item_key} · {self.label or self.original_name or self.url}"
