from django.conf import settings
from django.db import models
from django.db.models import Q

from mixins import BaseModelMixin


class Capability(BaseModelMixin):
    """One row per catalog entry (rbac/capability_catalog.py). Synced, never hand-edited."""

    key = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    module = models.SlugField(max_length=40)
    resource = models.SlugField(max_length=40)
    action = models.SlugField(max_length=40)
    is_dangerous = models.BooleanField(default=False)

    class Meta:
        ordering = ["module", "resource", "action"]

    def __str__(self):
        return self.key


class AccessRole(BaseModelMixin):
    """A named bundle of capabilities. Separate from django.contrib.auth Group on purpose."""

    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False, help_text="Built-in role: cannot be renamed or deleted.")
    capabilities = models.ManyToManyField(Capability, through="RoleCapability", related_name="roles", blank=True)
    pillars = models.JSONField(
        default=list, blank=True,
        help_text='Row restriction: pillar keys this role applies to (e.g. ["IC"]). Empty = all pillars.',
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RoleCapability(BaseModelMixin):
    role = models.ForeignKey(AccessRole, on_delete=models.CASCADE, related_name="role_capabilities")
    capability = models.ForeignKey(Capability, on_delete=models.CASCADE, related_name="role_capabilities")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["role", "capability"], name="uniq_role_capability")]


class RoleAssignment(BaseModelMixin):
    """Grants a role to a user, optionally only within one department (NULL = all departments)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_assignments")
    role = models.ForeignKey(AccessRole, on_delete=models.CASCADE, related_name="assignments")
    department = models.ForeignKey("org.Department", null=True, blank=True, on_delete=models.CASCADE,
                                   related_name="role_assignments")
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["user__email", "role__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role", "department"],
                condition=Q(is_active=True, department__isnull=False),
                name="uniq_active_assignment_department",
            ),
            models.UniqueConstraint(
                fields=["user", "role"],
                condition=Q(is_active=True, department__isnull=True),
                name="uniq_active_assignment_global",
            ),
        ]

    def __str__(self):
        scope = self.department.name if self.department_id else "all departments"
        return f"{self.user} → {self.role} ({scope})"


class AuthzDenialLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    capability_key = models.CharField(max_length=64)
    path = models.CharField(max_length=500, blank=True)
    method = models.CharField(max_length=10, blank=True)
    department_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
