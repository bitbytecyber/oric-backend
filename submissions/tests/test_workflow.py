from rest_framework.test import APITestCase

from oric_backend.testing import make_user, seed_world
from submissions.models import Submission

ASRB = {"liaison_with": "AS&RB annual report", "execution_date": None}


class SubmissionFlowTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.w = seed_world()

    def setUp(self):
        self.faculty = make_user("fac@x.test", role="faculty", department=self.w.eed)
        self.manager = make_user("mgr@x.test", role="oric_manager")
        self.client.force_authenticate(self.faculty)

    def _payload(self, **over):
        date = self.w.cycle.starts_on.isoformat()
        return {"category": "asrb_liaison", "data": {"liaison_with": "AS&RB annual report", "execution_date": date,
                                                     "evidence_link": "https://drive.example/x"}, **over}

    def test_create_draft_then_submit_and_verify(self):
        res = self.client.post("/api/v1/submissions/", self._payload(), format="json")
        self.assertEqual(res.status_code, 201, res.content)
        sub = res.json()["data"]
        self.assertEqual(sub["status"], "draft")
        self.assertEqual(sub["owner_name"], self.faculty.person.full_name)
        self.assertEqual(sub["department_code"], "EED")
        res = self.client.post(f"/api/v1/submissions/{sub['id']}/transition/", {"action": "submit"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.client.force_authenticate(self.manager)
        res = self.client.post(f"/api/v1/submissions/{sub['id']}/transition/", {"action": "verify"}, format="json")
        self.assertEqual(res.json()["data"]["status"], "verified")

    def test_required_fields_enforced_on_submit_not_on_draft(self):
        res = self.client.post("/api/v1/submissions/", {"category": "asrb_liaison", "data": {}}, format="json")
        self.assertEqual(res.status_code, 201)
        res = self.client.post("/api/v1/submissions/", {"category": "asrb_liaison", "data": {}, "submit": True},
                               format="json")
        self.assertEqual(res.status_code, 400)

    def test_faculty_cannot_verify_and_return_needs_comment(self):
        sub = self.client.post("/api/v1/submissions/", self._payload(submit=True), format="json").json()["data"]
        self.assertEqual(self.client.post(f"/api/v1/submissions/{sub['id']}/transition/", {"action": "verify"},
                                          format="json").status_code, 403)
        self.client.force_authenticate(self.manager)
        res = self.client.post(f"/api/v1/submissions/{sub['id']}/transition/", {"action": "return"}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.client.post(f"/api/v1/submissions/{sub['id']}/transition/", {"action": "return", "comment": "fix"},
                               format="json")
        self.assertEqual(Submission.objects.get(pk=sub["id"]).status, "returned")

    def test_amount_promoted_to_rupees_and_lineage_advance(self):
        date = self.w.cycle.starts_on.isoformat()
        payload = {"category": "grant_nonhec_submitted", "data": {
            "research_grant_name": "PSF", "proposal_submission_date": date, "national_or_international": "National",
            "thematic_area": "Physics", "research_proposal_title": "Solar", "total_funding_requested": "2.5",
            "status": "Pending", "evidence_link": "https://x.example"}}
        sub = self.client.post("/api/v1/submissions/", payload, format="json").json()["data"]
        self.assertEqual(float(sub["amount_pkr"]), 2_500_000)
        self.assertEqual(sub["funding_source"], "NON_HEC")
        url = f"/api/v1/submissions/{sub['id']}/advance/"
        # an unverified stage can't advance
        res = self.client.post(url, {"category": "grant_nonhec_approved"}, format="json")
        self.assertEqual(res.status_code, 400, res.content)
        Submission.objects.filter(pk=sub["id"]).update(status="verified")
        res = self.client.post(url, {"category": "grant_nonhec_approved"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        nxt = res.json()["data"]
        self.assertEqual(nxt["lineage"], sub["id"])
        self.assertEqual(nxt["data"]["research_proposal_title"], "Solar")
        self.assertEqual(len(nxt["lineage_chain"]), 2)

    def test_oric_only_category_refused_for_faculty(self):
        res = self.client.post("/api/v1/submissions/", {"category": "grant_opportunity", "data": {}}, format="json")
        self.assertEqual(res.status_code, 403)
