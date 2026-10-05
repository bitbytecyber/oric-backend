"""Who can see / edit / delete which returns.

Pattern from sis_backend's StaffOrSelfQuerysetMixin: everyone sees their OWN
rows; staff additionally see rows inside the department/pillar scope of the
capability (``submission.view`` etc.).
"""
from django.db.models import Q

from rbac.utils import capability_scope_q, user_can_on, user_has_capability

from .models import Submission


def scope_q(user, key: str) -> Q | None:
    return capability_scope_q(user, key, department_field="department_id", pillar_field="pillar")


def visible_submissions(user, base=None):
    qs = base if base is not None else Submission.objects.all()
    if user.is_superuser:
        return qs
    q = scope_q(user, "submission.view")
    if q is None:
        return qs
    return qs.filter(Q(owner=user) | q)


def can_staff(user, key: str, sub: Submission) -> bool:
    return user_can_on(user, key, department_id=sub.department_id, pillar=sub.pillar)


def can_view(user, sub: Submission) -> bool:
    return sub.owner_id == user.id or can_staff(user, "submission.view", sub)


def can_edit(user, sub: Submission) -> bool:
    """Owner edits own draft/returned return while the cycle is open; staff with submission.change can
    correct anything not yet approved."""
    if sub.status == Submission.Status.APPROVED and not user.is_superuser:
        return False
    if sub.owner_id == user.id and sub.is_editable and sub.cycle.accepts_submissions:
        return user_has_capability(user, "submission.add")
    return can_staff(user, "submission.change", sub)


def can_delete(user, sub: Submission) -> bool:
    if sub.owner_id == user.id and sub.status == Submission.Status.DRAFT:
        return True
    return can_staff(user, "submission.delete", sub)
