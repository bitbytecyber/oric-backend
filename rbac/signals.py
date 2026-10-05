from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cache import bump_rbac_version
from .models import AccessRole, Capability, RoleAssignment, RoleCapability


@receiver([post_save, post_delete], sender=Capability)
@receiver([post_save, post_delete], sender=AccessRole)
@receiver([post_save, post_delete], sender=RoleCapability)
@receiver([post_save, post_delete], sender=RoleAssignment)
def _rbac_changed(sender, **kwargs):
    bump_rbac_version()


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def _user_saved(sender, instance, update_fields=None, **kwargs):
    # is_superuser / is_active changes alter abilities; cheap to always bump on
    # admin edits, but skip the frequent last_login-only save on sign-in.
    if update_fields and set(update_fields) <= {"last_login"}:
        return
    bump_rbac_version()
