from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .i18n import Translated


class ContactMessage(models.Model):
    name = models.CharField("nom", max_length=120)
    email = models.EmailField("courriel")
    subject = models.CharField("objet", max_length=40)
    message = models.TextField()
    created_at = models.DateTimeField("reçu le", auto_now_add=True)
    handled = models.BooleanField("traité", default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "message de contact"
        verbose_name_plural = "messages de contact"

    def __str__(self):
        return f"{self.name} — {self.get_subject_display()}"

    def get_subject_display(self):
        return dict(SUBJECTS).get(self.subject, self.subject)


SUBJECTS = [
    ("question", _("Une question")),
    ("evenement", _("Un problème avec un événement")),
    ("partenariat", _("Un partenariat, une source d'événements à ajouter")),
    ("autre", _("Autre chose")),
]


class Announcement(models.Model):
    """Bandeau d'annonce en haut de toutes les pages, géré par l'équipe."""

    class Tone(models.TextChoices):
        SOLEIL = "soleil", "Jaune (mise en avant)"
        CHAISE = "chaise", "Bleu (information)"
        ALERTE = "alerte", "Rouge (urgent)"

    message = models.CharField("message", max_length=240)
    message_en = models.CharField("message (anglais)", max_length=240, blank=True)
    link_url = models.CharField("lien", max_length=300, blank=True, help_text="Adresse complète ou chemin du site (/evenements/…)")
    link_label = models.CharField("texte du lien", max_length=60, blank=True)
    link_label_en = models.CharField("texte du lien (anglais)", max_length=60, blank=True)
    tone = models.CharField("couleur", max_length=10, choices=Tone.choices, default=Tone.SOLEIL)
    starts_at = models.DateTimeField("début", null=True, blank=True, help_text="Vide = tout de suite")
    ends_at = models.DateTimeField("fin", null=True, blank=True, help_text="Vide = jusqu'à désactivation")
    is_active = models.BooleanField("actif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    message_tr = Translated("message")
    link_label_tr = Translated("link_label")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "annonce"

    def __str__(self):
        return self.message

    @classmethod
    def current(cls):
        now = timezone.now()
        return (cls.objects.filter(is_active=True)
                .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
                .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now)).first())


class Ban(models.Model):
    """Adresse IP bloquée après des échecs de connexion (voir core.security)."""

    ip = models.GenericIPAddressField("adresse IP", unique=True)
    until = models.DateTimeField("bloquée jusqu'au")
    reason = models.CharField("motif", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-until"]
        verbose_name = "adresse bloquée"
        verbose_name_plural = "adresses bloquées"

    def __str__(self):
        return f"{self.ip} jusqu'au {self.until:%d/%m %H:%M}"


class LoginFailure(models.Model):
    ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "échec de connexion"
        verbose_name_plural = "échecs de connexion"


class JobRun(models.Model):
    """Dernier passage de chaque tâche planifiée (voir core.jobs), pour savoir si la tâche de fond tourne."""

    name = models.CharField("tâche", max_length=60, unique=True)
    last_started = models.DateTimeField("dernier départ", null=True, blank=True)
    last_finished = models.DateTimeField("dernière fin", null=True, blank=True)
    last_ok = models.BooleanField("réussie", default=True)
    last_message = models.TextField("compte rendu", blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "tâche planifiée"
        verbose_name_plural = "tâches planifiées"

    def __str__(self):
        return self.name
