import json

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from oric_backend.testing import make_user, seed_world
from submissions.models import Submission

PDF = b"%PDF-1.4\n%%EOF\n"


class SubmissionFlowTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ee, cls.cs, cls.cycle = seed_world()

    def setUp(self):
        self.faculty = make_user("fac@x.test", role="faculty", department=self.ee)
        self.manager = make_user("mgr@x.test", role="oric_manager")
        self.client.force_authenticate(self.faculty)

    def _create(self, counts=None):
        res = self.client.post("/api/v1/submissions/", {"pillar": "RE", "counts": counts or {}}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        return res.json()["data"]

    def _entry(self, sub_id, data, section="A15", files=True):
        payload = {"submission": sub_id, "section": section, "data": json.dumps(data)}
        if files:
            payload["evidence"] = SimpleUploadedFile("proof.pdf", PDF, content_type="application/pdf")
        return self.client.post("/api/v1/entries/", payload, format="multipart")

    def test_duplicate_return_is_rejected(self):
        self._create()
        res = self.client.post("/api/v1/submissions/", {"pillar": "RE"}, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["code"], "DUPLICATE_SUBMISSION")

    def test_entry_validation_against_registry(self):
        sub = self._create({"liaison_with_asrb": 1})
        bad = self._entry(sub["id"], {"liaison_with": ""}, files=False)
        self.assertEqual(bad.status_code, 400)
        details = bad.json()["details"]
        self.assertIn("liaison_with", details)
        self.assertIn("evidence", details)
        wrong = self._entry(sub["id"], {"x": 1}, section="B1")
        self.assertEqual(wrong.status_code, 400)  # B1 belongs to IC
        ok = self._entry(sub["id"], {"liaison_with": "AS&RB", "execution_date": "2026-01-10"})
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(len(ok.json()["data"]["files"]), 1)

    def test_submit_requires_declared_entries_then_full_review(self):
        sub = self._create({"liaison_with_asrb": 2})
        self._entry(sub["id"], {"liaison_with": "AS&RB", "execution_date": "2026-01-10"})
        res = self.client.post(f"/api/v1/submissions/{sub['id']}/transition/", {"action": "submit"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("entries", res.json()["details"])
        self.client.patch(f"/api/v1/submissions/{sub['id']}/", {"counts": {"liaison_with_asrb": 1}}, format="json")
        res = self.client.post(f"/api/v1/submissions/{sub['id']}/transition/", {"action": "submit"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        # locked for the owner now
        res = self.client.patch(f"/api/v1/submissions/{sub['id']}/", {"designation": "x"}, format="json")
        self.assertEqual(res.status_code, 409)

        self.client.force_authenticate(self.manager)
        res = self.client.post(f"/api/v1/submissions/{sub['id']}/transition/", {"action": "return"}, format="json")
        self.assertEqual(res.status_code, 400)  # comment required
        res = self.client.post(f"/api/v1/submissions/{sub['id']}/transition/",
                               {"action": "return", "comment": "Attach MoU"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Submission.objects.get(pk=sub["id"]).status, "returned")
        self.assertTrue(self.faculty.notifications.filter(kind="submission_returned").exists())

        self.client.force_authenticate(self.faculty)
        self.assertEqual(self.client.post(f"/api/v1/submissions/{sub['id']}/transition/", {"action": "submit"},
                                          format="json").status_code, 200)
        self.client.force_authenticate(self.manager)
        res = self.client.post(f"/api/v1/submissions/{sub['id']}/transition/", {"action": "approve"}, format="json")
        self.assertEqual(res.json()["data"]["status"], "approved")

    def test_faculty_cannot_approve_own_return(self):
        sub = self._create()
        self.client.post(f"/api/v1/submissions/{sub['id']}/transition/", {"action": "submit"}, format="json")
        res = self.client.post(f"/api/v1/submissions/{sub['id']}/transition/", {"action": "approve"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_evidence_download_is_permission_checked(self):
        sub = self._create({"liaison_with_asrb": 1})
        e = self._entry(sub["id"], {"liaison_with": "AS&RB", "execution_date": "2026-01-10"}).json()["data"]
        file_id = e["files"][0]["id"]
        self.assertEqual(self.client.get(f"/api/v1/evidence/{file_id}/download/").status_code, 200)
        other = make_user("other@x.test", role="faculty", department=self.ee)
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(f"/api/v1/evidence/{file_id}/download/").status_code, 403)

    def test_rejects_non_pdf_evidence(self):
        sub = self._create({"liaison_with_asrb": 1})
        res = self.client.post("/api/v1/entries/", {
            "submission": sub["id"], "section": "A15",
            "data": json.dumps({"liaison_with": "x", "execution_date": "2026-01-10"}),
            "evidence": SimpleUploadedFile("x.exe", b"MZ", content_type="application/x-msdownload"),
        }, format="multipart")
        self.assertEqual(res.status_code, 400)
