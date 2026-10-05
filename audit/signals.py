from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import ActivityAction
from .services import record_activity


@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    record_activity(ActivityAction.LOGIN, request=request, actor=user, description="Signed in")


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    if user is not None:
        record_activity(ActivityAction.LOGOUT, request=request, actor=user, description="Signed out")


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    email = (credentials or {}).get("email") or (credentials or {}).get("username") or ""
    record_activity(ActivityAction.LOGIN_FAILED, request=request, description=f"Failed sign-in for {email}"[:500],
                    metadata={"email": email})
