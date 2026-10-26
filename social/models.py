from django.conf import settings
from django.db import models
from django.utils import timezone


class Network(models.TextChoices):
    INSTAGRAM = "instagram", "Instagram"
    FACEBOOK = "facebook", "Facebook"
    X = "x", "X"
    BLUESKY = "bluesky", "Bluesky"


# Visuel utilisé par réseau (social.visuals.FORMATS) et longueur maximale du texte.
FORMAT = {"instagram": "portrait", "facebook": "portrait", "x": "paysage", "bluesky": "paysage"}
LIMIT = {"instagram": 2200, "facebook": 5000, "x": 280, "bluesky": 300}


class PostQuerySet(models.QuerySet):
    def due(self):
        return self.filter(status=Post.Status.SCHEDULED, scheduled_at__lte=timezone.now())


class Post(models.Model):
    """Publication d'un événement sur un réseau, immédiate ou programmée (envoyée par la tâche de fond)."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Programmée"
        SENDING = "sending", "En cours d'envoi"
        PUBLISHED = "published", "Publiée"
        FAILED = "failed", "Échec"
        CANCELLED = "cancelled", "Annulée"

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="posts")
    network = models.CharField("réseau", max_length=10, choices=Network.choices)
    text = models.TextField("texte")
    scheduled_at = models.DateTimeField("prévue le", default=timezone.now, db_index=True)
    status = models.CharField("état", max_length=10, choices=Status.choices, default=Status.SCHEDULED, db_index=True)
    attempts = models.PositiveSmallIntegerField("tentatives", default=0)
    external_id = models.CharField("identifiant sur le réseau", max_length=200, blank=True)
    external_url = models.URLField("lien de la publication", blank=True, max_length=500)
    error = models.TextField("erreur", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField("publiée le", null=True, blank=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-scheduled_at"]
        verbose_name = "publication"

    def __str__(self):
        return f"{self.get_network_display()} — {self.event}"

    @property
    def visual_format(self):
        return FORMAT[self.network]
