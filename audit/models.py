from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class ActivityAction(models.TextChoices):
    LOGIN = "login", "Login"
    LOGOUT = "logout", "Logout"
    LOGIN_FAILED = "login_failed", "Login failed"
    PASSWORD_CHANGED = "password_changed", "Password changed"
    PASSWORD_RESET = "password_reset", "Password reset"
    EXPORT = "export", "Export"
    DOWNLOAD = "download", "Download"
    WORKFLOW = "workflow", "Workflow action"
    PERMISSION_DENIED = "permission_denied", "Permission denied"
    OTHER = "other", "Other"


class ActivityEvent(models.Model):
    """Append-only log of non-row events (logins, exports, downloads, workflow).

    Row diffs are django-auditlog's LogEntry; both carry the same request_id.
    """

    action = models.CharField(max_length=30, choices=ActivityAction.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actor_label = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=500, blank=True)
    target_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    target_id = models.CharField(max_length=64, blank=True)
    target = GenericForeignKey("target_type", "target_id")
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    path = models.CharField(max_length=500, blank=True)
    method = models.CharField(max_length=10, blank=True)
    remote_addr = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.action} {self.actor_label}"
