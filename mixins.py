from django.db import models


class BaseModelMixin(models.Model):
    """created_at / updated_at on every model (same as sis_backend)."""

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        abstract = True
