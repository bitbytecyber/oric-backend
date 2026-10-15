from rest_framework.test import APITestCase

from org.services.directory import sync_leadership_roles
from oric_backend.testing import make_user, seed_world
from rbac.utils import user_has_capability
from submissions.models import Contributor, Submission


class ScopeTests(APITestCase):
    """The visibility matrix: faculty own, Chair department, Dean faculty, managers categories, Director all."""

    @classmethod
    def setUpTestData(cls):
        cls.w = w = seed_world()
        cls.fe = make_user("fe@x.test", role="faculty", department=w.eed)
        cls.fc = make_user("fc@x.test", role="faculty", department=w.csit)
        cls.fv = make_user("fv@x.test", role="faculty", department=w.ced)
        cls.chair = make_user("chair@x.test", role="chairman", department=w.eed, scoped_department=w.eed)
        cls.dean = make_user("dean@x.test", role="dean", department=w.eed, scoped_faculty=w.ece)
        cls.ipm = make_user("ipm@x.test", role="ip_manager")
        cls.director = make_user("dir@x.test", role="oric_director")
        cls.s_eed = cls._sub(cls.fe, w.eed, "patent")
        cls.s_csit = cls._sub(cls.fc, w.csit, "publication")
        cls.s_ced = cls._sub(cls.fv, w.ced, "publication")

    @classmethod
    def _sub(cls, user, dept, category):
        s = Submission(category=category, cycle=cls.w.cycle, owner=user.person, submitted_by=user, department=dept,
                       faculty=dept.faculty, status="submitted", data={"publication_title": "t"})
        s.promote()
        s.save()
        s.sync_departments()
        return s

    def _ids(self, user):
        self.client.force_authenticate(user)
        return {r["id"] for r in self.client.get("/api/v1/submissions/?limit=100").json()["data"]["results"]}

    def test_faculty_sees_only_own(self):
        self.assertEqual(self._ids(self.fe), {self.s_eed.pk})
        self.assertFalse(user_has_capability(self.fe, "submission.view"))

    def test_chair_sees_department(self):
        self.assertEqual(self._ids(self.chair), {self.s_eed.pk})

    def test_dean_sees_whole_faculty_not_others(self):
        self.assertEqual(self._ids(self.dean), {self.s_eed.pk, self.s_csit.pk})

    def test_ip_manager_sees_ip_categories_everywhere(self):
        self.assertEqual(self._ids(self.ipm), {self.s_eed.pk})

    def test_director_sees_all(self):
        self.assertEqual(self._ids(self.director), {self.s_eed.pk, self.s_csit.pk, self.s_ced.pk})

    def test_co_pi_department_sees_it(self):
        Contributor.objects.create(submission=self.s_ced, role="co_author", person=self.fe.person)
        self.s_ced.sync_departments()
        self.assertIn(self.s_ced.pk, self._ids(self.chair))
        self.assertIn(self.s_ced.pk, self._ids(self.fe))

    def test_chair_can_submit_on_behalf_only_within_department(self):
        self.client.force_authenticate(self.chair)
        date = self.w.cycle.starts_on.isoformat()
        body = {"category": "asrb_liaison", "people": [{"role": "lead", "person_id": self.fe.person.pk}],
                "data": {"liaison_with": "x", "execution_date": date}}
        res = self.client.post("/api/v1/submissions/", body, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["data"]["owner"], self.fe.person.pk)
        self.assertTrue(res.json()["data"]["on_behalf"])
        body["people"] = [{"role": "lead", "person_id": self.fv.person.pk}]
        self.assertEqual(self.client.post("/api/v1/submissions/", body, format="json").status_code, 403)

    def test_drafts_are_private(self):
        self.s_csit.status = "draft"
        self.s_csit.save()
        self.assertNotIn(self.s_csit.pk, self._ids(self.dean))
        self.assertIn(self.s_csit.pk, self._ids(self.fc))

    def test_explore_root_follows_role(self):
        for user, level in ((self.director, "university"), (self.dean, "faculty"), (self.chair, "department")):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get("/api/v1/explore/").json()["data"]["level"], level)

    def test_leadership_sync_creates_and_removes_roles(self):
        self.w.csit.chair = self.fc.person
        self.w.csit.save()
        sync_leadership_roles()
        self.assertEqual(self._ids(self.fc), {self.s_csit.pk})
        self.client.force_authenticate(self.fc)
        self.assertEqual(self.client.get("/api/v1/explore/").json()["data"]["level"], "department")
        self.w.csit.chair = None
        self.w.csit.save()
        sync_leadership_roles()
        self.assertFalse(self.fc.role_assignments.filter(role__slug="chairman", is_active=True).exists())
