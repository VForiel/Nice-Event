from django.conf import settings
from django.db import models

from .crypto import EncryptedTextField


class SiteConfig(models.Model):
    """Réglages du site modifiables depuis /gestion/reglages/ (une seule ligne, pk = 1).

    Chaque phase y ajoute ses blocs : réseaux sociaux (phase 4), sources et horaires de scan (phase 5).
    """

    class Security(models.TextChoices):
        SSL = "ssl", "SSL/TLS (port 465)"
        STARTTLS = "starttls", "STARTTLS (port 587)"
        NONE = "none", "Aucune (déconseillé)"

    # Courriel
    smtp_host = models.CharField("serveur SMTP", max_length=200, blank=True,
                                 help_text="Ex. smtp.mail.ovh.net. Vide : les courriels s'affichent dans les journaux au lieu de partir.")
    smtp_port = models.PositiveIntegerField("port", default=465)
    smtp_security = models.CharField("sécurité", max_length=10, choices=Security.choices, default=Security.SSL)
    smtp_user = models.CharField("identifiant", max_length=200, blank=True, help_text="En général l'adresse complète.")
    smtp_password = EncryptedTextField("mot de passe", blank=True)
    from_email = models.CharField("expéditeur", max_length=200, default="Nice-Event <contact@nice-event.fr>",
                                  help_text="Nom et adresse affichés aux destinataires. L'adresse doit être celle du compte SMTP.")
    contact_email = models.EmailField("adresse de contact", default="contact@nice-event.fr",
                                      help_text="Reçoit les messages du formulaire de contact ; affichée sur le site.")

    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "réglages du site"
        verbose_name_plural = "réglages du site"

    def __str__(self):
        return "Réglages du site"

    @classmethod
    def get(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    @property
    def smtp_ready(self):
        return bool(self.smtp_host)


class ConfigChange(models.Model):
    """Journal des modifications des réglages : qui, quand, quels champs (jamais les valeurs des secrets)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, verbose_name="par")
    changed_at = models.DateTimeField("le", auto_now_add=True)
    fields = models.CharField("réglages modifiés", max_length=500)

    class Meta:
        ordering = ["-changed_at"]
        verbose_name = "modification des réglages"
        verbose_name_plural = "modifications des réglages"

    def __str__(self):
        return f"{self.changed_at:%d/%m/%Y %H:%M} — {self.fields}"
