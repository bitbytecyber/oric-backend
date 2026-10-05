"""Seed reference data, and optionally a realistic demo world.

    python manage.py seed_oric                         # departments, cycles, ORIC team, RBAC
    python manage.py seed_oric --demo                  # + role accounts, faculty in every department, returns
    python manage.py seed_oric --demo --faculty-per-dept 6 --years 3
    python manage.py seed_oric --reset-demo --demo     # wipe demo accounts/returns (*.oric.test) and rebuild

Idempotent: reference data uses update_or_create; demo people are keyed by email and
returns by (pillar, cycle, owner), so re-running only fills gaps.
"""
import datetime
import os
import random

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from notifications.models import Notification
from org.models import ContactMessage, Department, ReportingCycle
from org.services.demo_data import make_pdf, make_person, make_project, value_for
from org.services.seed import seed_cycles, seed_departments, seed_team
from people.models import User
from people.services.profile import provision_user
from rbac.models import AccessRole, RoleAssignment
from rbac.services.seed import seed_roles, sync_capabilities
from submissions.models import EvidenceFile, ReviewEvent, SectionEntry, Submission
from submissions.registry import PILLARS, section_count_fields

DEMO_DOMAIN = "oric.test"  # every demo account ends with this; reserved TLD, never delivers mail

# Named role accounts (documented in seed_readme.md).
ROLE_ACCOUNTS = [
    # email, name, designation, dept code, role, scope the role to that department?
    ("admin@oric.test", "Portal Administrator", "IT Manager, ORIC", None, "admin", False),
    ("director@oric.test", "Dr. Riaz Uddin", "Director ORIC", "EE", "oric_director", False),
    ("manager@oric.test", "Mr. Imran Ahmed", "Assistant Manager ORIC", None, "oric_manager", False),
    ("research.manager@oric.test", "Dr. Muhammad Uzair", "Manager — Research Operations & Development", "ME",
     "research_ops_manager", False),
    ("ip.manager@oric.test", "Dr. Ashar Ahmed", "Manager — Intellectual Property", "ME", "ip_manager", False),
    ("techtransfer@oric.test", "Dr. Saeeda Nadir Ali", "Manager — Tech Transfer & University-Industry Linkage",
     "CY", "tech_transfer_manager", False),
    ("incubation@oric.test", "Dr. Sundus Ali", "Manager — Business Incubation", "CSIT", "incubation_manager", False),
    ("auditor@oric.test", "Ms. Hina Siddiqui", "Internal Auditor", None, "auditor", False),
    ("focal.ee@oric.test", "Dr. Ayesha Khan", "Associate Professor", "EE", "department_focal", True),
    ("faculty.ee@oric.test", "Dr. Kamran Ali", "Assistant Professor", "EE", "faculty", False),
    ("faculty.cs@oric.test", "Dr. Sana Javed", "Associate Professor", "CSIT", "faculty", False),
    ("faculty.me@oric.test", "Engr. Bilal Ahmed", "Lecturer", "ME", "faculty", False),
    ("faculty.ch@oric.test", "Dr. Faraz Hussain", "Professor", "CH", "faculty", False),
]

# Which sub-forms a typical return touches, weighted by how common the activity is.
SECTION_WEIGHTS = {
    "A1": 9, "A2": 8, "A3": 4, "A4": 3, "A5": 3, "A6": 2, "A7": 3, "A8": 2, "A9": 1, "A10": 2, "A11": 2, "A12": 4,
    "A13": 2, "A14": 2, "A15": 1,
    "B1": 4, "B2": 3, "B3": 1, "B4": 1, "B5": 3, "B6": 2, "B7": 3, "B8": 3, "B9": 3, "B10": 3, "B11": 4, "B12": 2,
    "B13": 9,
    "C1": 5, "C2": 2, "C3": 3, "C4": 4,
}
PILLAR_PROBABILITY = {"RE": 0.8, "IC": 0.5, "SCB": 0.22}


class Command(BaseCommand):
    help = "Seed departments, reporting cycles, ORIC team and RBAC; --demo adds people and filed returns."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true", help="Create demo people and returns.")
        parser.add_argument("--faculty-per-dept", type=int, default=4, help="Generated faculty per department.")
        parser.add_argument("--years", type=int, default=3, help="Reporting years of returns to generate (max 3).")
        parser.add_argument("--seed", type=int, default=2026, help="Random seed (same seed → same demo world).")
        parser.add_argument("--reset-demo", action="store_true",
                            help=f"Delete every *@*.{DEMO_DOMAIN} / *@{DEMO_DOMAIN} account and its returns first.")
        parser.add_argument("--superuser-email", default=os.environ.get("ORIC_SUPERUSER_EMAIL", ""))
        parser.add_argument("--superuser-password", default=os.environ.get("ORIC_SUPERUSER_PASSWORD", ""))

    def handle(self, *args, **o):
        with transaction.atomic():
            if o["reset_demo"]:
                self._reset_demo()
            n = seed_departments()
            seed_cycles()
            seed_team()
            sync_capabilities()
            seed_roles(reconcile=True)
            self.stdout.write(self.style.SUCCESS(f"Reference data: {n} departments, reporting cycles, ORIC team, RBAC."))
            if o["superuser_email"] and o["superuser_password"]:
                provision_user(email=o["superuser_email"], full_name="System Administrator",
                               password=o["superuser_password"], is_staff=True, is_superuser=True,
                               must_change_password=False)
                self.stdout.write(f"Superuser ready: {o['superuser_email']}")
        if o["demo"]:
            self._demo(o)

    # ------------------------------------------------------------------------------------------
    def _reset_demo(self):
        demo = User.objects.filter(email__iendswith=DEMO_DOMAIN)
        subs = Submission.objects.filter(owner__in=demo)
        for ev in EvidenceFile.objects.filter(entry__submission__in=subs):
            ev.file.delete(save=False)
        counts = (subs.count(), demo.count())
        subs.delete()
        demo.delete()
        ContactMessage.objects.filter(email__iendswith=DEMO_DOMAIN).delete()
        self.stdout.write(self.style.WARNING(f"Removed {counts[0]} demo returns and {counts[1]} demo accounts."))

    def _demo(self, o):
        rng = random.Random(o["seed"])
        password = os.environ.get("ORIC_DEMO_PASSWORD", "OricDemo#2026")
        depts = {d.code: d for d in Department.objects.all()}

        with transaction.atomic():
            people = self._role_accounts(depts, password)
            faculty = self._faculty(rng, depts, password, o["faculty_per_dept"])
        self.stdout.write(self.style.SUCCESS(
            f"People: {len(people)} role accounts + {len(faculty)} faculty across {len(depts)} departments."
        ))

        cycles = list(ReportingCycle.objects.order_by("-year")[: max(1, min(3, o["years"]))])
        reviewers = {
            "RE": [people["research.manager@oric.test"], people["manager@oric.test"]],
            "IC": [people["ip.manager@oric.test"], people["techtransfer@oric.test"]],
            "SCB": [people["incubation@oric.test"], people["manager@oric.test"]],
        }
        filers = faculty + [people[e] for e, *_ in ROLE_ACCOUNTS if e.startswith(("faculty.", "director", "focal"))]
        made = entries = files = 0
        for cycle in cycles:
            with transaction.atomic():
                for user in filers:
                    for p in PILLARS:
                        # One RNG per (person, year, pillar): re-running makes the same decisions,
                        # so existing returns are skipped and nothing new is invented.
                        krng = random.Random(f"{o['seed']}:{user.email}:{cycle.year}:{p['key']}")
                        if krng.random() > PILLAR_PROBABILITY[p["key"]]:
                            continue
                        r = self._return(krng, user, p, cycle, reviewers[p["key"]])
                        if r:
                            made += 1
                            entries += r[0]
                            files += r[1]
            self.stdout.write(f"  {cycle.label}: returns so far {made}")
        self._named_scenarios(people)
        self._inbox(rng)
        self.stdout.write(self.style.SUCCESS(
            f"Returns: {made} filed with {entries} entries and {files} evidence PDFs over {len(cycles)} years. "
            f"Demo password: see seed_readme.md (ORIC_DEMO_PASSWORD)."
        ))

    def _role_accounts(self, depts, password):
        out = {}
        for email, name, desig, code, role_slug, scoped in ROLE_ACCOUNTS:
            dept = depts.get(code) if code else None
            u = provision_user(email=email, full_name=name, password=password, designation=desig, department=dept,
                               is_staff=role_slug == "admin", is_superuser=role_slug == "admin",
                               must_change_password=False)
            role = AccessRole.objects.get(slug=role_slug)
            RoleAssignment.objects.get_or_create(user=u, role=role, department=dept if scoped else None,
                                                 is_active=True)
            if dept is not None and role_slug != "faculty":  # staff with a department also file returns
                RoleAssignment.objects.get_or_create(user=u, role=AccessRole.objects.get(slug="faculty"),
                                                     department=None, is_active=True)
            out[email] = u
        return out

    def _faculty(self, rng, depts, password, per_dept):
        faculty_role = AccessRole.objects.get(slug="faculty")
        focal_role = AccessRole.objects.get(slug="department_focal")
        used: set[str] = set()
        users = []
        for code, dept in sorted(depts.items()):
            for i in range(per_dept):
                p = make_person(rng, used)
                u = provision_user(email=p["email"], full_name=p["full_name"], password=password,
                                   designation=p["designation"], department=dept, employee_id=p["employee_id"],
                                   phone=p["phone"], must_change_password=False)
                RoleAssignment.objects.get_or_create(user=u, role=faculty_role, department=None, is_active=True)
                # The first person of every department is its ORIC focal person (department-scoped).
                if i == 0 and code != "EE":  # EE's focal is the named focal.ee account
                    RoleAssignment.objects.get_or_create(user=u, role=focal_role, department=dept, is_active=True)
                users.append(u)
        return users

    def _return(self, rng, user, pillar, cycle, reviewers):
        if Submission.objects.filter(pillar=pillar["key"], cycle=cycle, owner=user).exists():
            return None
        open_cycle = cycle.status == ReportingCycle.Status.OPEN
        if open_cycle:
            status = rng.choices(["draft", "submitted", "under_review", "returned", "approved", "rejected"],
                                 [22, 20, 14, 10, 31, 3])[0]
        else:
            status = rng.choices(["approved", "rejected", "returned"], [90, 6, 4])[0]

        k = rng.randint(2, 5)
        sec_pool = pillar["sections"]
        chosen = []
        while len(chosen) < min(k, len(sec_pool)):
            s = rng.choices(sec_pool, [SECTION_WEIGHTS.get(x["key"], 1) for x in sec_pool])[0]
            if s not in chosen:
                chosen.append(s)
        counts = {f["name"]: 0 for f in pillar["counts"]}
        plan = {}
        for s in chosen:
            n = rng.choices([1, 2, 3], [6, 3, 1])[0]
            plan[s["key"]] = n
            if s["key"] == "B2":
                counts["patents_filed"] += n
            else:
                counts[section_count_fields(s)[0]] += n
        for c in pillar["counts"]:  # figures without sub-forms (jobs, placements, participation)
            if not any(c["name"] in section_count_fields(s) for s in pillar["sections"]):
                counts[c["name"]] = rng.choice([0, 0, 1, 2, 3, 5, 8])

        p = getattr(user, "person", None)
        sub = Submission.objects.create(
            pillar=pillar["key"], cycle=cycle, owner=user, department=p.department if p else None,
            faculty_name=user.full_name, faculty_email=user.email, designation=user.designation, counts=counts,
        )
        project = make_project(rng)
        n_entries = n_files = 0
        incomplete_draft = status == "draft" and rng.random() < 0.6
        for s in chosen:
            want = plan[s["key"]]
            have = want - 1 if incomplete_draft and want and s is chosen[0] else want  # drafts show hollow dots
            for i in range(have):
                ctx = {"user": user, "department": sub.department.name if sub.department else "", "year": cycle.year,
                       "project": project if i == 0 else make_project(rng), "i": i}
                data = {f["name"]: value_for(f, s["key"], ctx, rng) for f in s["fields"] if f["type"] != "file"}
                if data.get("start_date") and "end_date" in data:
                    start = datetime.date.fromisoformat(data["start_date"])
                    data["end_date"] = (start + datetime.timedelta(days=rng.choice([365, 540, 730]))).isoformat()
                if s["key"] == "B2":
                    data["filed_or_granted"] = "Filed"
                    data["granting_authority"] = ""
                data = {k: v for k, v in data.items() if v not in (None,)}
                entry = SectionEntry.objects.create(submission=sub, section=s["key"], data=data, created_by=user)
                n_entries += 1
                for f in s["fields"]:
                    if f["type"] != "file" or (not f["required"] and rng.random() < 0.7):
                        continue
                    title = next((str(data[x]) for x in ("research_proposal_title", "invention_title", "title",
                                                         "project_title", "startup_name", "event_title",
                                                         "publication_reference") if data.get(x)), s["title"])
                    pdf = make_pdf([
                        f"{f['label']} — {s['code']}",
                        f"Return: {pillar['name']} · {cycle.label}",
                        f"Faculty: {user.full_name}, {user.designation}",
                        f"Department: {ctx['department']}",
                        f"Activity: {title}",
                        f"Section: {s['title']}",
                        f"Date: {next((data[x] for x in data if x.endswith('date') and data[x]), '—')}",
                    ])
                    ev = EvidenceFile(entry=entry, field=f["name"], size=len(pdf), content_type="application/pdf",
                                      original_name=f"{s['key']}-{f['name']}-{user.email.split('@')[0]}.pdf",
                                      uploaded_by=user)
                    ev.file.save(f"{f['name']}.pdf", ContentFile(pdf), save=False)
                    ev.save()
                    n_files += 1

        self._apply_status(rng, sub, status, cycle, reviewers)
        return n_entries, n_files

    def _apply_status(self, rng, sub, status, cycle, reviewers):
        tz = timezone.get_current_timezone()
        window_start = datetime.datetime(cycle.year, 7, 10, 9, tzinfo=tz)
        now = timezone.now()
        window_end = min(now - datetime.timedelta(hours=6), datetime.datetime(cycle.year, 12, 10, 17, tzinfo=tz))
        span = max(1, int((window_end - window_start).total_seconds()))
        started = window_start + datetime.timedelta(seconds=rng.randint(0, span // 2))
        submitted = started + datetime.timedelta(days=rng.randint(1, 20), hours=rng.randint(0, 8))
        submitted = min(submitted, window_end)
        reviewer = rng.choice(reviewers)
        events = []
        if status != "draft":
            events.append(("submit", sub.owner, "draft", "submitted", "", submitted))
        cur, t = "submitted", submitted
        if status in ("under_review", "returned", "approved", "rejected"):
            t = min(t + datetime.timedelta(days=rng.randint(1, 6)), window_end)
            events.append(("start_review", reviewer, cur, "under_review", "", t))
            cur = "under_review"
        comments = {
            "returned": ["Please attach the signed MoU for the research link.",
                         "The evidence for the HEC grant is the cover letter only; attach the submission acknowledgement.",
                         "Funding figure differs from the award letter — please correct the amount."],
            "rejected": ["Activity falls outside this fiscal year.", "Duplicate of a return filed by your co-PI."],
            "approved": ["", "", "Well documented — thank you."],
        }
        if status in ("returned", "approved", "rejected"):
            t = min(t + datetime.timedelta(days=rng.randint(1, 10)), window_end)
            comment = rng.choice(comments[status])
            action = {"returned": "return", "approved": "approve", "rejected": "reject"}[status]
            events.append((action, reviewer, cur, status, comment, t))
            sub.reviewed_by, sub.reviewed_at, sub.review_comment = reviewer, t, comment
        for action, actor, frm, to, comment, at in events:
            ev = ReviewEvent.objects.create(submission=sub, actor=actor, action=action, from_status=frm, to_status=to,
                                            comment=comment)
            ReviewEvent.objects.filter(pk=ev.pk).update(created_at=at)
        sub.status = status
        sub.submitted_at = submitted if status != "draft" else None
        sub.save()
        last = events[-1][5] if events else started
        Submission.objects.filter(pk=sub.pk).update(created_at=started, updated_at=last)
        if cycle.status == ReportingCycle.Status.OPEN and status in ("returned", "approved", "rejected"):
            Notification.objects.create(
                user=sub.owner, kind=f"submission_{status}",
                title=f"Your {sub.get_pillar_display()} return is now: {sub.get_status_display()}",
                body=sub.review_comment, link=f"/returns/{sub.pk}",
            )

    def _named_scenarios(self, people):
        """Make sure the role accounts in seed_readme.md each have something to look at."""
        cycle = ReportingCycle.objects.filter(status=ReportingCycle.Status.OPEN).first()
        if not cycle:
            return
        rng = random.Random(7)
        want = [("faculty.ee@oric.test", "RE", "submitted"), ("faculty.ee@oric.test", "IC", "draft"),
                ("faculty.cs@oric.test", "RE", "approved"), ("faculty.cs@oric.test", "SCB", "under_review"),
                ("faculty.me@oric.test", "IC", "returned"), ("faculty.ch@oric.test", "RE", "draft")]
        reviewers = [people["manager@oric.test"]]
        for email, pk, status in want:
            u = people[email]
            if Submission.objects.filter(owner=u, cycle=cycle, pillar=pk).exists():
                continue
            pillar = next(p for p in PILLARS if p["key"] == pk)
            # temporarily force the status by retrying the generator's random status
            sub_rng = random.Random(rng.random())
            r = self._return(sub_rng, u, pillar, cycle, reviewers)
            if r:
                sub = Submission.objects.get(owner=u, cycle=cycle, pillar=pk)
                ReviewEvent.objects.filter(submission=sub).delete()
                self._apply_status(sub_rng, sub, status, cycle, reviewers)

    def _inbox(self, rng):
        if ContactMessage.objects.filter(email__iendswith=DEMO_DOMAIN).exists():
            return
        msgs = [
            ("Dr. Nadia Rizvi", "nadia.rizvi@faculty.oric.test", "Cannot find the joint project form",
             "Where do I report a joint proposal submitted with LUMS to the PSF? It is not an HEC grant."),
            ("Mr. Owais Memon", "owais.memon@faculty.oric.test", "Evidence file too large",
             "My award letter scan is 14 MB. Can ORIC accept it by email instead?"),
            ("Dr. Saad Qureshi", "saad.qureshi@faculty.oric.test", "Department focal person",
             "Who is the ORIC focal person for Textile Engineering this year?"),
        ]
        for name, email, subject, message in msgs:
            ContactMessage.objects.create(name=name, email=email, subject=subject, message=message,
                                          handled=rng.random() < 0.3)
