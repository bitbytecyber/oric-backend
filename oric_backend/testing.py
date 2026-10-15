"""Shared test fixtures: two faculties, three departments, an open fiscal year, RBAC seeded."""
import datetime

from org.models import Department, Faculty, ReportingCycle
from people.services.profile import provision_user
from rbac.models import AccessRole, RoleAssignment
from rbac.services.seed import seed_roles, sync_capabilities


class World:
    pass


def seed_world():
    sync_capabilities()
    seed_roles()
    w = World()
    w.ece = Faculty.objects.create(code="ECE", name="Faculty of Electrical & Computer Engineering")
    w.cpl = Faculty.objects.create(code="CPL", name="Faculty of Civil & Petroleum Engineering")
    w.eed = Department.objects.create(name="Department of Electrical Engineering", code="EED", faculty=w.ece)
    w.csit = Department.objects.create(name="Department of Computer Science & IT", code="CSIT", faculty=w.ece)
    w.ced = Department.objects.create(name="Department of Civil Engineering", code="CED", faculty=w.cpl)
    today = datetime.date.today()
    w.cycle = ReportingCycle.objects.create(
        label="FY test", year=today.year, starts_on=today - datetime.timedelta(days=300),
        ends_on=today + datetime.timedelta(days=60), submission_deadline=today + datetime.timedelta(days=30),
        status=ReportingCycle.Status.OPEN, phd_faculty_count=100,
    )
    return w


def make_user(email, *, role=None, department=None, scoped_department=None, scoped_faculty=None, **extra):
    u = provision_user(email=email, password="x-Strong-Pass-1", full_name=f"Dr. {email.split('@')[0].title()}",
                       department=department, must_change_password=False, **extra)
    if role:
        RoleAssignment.objects.create(user=u, role=AccessRole.objects.get(slug=role), department=scoped_department,
                                      faculty=scoped_faculty)
    if role != "faculty" and department is not None:
        RoleAssignment.objects.get_or_create(user=u, role=AccessRole.objects.get(slug="faculty"), department=None,
                                             faculty=None, is_active=True)
    return u
