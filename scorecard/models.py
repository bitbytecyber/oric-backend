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
