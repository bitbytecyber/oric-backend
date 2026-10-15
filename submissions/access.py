"""Who can see / add / edit / delete / verify which submissions.

* Everyone sees what they own, what they are a contributor on and what they entered.
* Staff additionally see rows inside the scope of ``submission.view``:
  Chairman → any submission linked to their department (owner or NED contributor),
  Dean → any linked to a department of their faculty, ORIC managers → their
  pillars / categories everywhere, Director → everything.
"""
from django.db.models import Q

from rbac.utils import capability_scope_q, user_can_on, user_has_capability

from .models import Contributor, Submission
from .registry import CATEGORY_BY_KEY

SubmissionDepartment = Submission.departments.through


def _org_q(*, department_id=None, faculty_id=None) -> Q:
    links = SubmissionDepartment.objects.all()
    if department_id is not None:
        links = links.filter(department_id=department_id)
    elif faculty_id is not None:
        links = links.filter(department__faculty_id=faculty_id)
    return Q(pk__in=links.values("submission_id"))


def scope_q(user, key: str) -> Q | None:
    return capability_scope_q(user, key, pillar_field="pillar", category_field="category", org_q=_org_q)


def own_q(user) -> Q:
    contributed = Contributor.objects.filter(person__user=user).values("submission_id")
    return Q(owner__user=user) | Q(submitted_by=user) | Q(pk__in=contributed)


def visible_submissions(user, base=None):
    qs = base if base is not None else Submission.objects.all()
    if user.is_superuser:
        return qs
    q = scope_q(user, "submission.view")
    if q is None:
        return qs
    return qs.filter(own_q(user) | q)


def _dept_ids(sub: Submission) -> set[int]:
    ids = set(sub.departments.values_list("pk", flat=True))
    if sub.department_id:
        ids.add(sub.department_id)
    return ids


def can_staff(user, key: str, sub: Submission) -> bool:
    return user_can_on(user, key, department_ids=_dept_ids(sub), pillar=sub.pillar, category=sub.category)


def is_own(user, sub: Submission) -> bool:
    if sub.submitted_by_id == user.id:
        return True
    if sub.owner_id and sub.owner.user_id == user.id:
        return True
    return sub.contributors.filter(person__user=user).exists()


def can_view(user, sub: Submission) -> bool:
    return user.is_superuser or is_own(user, sub) or can_staff(user, "submission.view", sub)


def _is_author(user, sub: Submission) -> bool:
    return sub.submitted_by_id == user.id or (sub.owner_id is not None and sub.owner.user_id == user.id)


def can_edit(user, sub: Submission) -> bool:
    """Owner / the person who entered it edit while draft or returned and the year is open;
    staff with ``submission.change`` (ORIC) can correct anything in scope."""
    if can_staff(user, "submission.change", sub):
        return True
    return _is_author(user, sub) and sub.is_editable and sub.cycle.accepts_submissions


def can_delete(user, sub: Submission) -> bool:
    if _is_author(user, sub) and sub.status == Submission.Status.DRAFT:
        return True
    return can_staff(user, "submission.delete", sub)


def can_add(user, *, category: str, person=None) -> bool:
    """May ``user`` record a ``category`` submission owned by ``person`` (None = institution-level)?"""
    if user.is_superuser:
        return True
    c = CATEGORY_BY_KEY[category]
    if c["oric_only"]:
        return user_can_on(user, "submission.add_oric", pillar=c["pillar"], category=category)
    own_person = getattr(user, "person", None) if hasattr(user, "person") else None
    if person is None or (own_person is not None and person.pk == own_person.pk):
        return user_has_capability(user, "submission.add") or user_has_capability(user, "submission.add_on_behalf")
    dept_ids = {person.department_id} if person.department_id else set()
    return user_can_on(user, "submission.add_on_behalf", department_ids=dept_ids, pillar=c["pillar"],
                       category=category)


def proxy_people(user):
    """People ``user`` may submit on behalf of (for the person picker)."""
    from people.models import Person
    from rbac.utils import capability_scopes

    if user.is_superuser:
        return Person.objects.all()
    scopes = capability_scopes(user, "submission.add_on_behalf")
    if not scopes:
        return Person.objects.filter(user=user)
    if any(s.is_global for s in scopes):
        return Person.objects.all()
    q = Q(user=user)
    for s in scopes:
        if s.department_id:
            q |= Q(department_id=s.department_id)
        elif s.faculty_id:
            q |= Q(department__faculty_id=s.faculty_id)
    return Person.objects.filter(q)
