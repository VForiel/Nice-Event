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

    # Comptes et publication
    require_email_confirmation = models.BooleanField(
        "courriel confirmé pour publier", default=True,
        help_text="Les membres doivent avoir ouvert le lien reçu par courriel avant de publier un événement. "
                  "Le premier événement de chaque compte reste modéré dans tous les cas.")

    # Agendas externes (app aggregator)
    scan_times = models.CharField("horaires des scans", max_length=60, default="10:00,16:00,22:00",
                                  help_text="Heures de Paris, séparées par des virgules.")

    # Réseaux sociaux (diffusion depuis /gestion/, app social)
    social_signature = models.CharField("signature des publications", max_length=200, blank=True,
                                        default="#Nice #CoteDAzur #NiceEvent",
                                        help_text="Ajoutée à la fin des textes (hashtags…).")
    # Connexion avec Google (OpenID Connect)
    google_client_id = models.CharField("Google : ID client", max_length=200, blank=True,
                                        help_text="Console Google Cloud › API et services › Identifiants › ID client OAuth")
    google_client_secret = EncryptedTextField("Google : code secret du client", blank=True)

    bluesky_enabled = models.BooleanField("Bluesky actif", default=False)
    bluesky_handle = models.CharField("identifiant Bluesky", max_length=100, blank=True, help_text="Ex. nice-event.bsky.social")
    bluesky_app_password = EncryptedTextField("mot de passe d'application Bluesky", blank=True,
                                              help_text="Réglages › Confidentialité et sécurité › Mots de passe d'application.")
    meta_api_version = models.CharField("version de l'API Graph de Meta", max_length=10, default="v24.0")
    facebook_enabled = models.BooleanField("Facebook actif", default=False)
    facebook_page_id = models.CharField("identifiant de la Page Facebook", max_length=40, blank=True)
    facebook_page_token = EncryptedTextField("jeton d'accès de la Page", blank=True,
                                             help_text="Jeton de Page longue durée (sert aussi à Instagram).")
    instagram_enabled = models.BooleanField("Instagram actif", default=False)
    instagram_user_id = models.CharField("identifiant du compte Instagram professionnel", max_length=40, blank=True,
                                         help_text="Compte relié à la Page Facebook.")
    x_enabled = models.BooleanField("X actif", default=False)
    x_api_key = models.CharField("X : API key", max_length=100, blank=True)
    x_api_secret = EncryptedTextField("X : API key secret", blank=True)
    x_access_token = models.CharField("X : access token", max_length=100, blank=True)
    x_access_secret = EncryptedTextField("X : access token secret", blank=True)
    # Alertes des membres (page « Filtres & alertes »)
    telegram_bot_token = EncryptedTextField("jeton du bot Telegram", blank=True,
                                            help_text="Créé avec @BotFather ; les membres indiquent leur identifiant de discussion.")
    telegram_bot_name = models.CharField("nom du bot Telegram", max_length=60, blank=True, help_text="Sans @, ex. NiceEventBot")
    # Notifications du navigateur (Web Push) : paire de clés VAPID créée automatiquement au premier besoin.
    vapid_public_key = models.CharField(max_length=120, blank=True, editable=False)
    vapid_private_key = EncryptedTextField(blank=True, editable=False)
    social_checked_at = models.DateTimeField("dernière vérification des comptes", null=True, blank=True)
    social_check = models.JSONField("résultat de la vérification", default=dict, blank=True)

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

    def scan_hours(self):
        hours = []
        for value in self.scan_times.split(","):
            value = value.strip()
            try:
                h, m = (int(x) for x in value.split(":"))
            except ValueError:
                continue
            if 0 <= h < 24 and 0 <= m < 60:
                hours.append(f"{h:02d}:{m:02d}")
        return hours or ["10:00", "16:00", "22:00"]

    @property
    def google_ready(self):
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def smtp_ready(self):
        return bool(self.smtp_host)

    def network_ready(self, network):
        """Réseau activé et identifiants saisis."""
        return bool({
            "bluesky": self.bluesky_enabled and self.bluesky_handle and self.bluesky_app_password,
            "facebook": self.facebook_enabled and self.facebook_page_id and self.facebook_page_token,
            "instagram": self.instagram_enabled and self.instagram_user_id and self.facebook_page_token,
            "x": self.x_enabled and self.x_api_key and self.x_api_secret and self.x_access_token and self.x_access_secret,
        }.get(network, False))


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
