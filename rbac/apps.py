from django.apps import AppConfig


class RbacConfig(AppConfig):
    name = "rbac"
    verbose_name = "Roles & permissions"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401
