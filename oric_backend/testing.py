"""Shared test fixtures."""
import datetime

from org.models import Department, ReportingCycle
from people.services.profile import provision_user
from rbac.models import AccessRole, RoleAssignment
from rbac.services.seed import seed_roles, sync_capabilities


def seed_world():
    sync_capabilities()
    seed_roles()
    ee = Department.objects.create(name="Department of Electrical Engineering", code="EE")
    cs = Department.objects.create(name="Department of Computer Science & Information Technology", code="CSIT")
    today = datetime.date.today()
    cycle = ReportingCycle.objects.create(
        label="FY test", year=today.year, starts_on=today - datetime.timedelta(days=300),
        ends_on=today - datetime.timedelta(days=1), submission_deadline=today + datetime.timedelta(days=30),
        status=ReportingCycle.Status.OPEN,
    )
    return ee, cs, cycle


def make_user(email, *, role=None, department=None, scoped_department=None, **extra):
    u = provision_user(email=email, password="x-Strong-Pass-1", full_name=email.split("@")[0],
                       department=department, must_change_password=False, **extra)
    if role:
        RoleAssignment.objects.create(user=u, role=AccessRole.objects.get(slug=role), department=scoped_department)
    return u
