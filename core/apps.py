from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = "Site"

    def ready(self):
        from . import security  # noqa: F401  (signaux de connexion)
