from django.apps import AppConfig


class CommunityConfig(AppConfig):
    name = "community"
    verbose_name = "Membres"

    def ready(self):
        from . import signals  # noqa: F401
