from rest_framework.test import APITestCase

from oric_backend.testing import make_user, seed_world
from rbac.models import AccessRole, RoleAssignment
from rbac.utils import capability_scope_q, user_has_capability
from submissions.models import Submission


class CapabilityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ee, cls.cs, cls.cycle = seed_world()

    def _sub(self, owner, dept, pillar="RE"):
        return Submission.objects.create(pillar=pillar, cycle=self.cycle, owner=owner, department=dept,
                                         faculty_name=owner.full_name, faculty_email=owner.email, status="submitted")

    def test_faculty_has_only_foundation_and_add(self):
        f = make_user("f@x.test", role="faculty", department=self.ee)
        self.assertTrue(user_has_capability(f, "submission.add"))
        self.assertFalse(user_has_capability(f, "submission.view"))
        self.assertFalse(user_has_capability(f, "rbac.manage"))

    def test_director_lacks_rbac_manage_admin_has_it(self):
        d = make_user("d@x.test", role="oric_director")
        a = make_user("a@x.test", role="admin")
        self.assertFalse(user_has_capability(d, "rbac.manage"))
        self.assertTrue(user_has_capability(a, "rbac.manage"))

    def test_department_focal_sees_only_own_department(self):
        focal = make_user("focal@x.test", role="department_focal", department=self.ee, scoped_department=self.ee)
        fe = make_user("fe@x.test", role="faculty", department=self.ee)
        fc = make_user("fc@x.test", role="faculty", department=self.cs)
        mine, other = self._sub(fe, self.ee), self._sub(fc, self.cs)
        self.client.force_authenticate(focal)
        res = self.client.get("/api/v1/submissions/")
        ids = {r["id"] for r in res.json()["data"]["results"]}
        self.assertIn(mine.pk, ids)
        self.assertNotIn(other.pk, ids)
        self.assertEqual(self.client.get(f"/api/v1/submissions/{other.pk}/").status_code, 404)

    def test_pillar_restricted_manager(self):
        ipm = make_user("ip@x.test", role="ip_manager")
        f = make_user("f2@x.test", role="faculty", department=self.ee)
        re_, ic = self._sub(f, self.ee, "RE"), self._sub(f, self.ee, "IC")
        q = capability_scope_q(ipm, "submission.view", pillar_field="pillar")
        ids = set(Submission.objects.filter(q).values_list("pk", flat=True))
        self.assertEqual(ids, {ic.pk})
        self.client.force_authenticate(ipm)
        res = self.client.post(f"/api/v1/submissions/{re_.pk}/transition/", {"action": "approve"}, format="json")
        self.assertEqual(res.status_code, 404)  # not even visible
        res = self.client.post(f"/api/v1/submissions/{ic.pk}/transition/", {"action": "approve"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)

    def test_faculty_cannot_see_others_returns(self):
        a = make_user("a1@x.test", role="faculty", department=self.ee)
        b = make_user("b1@x.test", role="faculty", department=self.ee)
        sb = self._sub(b, self.ee)
        self.client.force_authenticate(a)
        self.assertEqual(self.client.get(f"/api/v1/submissions/{sb.pk}/").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/submissions/").json()["data"]["count"], 0)

    def test_denied_route_names_required_permission(self):
        f = make_user("f3@x.test", role="faculty", department=self.ee)
        self.client.force_authenticate(f)
        res = self.client.get("/api/v1/users/")
        self.assertEqual(res.status_code, 403)
        body = res.json()
        self.assertEqual(body["code"], "INSUFFICIENT_PERMISSION")
        self.assertEqual(body["details"]["required_permission"], "user.view")

    def test_abilities_payload_has_scoped_rules(self):
        focal = make_user("focal2@x.test", role="department_focal", department=self.ee, scoped_department=self.ee)
        self.client.force_authenticate(focal)
        data = self.client.get("/api/v1/me/abilities/").json()["data"]
        rule = next(r for r in data["rules"] if r["subject"] == "Submission" and r["action"] == "read")
        self.assertEqual(rule["conditions"]["department_id"]["$in"], [self.ee.pk])


class RbacAdminGuardTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ee, cls.cs, cls.cycle = seed_world()

    def test_cannot_grant_role_with_capabilities_you_lack(self):
        # director has role_assignment.add but not rbac.manage → cannot hand out the admin role
        d = make_user("dir@x.test", role="oric_director")
        target = make_user("t@x.test")
        self.client.force_authenticate(d)
        admin_role = AccessRole.objects.get(slug="admin")
        res = self.client.post("/api/v1/rbac/assignments/", {"user": target.pk, "role": admin_role.pk}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["code"], "PRIVILEGE_ESCALATION")
        ok = self.client.post("/api/v1/rbac/assignments/",
                              {"user": target.pk, "role": AccessRole.objects.get(slug="faculty").pk}, format="json")
        self.assertEqual(ok.status_code, 201, ok.content)

    def test_admin_cannot_lock_self_out(self):
        a = make_user("adm@x.test", role="admin")
        assignment = RoleAssignment.objects.get(user=a)
        self.client.force_authenticate(a)
        res = self.client.post(f"/api/v1/rbac/assignments/{assignment.pk}/deactivate/")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["code"], "SELF_LOCKOUT")

    def test_system_role_cannot_be_deleted(self):
        a = make_user("adm2@x.test", role="admin")
        self.client.force_authenticate(a)
        role = AccessRole.objects.get(slug="faculty")
        self.assertEqual(self.client.delete(f"/api/v1/rbac/roles/{role.pk}/").status_code, 409)
