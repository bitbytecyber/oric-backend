import datetime
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from oric_backend.testing import make_user, seed_world
from org.models import ReportingCycle
from scorecard.models import InstitutionEvidence, InstitutionProfile

PDF = b"%PDF-1.4 test"
BASE = "/api/v1/scorecard/profile"


def pdf(name="cv.pdf"):
    return SimpleUploadedFile(name, PDF, content_type="application/pdf")


def body(r):
    d = r.json()
    return d.get("data", d) if isinstance(d, dict) else d


class InstitutionEvidenceTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        ctx = override_settings(MEDIA_ROOT=self.media)
        ctx.enable()
        self.addCleanup(ctx.disable)

        self.w = seed_world()
        self.cycle = self.w.cycle
        self.director = make_user("director@neduet.edu.pk", role="oric_director")
        self.auditor = make_user("auditor@neduet.edu.pk", role="auditor")
        self.nobody = make_user("someone@neduet.edu.pk")
        self.client = APIClient()
        self.client.force_authenticate(self.director)
        self.profile = InstitutionProfile.objects.create(
            cycle=self.cycle, staff=[{"id": "s1", "position": "Director ORIC", "name": "Dr. A"},
                                     {"id": "s2", "position": "Manager", "name": "Dr. B"}])

    def upload(self, **data):
        data.setdefault("cycle", self.cycle.pk)
        return self.client.post(f"{BASE}/evidence/", data, format="multipart")

    # --- upload / list ---------------------------------------------------------------------------

    def test_upload_files_and_link_to_operations_item(self):
        r = self.upload(item_key="steering_committee", doc_type="minutes", file=[pdf("m1.pdf"), pdf("m2.pdf")],
                        url="https://example.edu/sc", label="SC 2025")
        self.assertEqual(r.status_code, 201, r.content)
        rows = body(r)
        self.assertEqual([x["kind"] for x in rows], ["file", "file", "link"])
        ev = InstitutionEvidence.objects.exclude(file="")
        self.assertEqual(ev.count(), 2)
        self.assertTrue(ev.first().file.name.startswith(f"institution/{self.cycle.year}/steering_committee/"))
        listed = body(self.client.get(f"{BASE}/evidence/?cycle={self.cycle.pk}"))
        self.assertEqual(len(listed), 3)
        self.assertEqual(listed[0]["original_name"], "m1.pdf")

    def test_staff_evidence_needs_known_row(self):
        self.assertEqual(self.upload(item_key="staff", doc_type="cv", file=pdf()).status_code, 400)
        self.assertEqual(self.upload(item_key="staff", staff_id="nope", doc_type="cv", file=pdf()).status_code, 400)
        self.assertEqual(self.upload(item_key="staff", staff_id="s1", doc_type="cv", file=pdf()).status_code, 201)

    def test_rejects_bad_type_size_and_empty(self):
        exe = SimpleUploadedFile("x.exe", b"MZ", content_type="application/x-msdownload")
        self.assertEqual(self.upload(item_key="head", file=exe).status_code, 400)
        big = SimpleUploadedFile("big.pdf", b"0" * (10 * 1024 * 1024 + 1), content_type="application/pdf")
        self.assertEqual(self.upload(item_key="head", file=big).status_code, 400)
        self.assertEqual(self.upload(item_key="head").status_code, 400)
        self.assertEqual(self.upload(item_key="bogus", url="https://x.org").status_code, 400)
        self.assertFalse(InstitutionEvidence.objects.exists())

    # --- permissions -----------------------------------------------------------------------------

    def test_view_only_user_can_list_and_download_but_not_change(self):
        ev = body(self.upload(item_key="head", file=pdf("n.pdf")))[0]
        self.client.force_authenticate(self.auditor)
        self.assertEqual(self.client.get(f"{BASE}/evidence/?cycle={self.cycle.pk}").status_code, 200)
        r = self.client.get(f"{BASE}/evidence/{ev['id']}/download/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), PDF)
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertEqual(self.upload(item_key="head", url="https://x.org").status_code, 403)
        self.assertEqual(self.client.delete(f"{BASE}/evidence/{ev['id']}/").status_code, 403)

    def test_no_capability_is_forbidden(self):
        ev = body(self.upload(item_key="head", file=pdf()))[0]
        self.client.force_authenticate(self.nobody)
        self.assertEqual(self.client.get(f"{BASE}/evidence/?cycle={self.cycle.pk}").status_code, 403)
        self.assertEqual(self.client.get(f"{BASE}/evidence/{ev['id']}/download/").status_code, 403)
        self.assertEqual(self.upload(item_key="head", url="https://x.org").status_code, 403)
        self.assertEqual(self.client.delete(f"{BASE}/evidence/{ev['id']}/").status_code, 403)

    def test_delete_removes_row_and_file(self):
        ev = body(self.upload(item_key="head", file=pdf()))[0]
        obj = InstitutionEvidence.objects.get(pk=ev["id"])
        storage, name = obj.file.storage, obj.file.name
        self.assertTrue(storage.exists(name))
        self.assertEqual(self.client.delete(f"{BASE}/evidence/{ev['id']}/").status_code, 204)
        self.assertFalse(InstitutionEvidence.objects.exists())
        self.assertFalse(storage.exists(name))

    def test_download_of_link_is_404(self):
        ev = body(self.upload(item_key="webpage", url="https://oric.neduet.edu.pk"))[0]
        self.assertEqual(self.client.get(f"{BASE}/evidence/{ev['id']}/download/").status_code, 404)

    # --- staff ids -------------------------------------------------------------------------------

    def test_patch_keeps_ids_mints_new_and_drops_orphan_evidence(self):
        self.upload(item_key="staff", staff_id="s2", doc_type="cv", file=pdf())
        r = self.client.patch(f"{BASE}/?cycle={self.cycle.pk}", {"staff": [
            {"id": "s1", "position": "Director ORIC", "name": "Dr. A (edited)"},
            {"position": "Support", "name": "Mr. C"},
        ]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        staff = InstitutionProfile.objects.get(pk=self.profile.pk).staff
        self.assertEqual(staff[0]["id"], "s1")
        self.assertTrue(staff[1]["id"] and staff[1]["id"] not in ("s1", "s2"))
        self.assertFalse(InstitutionEvidence.objects.filter(staff_id="s2").exists())

    def test_patch_without_ids_matches_existing_rows(self):
        r = self.client.patch(f"{BASE}/?cycle={self.cycle.pk}", {"staff": [
            {"position": "Manager", "name": "Dr. B"}, {"position": "Director ORIC", "name": "Dr. A"}]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([s["id"] for s in InstitutionProfile.objects.get(pk=self.profile.pk).staff], ["s2", "s1"])

    def test_get_backfills_missing_ids(self):
        InstitutionProfile.objects.filter(pk=self.profile.pk).update(staff=[{"position": "X", "name": "Y"}])
        staff = body(self.client.get(f"{BASE}/?cycle={self.cycle.pk}"))["staff"]
        self.assertTrue(staff[0]["id"])
        self.assertEqual(InstitutionProfile.objects.get(pk=self.profile.pk).staff[0]["id"], staff[0]["id"])

    # --- clone -----------------------------------------------------------------------------------

    def test_clone_copies_staff_cv_and_letter_only(self):
        self.upload(item_key="staff", staff_id="s1", doc_type="cv", file=pdf("cv.pdf"))
        self.upload(item_key="staff", staff_id="s1", doc_type="appointment_letter", url="https://x.org/letter")
        self.upload(item_key="staff", staff_id="s1", doc_type="other", file=pdf("misc.pdf"))
        self.upload(item_key="steering_committee", doc_type="minutes", file=pdf("min.pdf"))
        today = datetime.date.today()
        nxt = ReportingCycle.objects.create(label="FY next", year=self.cycle.year + 1, starts_on=today,
                                            ends_on=today + datetime.timedelta(days=365),
                                            submission_deadline=today + datetime.timedelta(days=300))
        InstitutionEvidence.objects.create(cycle=nxt, item_key="staff", staff_id="old", doc_type="cv",
                                           url="https://stale.example")
        r = self.client.post(f"{BASE}/clone/", {"from_cycle": self.cycle.pk, "to_cycle": nxt.pk}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        copied = InstitutionEvidence.objects.filter(cycle=nxt).order_by("doc_type")
        self.assertEqual([(e.item_key, e.staff_id, e.doc_type) for e in copied],
                         [("staff", "s1", "appointment_letter"), ("staff", "s1", "cv")])
        cv = copied.get(doc_type="cv")
        src_cv = InstitutionEvidence.objects.get(cycle=self.cycle, doc_type="cv")
        self.assertNotEqual(cv.file.name, src_cv.file.name)
        self.assertTrue(cv.file.name.startswith(f"institution/{nxt.year}/staff/"))
        with cv.file.open("rb") as fh:
            self.assertEqual(fh.read(), PDF)
        self.assertEqual(InstitutionEvidence.objects.filter(cycle=self.cycle).count(), 4)
