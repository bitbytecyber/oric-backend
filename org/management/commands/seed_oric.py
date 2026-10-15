"""Seed reference data, the NED directory, last year's HEC workbook and (optionally) demo activity.

    python manage.py seed_oric                              # fiscal years, RBAC, directory (org/seed/*.csv + photos/)
    python manage.py seed_oric --workbook .local/hec_fy2024-25.xlsx   # + import FY 2024-25 HEC workbook
    python manage.py seed_oric --demo                       # + synthetic FY 2025-26 portal submissions
    python manage.py seed_oric --reset-demo --demo          # wipe synthetic submissions first

Every directory account gets ``ORIC_DEMO_PASSWORD`` (default ``OricDemo#2026``) in demo mode so any
role can be tried. Synthetic submissions are tagged ``data._demo`` and never touch imported data.
"""
import os
import random

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from imports.models import ImportBatch
from org.models import ReportingCycle
from org.services.demo_data import make_pdf, make_project, value_for
from org.services.directory import import_directory, read_seed_dir
from org.services.seed import seed_cycles
from people.models import Person, User
from people.services.profile import provision_user
from rbac.models import AccessRole, RoleAssignment
from rbac.services.seed import seed_roles, sync_capabilities
from submissions.models import EvidenceFile, ReviewEvent, Submission
from submissions.registry import CATEGORIES, lead_slot

DEMO_ADMIN = "admin@oric.test"
FACULTY_CATEGORY_WEIGHTS = {
    "grant_hec_submitted": 6, "grant_nonhec_submitted": 8, "grant_nonhec_approved": 4, "grant_hec_approved": 2,
    "joint_submitted": 2, "contract_research": 4, "policy_advocacy": 3, "research_link": 3, "civic_engagement": 2,
    "consultancy_contract": 4, "publication": 9, "ip_disclosure": 2, "patent": 2, "prototype": 2,
    "creative_product": 1, "industry_visit": 1, "collaboration_agreement": 1, "award": 2, "training_external": 2,
    "startup": 1, "entrepreneurship_event": 1,
}


class Command(BaseCommand):
    help = "Seed fiscal years, RBAC, NED directory; optionally import the HEC workbook and demo activity."

    def add_arguments(self, parser):
        parser.add_argument("--workbook", default="", help="HEC scorecard workbook to import into FY 2024-25.")
        parser.add_argument("--workbook-year", type=int, default=2025)
        parser.add_argument("--demo", action="store_true", help="Synthetic FY 2025-26 submissions + demo password.")
        parser.add_argument("--reset-demo", action="store_true", help="Delete synthetic submissions first.")
        parser.add_argument("--seed", type=int, default=2026)
        parser.add_argument("--superuser-email", default=os.environ.get("ORIC_SUPERUSER_EMAIL", ""))
        parser.add_argument("--superuser-password", default=os.environ.get("ORIC_SUPERUSER_PASSWORD", ""))

    def handle(self, *args, **o):
        password = os.environ.get("ORIC_DEMO_PASSWORD") or ("OricDemo#2026" if o["demo"] else None)
        with transaction.atomic():
            seed_cycles()
            sync_capabilities()
            seed_roles(reconcile=True)
            files = read_seed_dir()
            if files:
                res = import_directory(files, password=password)
                self.stdout.write(self.style.SUCCESS(
                    "Directory: " + ", ".join(f"{k} +{v['created']}" for k, v in res.items()
                                              if isinstance(v, dict) and "created" in v and isinstance(v["created"], int))))
            else:
                self.stdout.write(self.style.WARNING("org/seed/*.csv not found - directory not imported."))
            if o["superuser_email"] and o["superuser_password"]:
                provision_user(email=o["superuser_email"], full_name="System Administrator",
                               password=o["superuser_password"], is_staff=True, is_superuser=True,
                               must_change_password=False)
            if o["demo"]:
                provision_user(email=DEMO_ADMIN, full_name="Portal Administrator", password=password,
                               designation="System administrator", must_change_password=False)
                admin = User.objects.get(email=DEMO_ADMIN)
                RoleAssignment.objects.get_or_create(user=admin, role=AccessRole.objects.get(slug="admin"),
                                                     department=None, faculty=None, is_active=True)
                User.objects.update(must_change_password=False)  # demo: no forced password change

        if o["workbook"]:
            self._workbook(o["workbook"], o["workbook_year"])
        if o["reset_demo"]:
            self._reset_demo()
        if o["demo"]:
            self._demo(o["seed"])

    # ------------------------------------------------------------------------------------------
    def _workbook(self, path, year):
        from imports.services.hec_workbook import import_workbook

        cycle = ReportingCycle.objects.get(year=year)
        batch = ImportBatch.objects.create(kind=ImportBatch.Kind.HEC_WORKBOOK, original_name=os.path.basename(path),
                                           cycle=cycle, options={"replace": True})
        stats = import_workbook(batch, path)
        self.stdout.write(self.style.SUCCESS(
            f"Workbook {cycle.label}: {stats['created']} records, {stats['unmatched']} to match."))

    def _reset_demo(self):
        qs = Submission.objects.filter(data___demo=True)
        for ev in EvidenceFile.objects.filter(submission__in=qs):
            ev.file.delete(save=False)
        n = qs.count()
        qs.delete()
        self.stdout.write(self.style.WARNING(f"Removed {n} synthetic submissions."))

    def _demo(self, seed):
        cycle = ReportingCycle.current()
        if not cycle:
            return
        if Submission.objects.filter(data___demo=True, cycle=cycle).exists():
            self.stdout.write("Demo submissions already exist (use --reset-demo to rebuild).")
            return
        rng = random.Random(seed)
        people = list(Person.objects.filter(is_faculty=True, user__isnull=False, department__isnull=False)
                      .select_related("department__faculty", "user"))
        verifier = User.objects.filter(role_assignments__role__slug="oric_director").first() or \
            User.objects.get(email=DEMO_ADMIN)
        cats = {c["key"]: c for c in CATEGORIES}
        keys, weights = zip(*FACULTY_CATEGORY_WEIGHTS.items())
        made = 0
        with transaction.atomic():
            for person in people:
                if rng.random() > 0.45:
                    continue
                for _ in range(rng.choice([1, 1, 2, 2, 3, 4])):
                    c = cats[rng.choices(keys, weights)[0]]
                    sub = self._make(rng, person, c, cycle, verifier)
                    made += bool(sub)
        self.stdout.write(self.style.SUCCESS(f"Demo: {made} synthetic FY {cycle.label} submissions."))

    def _make(self, rng, person, c, cycle, verifier):
        ctx = {"person": person, "year": cycle.year, "project": make_project(rng)}
        data = {}
        for f in c["fields"]:
            v = value_for(f, c["key"], ctx, rng)
            if v not in (None, ""):
                data[f["name"]] = v
        data["_demo"] = True
        status = rng.choices([Submission.Status.DRAFT, Submission.Status.SUBMITTED, Submission.Status.VERIFIED,
                              Submission.Status.RETURNED], [1, 4, 5, 0.6])[0]
        # a third are entered by the chairman on the member's behalf
        chair = person.department.chair if person.department_id else None
        by = chair.user if chair and chair.user_id and rng.random() < 0.3 else person.user
        sub = Submission(category=c["key"], cycle=cycle, owner=person, submitted_by=by, data=data, status=status,
                         department=person.department, faculty=person.department.faculty)
        sub.promote()
        now = timezone.now()
        if status != Submission.Status.DRAFT:
            sub.submitted_at = now
        if status in (Submission.Status.VERIFIED, Submission.Status.RETURNED):
            sub.verified_by, sub.verified_at = verifier, now
            if status == Submission.Status.RETURNED:
                sub.review_comment = "Please attach the award letter / evidence and correct the amount."
        sub.save()
        slot = lead_slot(c)
        if slot:
            sub.contributors.create(role=slot["role"], person=person, order=0)
        co = next((p for p in c["people"] if not p["lead"]), None)
        if co and rng.random() < 0.4:
            colleague = Person.objects.filter(department__faculty=person.department.faculty, is_faculty=True) \
                .exclude(pk=person.pk).order_by("?").first()
            if colleague:
                sub.contributors.create(role=co["role"], person=colleague, order=1)
        sub.sync_departments()
        if rng.random() < 0.7 and any(f["type"] == "file" for f in c["fields"]):
            pdf = make_pdf([c["title"], sub.title, person.full_name, cycle.label])
            ev = EvidenceFile(submission=sub, field="evidence", original_name=f"evidence-{sub.pk}.pdf",
                              size=len(pdf), content_type="application/pdf", uploaded_by=by)
            ev.file.save(f"evidence-{sub.pk}.pdf", ContentFile(pdf), save=True)
        ReviewEvent.objects.create(submission=sub, actor=by, action=ReviewEvent.Action.CREATE, to_status="draft")
        if status != Submission.Status.DRAFT:
            ReviewEvent.objects.create(submission=sub, actor=by, action=ReviewEvent.Action.SUBMIT,
                                       from_status="draft", to_status="submitted")
        if status in (Submission.Status.VERIFIED, Submission.Status.RETURNED):
            ReviewEvent.objects.create(submission=sub, actor=verifier,
                                       action="verify" if status == "verified" else "return",
                                       from_status="submitted", to_status=status, comment=sub.review_comment)
        return sub
