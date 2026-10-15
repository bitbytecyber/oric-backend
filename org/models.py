from django.db import models
from django.utils import timezone


class Faculty(models.Model):
    """A NED faculty (school) headed by a Dean, e.g. Faculty of Electrical & Computer Engineering."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150, unique=True)
    short_name = models.CharField(max_length=80, blank=True)
    dean = models.ForeignKey("people.Person", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="dean_of")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "faculties"

    def __str__(self):
        return self.name


class Department(models.Model):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=20, unique=True)
    faculty = models.ForeignKey(Faculty, null=True, blank=True, on_delete=models.PROTECT, related_name="departments")
    chair = models.ForeignKey("people.Person", null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="chair_of")
    co_chairs = models.ManyToManyField("people.Person", blank=True, related_name="co_chair_of")
    website = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Organization(models.Model):
    """External body: funder, company, government department, MoU partner, licensee …

    Free-text answers are normalised onto these rows (``aliases`` keeps every
    spelling seen) so reports can group "HEC" / "Higher Education Commission".
    """

    name = models.CharField(max_length=255, unique=True)
    kind = models.CharField(max_length=30, blank=True, help_text="funder, company, government, academic, ngo …")
    country = models.CharField(max_length=80, blank=True)
    aliases = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ReportingCycle(models.Model):
    """One ORIC reporting year (HEC fiscal year runs 1 July – 30 June)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPEN = "open", "Open for submissions"
        CLOSED = "closed", "Closed"
        ARCHIVED = "archived", "Archived"

    label = models.CharField(max_length=40, unique=True, help_text='e.g. "FY 2025-26"')
    year = models.PositiveIntegerField(unique=True, help_text="Reporting year used in reports (fiscal year end).")
    starts_on = models.DateField()
    ends_on = models.DateField()
    submission_deadline = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    # Index-A denominators used by the scorecard (ratios are "per PhD faculty").
    phd_faculty_count = models.PositiveIntegerField(null=True, blank=True)
    sanctioned_faculty_posts = models.PositiveIntegerField(null=True, blank=True)
    existing_faculty_count = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-year"]

    def __str__(self):
        return self.label

    @property
    def accepts_submissions(self) -> bool:
        if self.status != self.Status.OPEN:
            return False
        return not self.submission_deadline or timezone.localdate() <= self.submission_deadline

    @classmethod
    def for_date(cls, d):
        if not d:
            return None
        return cls.objects.filter(starts_on__lte=d, ends_on__gte=d).first()

    @classmethod
    def current(cls):
        return cls.objects.filter(status=cls.Status.OPEN).order_by("-year").first() or cls.objects.first()


class TeamMember(models.Model):
    """ORIC team shown on the home page."""

    name = models.CharField(max_length=120)
    title = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    photo = models.ImageField(upload_to="team/", blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class ContactMessage(models.Model):
    """Replaces the legacy browser-side EmailJS contact form."""

    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    handled = models.BooleanField(default=False)
    handled_by = models.ForeignKey("people.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at"]
