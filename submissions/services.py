"""Submission write paths: create / update, workflow transitions, stage advance.

The only place statuses change and the only place typed columns are derived.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from audit.models import ActivityAction
from audit.services import record_activity
from notifications.services import notify
from org.models import Organization, ReportingCycle
from oric_backend.errors import CycleClosedError, InsufficientPermissionError
from people.models import Person

from .models import Contributor, EvidenceFile, ReviewEvent, Submission
from .registry import CATEGORY_BY_KEY, lead_slot
from .validation import validate_data, validate_people

S = Submission.Status
A = ReviewEvent.Action

# action -> (allowed from-statuses, to-status, capability or None for the author)
TRANSITIONS = {
    A.SUBMIT: ((S.DRAFT, S.RETURNED), S.SUBMITTED, None),
    A.VERIFY: ((S.DRAFT, S.SUBMITTED, S.RETURNED), S.VERIFIED, "submission.verify"),
    A.RETURN: ((S.SUBMITTED, S.VERIFIED), S.RETURNED, "submission.verify"),
    A.REJECT: ((S.SUBMITTED,), S.REJECTED, "submission.verify"),
    A.REOPEN: ((S.VERIFIED, S.REJECTED), S.SUBMITTED, "submission.verify"),
}
COMMENT_REQUIRED = {A.RETURN, A.REJECT}


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------
def resolve_organization(name: str | None) -> Organization | None:
    name = " ".join((name or "").split())
    if not name or name.lower() in {"na", "n/a", "nil", "none", "-"}:
        return None
    org = Organization.objects.filter(name__iexact=name[:255]).first()
    if org:
        return org
    for o in Organization.objects.exclude(aliases=[]).only("id", "aliases"):
        if any(a.lower() == name.lower() for a in o.aliases):
            return o
    return Organization.objects.create(name=name[:255])


def _first_org_value(category: dict, data: dict) -> str | None:
    for f in category["fields"]:
        if f["type"] == "org" and data.get(f["name"]):
            return data[f["name"]]
    return None


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------
def default_cycle(event_date=None) -> ReportingCycle | None:
    return ReportingCycle.for_date(event_date) or ReportingCycle.current()


@transaction.atomic
def save_submission(user, *, instance: Submission | None = None, category: str, data: dict, people: list[dict],
                    owner: Person | None = None, cycle: ReportingCycle | None = None, uploads: dict | None = None,
                    draft: bool = True, source: str = Submission.Source.PORTAL, enforce_cycle: bool = True,
                    validate: bool = True) -> Submission:
    """Validate and persist one submission with its contributors and files.

    ``people`` carries every contributor, including the lead (owner). When the lead
    slot is absent, ``owner`` (or the acting user's own person) becomes the lead.
    """
    c = CATEGORY_BY_KEY.get(category)
    if not c:
        raise ValidationError({"category": "Unknown category."})
    uploads = uploads or {}
    existing_files = set(instance.files.values_list("field", flat=True)) if instance else set()
    if validate:
        data = validate_data(category, data, existing_files=existing_files, incoming_files=set(uploads), draft=draft)
        people = validate_people(category, people, draft=draft)

    slot = lead_slot(c)
    lead = next((p for p in people if slot and p["role"] == slot["role"]), None)
    if lead and lead.get("person_id"):
        owner = Person.objects.select_related("department").get(pk=lead["person_id"])
    elif owner is None and not c["oric_only"] and not (lead and lead.get("name")):
        owner = getattr(user, "person", None) if user and user.is_authenticated else None
    if slot and owner and not lead:
        people = [{"role": slot["role"], "person_id": owner.pk, "name": "", "designation": "", "affiliation": ""},
                  *people]

    sub = instance or Submission(category=category, submitted_by=user if user and user.is_authenticated else None,
                                 source=source)
    if instance is not None and instance.category != category:
        raise ValidationError({"category": "The category of a submission cannot change."})
    sub.data = data
    sub.owner = owner
    sub.department = owner.department if owner else None
    sub.faculty = owner.department.faculty if owner and owner.department_id else None
    sub.promote()
    if cycle is None:
        cycle = sub.cycle if sub.cycle_id else default_cycle(sub.event_date)
    if cycle is None:
        raise ValidationError({"cycle": "No fiscal year is configured."})
    sub.cycle = cycle
    if enforce_cycle and not cycle.accepts_submissions and not _is_staff(user, sub):
        raise CycleClosedError()
    org_name = _first_org_value(c, data)
    sub.organization = resolve_organization(org_name) if org_name else None
    created = sub.pk is None
    sub.save()

    sub.contributors.all().delete()
    Contributor.objects.bulk_create([
        Contributor(submission=sub, role=p["role"], person_id=p.get("person_id"), name=p.get("name", ""),
                    designation=p.get("designation", ""), affiliation=p.get("affiliation", ""), order=i)
        for i, p in enumerate(people)
    ])
    for field, upload in uploads.items():
        EvidenceFile.objects.filter(submission=sub, field=field).delete()
        EvidenceFile.objects.create(submission=sub, field=field, file=upload, original_name=upload.name[:255],
                                    size=upload.size, content_type=getattr(upload, "content_type", "") or "",
                                    uploaded_by=user if user and user.is_authenticated else None)
    sub.sync_departments()
    if created and source == Submission.Source.PORTAL:
        ReviewEvent.objects.create(submission=sub, actor=user, action=A.CREATE, to_status=sub.status)
    return sub


def _is_staff(user, sub) -> bool:
    from .access import can_staff

    return bool(user and user.is_authenticated) and (user.is_superuser or can_staff(user, "submission.change", sub))


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
def allowed_actions(user, submission) -> list[str]:
    from .access import _is_author, can_staff

    out = []
    for action, (from_statuses, _to, perm) in TRANSITIONS.items():
        if submission.status not in from_statuses:
            continue
        if perm is None:
            # submitting is the author's call (owner or whoever entered it); ORIC staff may still
            # submit their own entries after the deadline, but never someone else's returned record
            staff = can_staff(user, "submission.change", submission)
            if _is_author(user, submission) and (submission.cycle.accepts_submissions or staff):
                out.append(action)
        elif can_staff(user, perm, submission):
            out.append(action)
    return out


@transaction.atomic
def transition(user, submission: Submission, action: str, comment: str = "") -> Submission:
    comment = (comment or "").strip()
    if action not in TRANSITIONS:
        raise ValidationError({"action": "Unknown action."})
    if action not in allowed_actions(user, submission):
        if action == A.SUBMIT and not submission.cycle.accepts_submissions:
            raise CycleClosedError()
        raise InsufficientPermissionError(
            required_permission=TRANSITIONS[action][2] or "submission.add",
            message=f"You can't {action} this submission while it is {submission.get_status_display().lower()}.",
        )
    if action in COMMENT_REQUIRED and not comment:
        raise ValidationError({"comment": "Please explain why."})
    if action in (A.SUBMIT, A.VERIFY):
        existing = set(submission.files.values_list("field", flat=True))
        validate_data(submission.category, submission.data, existing_files=existing)
        validate_people(submission.category,
                        [{"role": c.role, "person_id": c.person_id, "name": c.name}
                         for c in submission.contributors.all()])

    from_status = submission.status
    to_status = TRANSITIONS[action][1]
    now = timezone.now()
    submission.status = to_status
    if action == A.SUBMIT or (action == A.VERIFY and not submission.submitted_at):
        submission.submitted_at = now
    if action in (A.VERIFY, A.RETURN, A.REJECT):
        submission.verified_by = user
        submission.verified_at = now
        submission.review_comment = comment
    submission.save()
    ReviewEvent.objects.create(submission=submission, actor=user, action=action, from_status=from_status,
                               to_status=to_status, comment=comment)
    record_activity(ActivityAction.WORKFLOW, actor=user, target=submission,
                    description=f"{action}: {from_status} → {to_status}", metadata={"comment": comment})
    _notify(user, submission, action, comment)
    return submission


def _notify(user, sub: Submission, action: str, comment: str) -> None:
    link = f"/submissions/{sub.pk}"
    label = sub.category_def["short"]
    if action == A.SUBMIT:
        from rbac.utils import users_with_capability

        who = sub.owner.full_name if sub.owner_id else "ORIC"
        for reviewer in users_with_capability("submission.verify", global_only=True, pillar=sub.pillar,
                                              category=sub.category):
            if reviewer.pk != user.pk:
                notify(reviewer, "submission_submitted", f"{label} submitted by {who}", body=sub.title, link=link)
        return
    target = sub.owner.user if sub.owner_id and sub.owner.user_id else sub.submitted_by
    if target and target.pk != user.pk:
        notify(target, f"submission_{sub.status}", f"{label}: {sub.get_status_display()}",
               body=comment or sub.title, link=link)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@transaction.atomic
def advance(user, sub: Submission, next_category: str) -> Submission:
    """Start the next stage (e.g. proposal approved → project approved) as a prefilled draft."""
    c = sub.category_def
    if next_category not in c["next_stages"]:
        raise ValidationError({"category": "That is not a next stage of this submission."})
    if sub.status != Submission.Status.VERIFIED:
        raise ValidationError({"category": "ORIC has to verify this stage before the next one can be recorded."})
    nc = CATEGORY_BY_KEY[next_category]
    names = {f["name"] for f in nc["fields"] if f["type"] != "file"}
    data = {k: v for k, v in (sub.data or {}).items() if k in names}
    if next_category == "patent":
        data["filed_or_granted"] = "Granted"
        data.pop("filing_date", None)
    slots = {p["role"] for p in nc["people"]}
    people = [{"role": x.role, "person_id": x.person_id, "name": x.name, "designation": x.designation,
               "affiliation": x.affiliation} for x in sub.contributors.all() if x.role in slots]
    new = save_submission(user, category=next_category, data=data, people=people, owner=sub.owner,
                          cycle=ReportingCycle.current(), draft=True, validate=False)
    new.lineage = sub
    new.save(update_fields=["lineage"])
    return new
