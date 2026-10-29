"""Alertes des membres : canaux de réception et événements déjà signalés.

Les filtres eux-mêmes sont des events.SavedFilter (règle + alerte + fréquence).
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Channel(models.Model):
    class Kind(models.TextChoices):
        EMAIL = "email", _("Courriel")
        PUSH = "push", _("Notification du navigateur")
        DISCORD = "discord", _("Discord (webhook)")
        TELEGRAM = "telegram", "Telegram"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alert_channels")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # Discord : {"webhook": url} ; Telegram : {"chat_id": "123"}
    config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "canal d'alerte"
        constraints = [models.UniqueConstraint(fields=["user", "kind"], name="unique_alert_channel")]

    def __str__(self):
        return f"{self.user} · {self.get_kind_display()}"


class PushSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "abonnement aux notifications du navigateur"


class Hit(models.Model):
    """Événement déjà signalé pour un filtre : jamais deux fois le même."""

    saved_filter = models.ForeignKey("events.SavedFilter", on_delete=models.CASCADE, related_name="hits")
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="+")
    sent_at = models.DateTimeField(null=True, blank=True)  # vide : en attente du prochain résumé
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["saved_filter", "event"], name="unique_alert_hit")]
