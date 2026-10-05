from allauth.account.signals import password_changed, password_reset, password_set
from django.dispatch import receiver

from audit.models import ActivityAction
from audit.services import record_activity


def _clear_forced_change(user):
    if getattr(user, "must_change_password", False):
        user.must_change_password = False
        user.save(update_fields=["must_change_password", "updated_at"])


@receiver(password_changed)
def _on_password_changed(sender, request, user, **kwargs):
    _clear_forced_change(user)
    record_activity(ActivityAction.PASSWORD_CHANGED, request=request, actor=user, description="Changed own password")


@receiver(password_set)
def _on_password_set(sender, request, user, **kwargs):
    _clear_forced_change(user)


@receiver(password_reset)
def _on_password_reset(sender, request, user, **kwargs):
    _clear_forced_change(user)
    record_activity(ActivityAction.PASSWORD_RESET, request=request, actor=user, description="Password reset by email")
