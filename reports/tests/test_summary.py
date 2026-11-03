import datetime
import io

from openpyxl import load_workbook
from rest_framework.test import APITestCase

from org.models import ReportingCycle
from oric_backend.testing import make_user, seed_world
from submissions.models import Contributor, Submission


class ActivitySummaryTests(APITestCase):
    """Multi-year activity report: numbers, role scoping, the xlsx_summary workbook."""

    @classmethod
    def setUpTestData(cls):
        cls.w = w = seed_world()
        start = w.cycle.starts_on
        cls.prev = ReportingCycle.objects.create(
            label="FY prev", year=w.cycle.year - 1, starts_on=start - datetime.timedelta(days=365),
            ends_on=start - datetime.timedelta(days=1), submission_deadline=start - datetime.timedelta(days=30),
            status=ReportingCycle.Status.CLOSED)
        cls.fe = make_user("fe@x.test", role="faculty", department=w.eed)
        cls.fe2 = make_user("fe2@x.test", role="faculty", department=w.eed)
        cls.fv = make_user("fv@x.test", role="faculty", department=w.ced)
        cls.chair = make_user("chair@x.test", role="chairman", department=w.eed, scoped_department=w.eed)
        cls.director = make_user("dir@x.test", role="oric_director")
        # fe: 2 grants (1 per FY) + 1 patent this FY + a draft and a rejected one that never count
        cls._sub(cls.fe, "grant_nonhec_approved", cls.prev, amount=1_000_000)
        cls._sub(cls.fe, "grant_nonhec_approved", w.cycle, amount=2_500_000)
        cls._sub(cls.fe, "patent", w.cycle)
        cls._sub(cls.fe, "patent", w.cycle, status="draft")
        cls._sub(cls.fe, "patent", w.cycle, status="rejected")
        # fe2 (same department) and fv (CED, fe is co-inventor) add to the department / person totals
        cls._sub(cls.fe2, "patent", cls.prev)
        s = cls._sub(cls.fv, "patent", w.cycle)
        Contributor.objects.create(submission=s, role="co_inventor", person=cls.fe.person)
        s.sync_departments()

    @classmethod
    def _sub(cls, user, category, cycle, *, amount=None, status="submitted"):
        dept = user.person.department
        s = Submission(category=category, cycle=cycle, owner=user.person, submitted_by=user, department=dept,
                       faculty=dept.faculty, status=status, data={})
        s.promote()
        s.amount_pkr = amount
        s.save()
        s.sync_departments()
        return s

    def _get(self, user, **params):
        self.client.force_authenticate(user)
        params.setdefault("cycle", f"{self.prev.pk},{self.w.cycle.pk}")
        return self.client.get("/api/v1/reports/summary/", params)

    @staticmethod
    def _grid(data):
        return {r["key"]: [c["count"] for c in r["cells"]] for r in data["categories"]}

    def test_person_summary_counts_amounts_and_totals(self):
        res = self._get(self.director, level="person", id=self.fe.person.pk)
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()["data"]
        self.assertEqual(data["subject"]["name"], self.fe.person.full_name)
        self.assertEqual([c["label"] for c in data["cycles"]], ["FY prev", "FY test"])
        self.assertEqual(data["range_label"], "FY prev – FY test")
        # drafts / rejected left out, co-inventor record included
        self.assertEqual(self._grid(data), {"grant_nonhec_approved": [1, 1], "patent": [0, 2]})
        grant = next(r for r in data["categories"] if r["key"] == "grant_nonhec_approved")
        self.assertEqual([c["amount_pkr"] for c in grant["cells"]], [1_000_000, 2_500_000])
        self.assertEqual(grant["total"], {"count": 2, "amount_pkr": 3_500_000})
        self.assertEqual([c["count"] for c in data["totals"]["cells"]], [1, 3])
        self.assertEqual(data["totals"]["total"]["count"], 4)
        self.assertEqual([p["key"] for p in data["pillars"]], ["RE", "IC"])

    def test_department_and_faculty_levels(self):
        dept = self._get(self.director, level="department", id=self.w.eed.pk).json()["data"]
        # fe's 3 + fe2's 1 + fv's patent (linked through fe as co-inventor)
        self.assertEqual(self._grid(dept), {"grant_nonhec_approved": [1, 1], "patent": [1, 2]})
        fac = self._get(self.director, level="faculty", id=self.w.cpl.pk).json()["data"]
        self.assertEqual(self._grid(fac), {"patent": [0, 1]})

    def test_single_cycle_range(self):
        data = self._get(self.director, level="person", id=self.fe.person.pk, cycle=self.w.cycle.pk).json()["data"]
        self.assertEqual(self._grid(data), {"grant_nonhec_approved": [1], "patent": [2]})

    def test_faculty_member_defaults_to_self_and_only_self(self):
        res = self._get(self.fe2)
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()["data"]
        self.assertEqual(data["subject"]["id"], self.fe2.person.pk)
        self.assertEqual(self._grid(data), {"patent": [1, 0]})
        self.assertEqual(self._get(self.fe2, level="person", id=self.fe.person.pk).status_code, 403)
        self.assertEqual(self._get(self.fe2, level="department", id=self.w.eed.pk).status_code, 403)

    def test_chair_sees_own_department_only(self):
        own = self._get(self.chair, level="department", id=self.w.eed.pk).json()["data"]
        self.assertEqual(self._grid(own), {"grant_nonhec_approved": [1, 1], "patent": [1, 2]})
        other = self._get(self.chair, level="department", id=self.w.ced.pk).json()["data"]
        # only the CED record EED is linked to (fe co-inventor) is visible to the EED chair
        self.assertEqual(self._grid(other), {"patent": [0, 1]})
        self.assertEqual(self._get(self.chair, level="faculty", id=self.w.cpl.pk).json()["data"]["totals"]["total"]
                         ["count"], 1)

    def test_bad_level_is_400(self):
        self.assertEqual(self._get(self.director, level="planet", id=1).status_code, 400)
        self.assertEqual(self._get(self.director, level="person", id=999999).status_code, 400)

    def _workbook(self, user, **params):
        self.client.force_authenticate(user)
        params = {"export_format": "xlsx_summary", "cycle": f"{self.prev.pk},{self.w.cycle.pk}", **params}
        res = self.client.get("/api/v1/reports/export/", params)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn("oric-activity-report", res["Content-Disposition"])
        return load_workbook(io.BytesIO(res.content))

    def test_xlsx_summary_workbook(self):
        wb = self._workbook(self.director, level="department", id=self.w.eed.pk)
        self.assertEqual(wb.sheetnames[0], "Summary")
        self.assertEqual(len(wb.sheetnames), 3)  # Summary + grant + patent
        ws = wb["Summary"]
        self.assertIn("Department of Electrical Engineering", ws["A1"].value)
        self.assertIn("FY prev – FY test", ws["A2"].value)
        rows = list(ws.iter_rows(min_row=4, values_only=True))
        self.assertEqual(rows[0][:5], ("Pillar", "Category", "HEC ref", "FY prev records", "FY prev amount (PKR)"))
        self.assertEqual(rows[-1][0], "Total")
        self.assertEqual(rows[-1][-2], 5)
        patent = wb[wb.sheetnames[2]]
        head = [c.value for c in patent[1]]
        self.assertEqual(head[1], "Fiscal year")
        self.assertEqual(sorted(r[1] for r in patent.iter_rows(min_row=2, values_only=True)),
                         ["FY prev", "FY test", "FY test"])

    def test_faculty_member_exports_own_report_with_mine(self):
        wb = self._workbook(self.fe, mine=1, level="person", id=self.fe.person.pk)
        self.assertEqual(wb["Summary"].iter_rows(min_row=4, values_only=True).__next__()[0], "Pillar")
        self.client.force_authenticate(self.fe)
        res = self.client.get("/api/v1/reports/export/", {"export_format": "xlsx_summary", "mine": 1,
                                                         "level": "department", "id": self.w.eed.pk})
        self.assertEqual(res.status_code, 403)
