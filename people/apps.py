from django.apps import AppConfig


class PeopleConfig(AppConfig):
    name = "people"
    verbose_name = "People"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401
