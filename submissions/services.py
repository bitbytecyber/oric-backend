"""Submission workflow: the only place statuses change."""
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from audit.models import ActivityAction
from audit.services import record_activity
from oric_backend.errors import CycleClosedError, InsufficientPermissionError

from notifications.services import notify
from .models import ReviewEvent, Submission

S = Submission.Status
A = ReviewEvent.Action

# action -> (allowed from-statuses, to-status, permission codename or None for owner-only)
TRANSITIONS = {
    A.SUBMIT: ((S.DRAFT, S.RETURNED), S.SUBMITTED, None),
    A.START_REVIEW: ((S.SUBMITTED,), S.UNDER_REVIEW, "submission.review"),
    A.RETURN: ((S.SUBMITTED, S.UNDER_REVIEW), S.RETURNED, "submission.review"),
    A.APPROVE: ((S.SUBMITTED, S.UNDER_REVIEW), S.APPROVED, "submission.approve"),
    A.REJECT: ((S.SUBMITTED, S.UNDER_REVIEW), S.REJECTED, "submission.approve"),
    A.REOPEN: ((S.APPROVED, S.REJECTED), S.RETURNED, "submission.approve"),
}
COMMENT_REQUIRED = {A.RETURN, A.REJECT, A.REOPEN}


def allowed_actions(user, submission) -> list[str]:
    from .access import can_staff

    out = []
    for action, (from_statuses, _to, perm) in TRANSITIONS.items():
        if submission.status not in from_statuses:
            continue
        if perm is None:
            if submission.owner_id == user.id and submission.cycle.accepts_submissions:
                out.append(action)
        elif can_staff(user, perm, submission):
            out.append(action)
    return out


@transaction.atomic
def transition(user, submission: Submission, action: str, comment: str = "") -> Submission:
    comment = comment or ""
    if action not in TRANSITIONS:
        raise ValidationError({"action": "Unknown action."})
    if action not in allowed_actions(user, submission):
        if action == A.SUBMIT and submission.owner_id == user.id and not submission.cycle.accepts_submissions:
            raise CycleClosedError()
        perm = TRANSITIONS[action][2] or "submission.add"
        raise InsufficientPermissionError(
            required_permission=perm,
            message=f"You can't {action.replace('_', ' ')} this return while it is {submission.get_status_display().lower()}.",
        )
    if action in COMMENT_REQUIRED and not comment.strip():
        raise ValidationError({"comment": "Please explain why."})
    if action == A.SUBMIT:
        missing = submission.missing_entries()
        if missing:
            raise ValidationError({
                "entries": [
                    f'{m["section"]} · {m["title"]}: {m["provided"]} of {m["declared"]} entries added'
                    for m in missing
                ]
            })

    from_status = submission.status
    to_status = TRANSITIONS[action][1]
    now = timezone.now()
    submission.status = to_status
    if action == A.SUBMIT:
        submission.submitted_at = now
    else:
        submission.reviewed_by = user
        submission.reviewed_at = now
        submission.review_comment = comment
    submission.save()
    ReviewEvent.objects.create(
        submission=submission, actor=user, action=action, from_status=from_status, to_status=to_status, comment=comment
    )

    record_activity(ActivityAction.WORKFLOW, actor=user, target=submission,
                    description=f"{action}: {from_status} → {to_status}", metadata={"comment": comment})

    link = f"/submissions/{submission.pk}"
    label = submission.get_pillar_display()
    if action == A.SUBMIT:
        from rbac.utils import users_with_capability

        for reviewer in users_with_capability("submission.review", department_id=submission.department_id,
                                              pillar=submission.pillar):
            if reviewer.pk != user.pk:
                notify(reviewer, "submission_submitted", f"New {label} return from {submission.faculty_name}", link=link)
    elif submission.owner_id != user.pk:
        notify(
            submission.owner,
            f"submission_{to_status}",
            f"Your {label} return is now: {submission.get_status_display()}",
            body=comment,
            link=link,
        )
    return submission
