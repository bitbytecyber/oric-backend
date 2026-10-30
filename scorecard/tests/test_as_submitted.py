from django.test import TestCase
from rest_framework.test import APIClient

from imports.models import ImportBatch
from oric_backend.testing import make_user, seed_world

CARD = {"template": "index_2021", "reported_fy": "FY 2024-25", "total": {"self": 81, "max": 100, "hec": None},
        "sections": []}


class AsSubmittedViewTests(TestCase):
    def setUp(self):
        self.w = seed_world()
        self.client = APIClient()
        self.client.force_authenticate(make_user("director@neduet.edu.pk", role="oric_director"))

    def get(self):
        r = self.client.get(f"/api/v1/scorecard/as-submitted/?cycle={self.w.cycle.pk}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        return body.get("data", body)

    def batch(self, **stats):
        return ImportBatch.objects.create(kind="hec_workbook", cycle=self.w.cycle, original_name="hec.xlsx",
                                          status="applied", stats=stats)

    def test_no_import(self):
        d = self.get()
        self.assertIsNone(d["card"])
        self.assertIsNone(d["batch"])

    def test_latest_full_import_and_stale_header(self):
        full = self.batch(as_submitted=CARD)
        self.batch(as_submitted={**CARD, "total": {"self": 1}}, only=["B.xi"])  # a table-only re-run
        d = self.get()
        self.assertEqual(d["batch"], full.pk)
        self.assertEqual(d["card"]["total"]["self"], 81)
        self.assertTrue(d["reported_fy_mismatch"])  # "FY test" cycle, card says FY 2024-25

    def test_workbook_without_score_card(self):
        b = self.batch(as_submitted={})
        d = self.get()
        self.assertEqual(d["batch"], b.pk)
        self.assertIsNone(d["card"])

    def test_requires_capability(self):
        self.client.force_authenticate(make_user("someone@neduet.edu.pk"))
        r = self.client.get(f"/api/v1/scorecard/as-submitted/?cycle={self.w.cycle.pk}")
        self.assertEqual(r.status_code, 403)
