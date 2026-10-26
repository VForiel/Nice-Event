"""Backend de courriel qui lit le serveur SMTP dans les réglages du site à chaque envoi : une modification dans
/gestion/reglages/ s'applique tout de suite, sans redémarrage ni .env."""

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.console import EmailBackend as ConsoleBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend

from .models import SiteConfig


def backend_for(config, fail_silently=False):
    if not config.smtp_ready:
        return ConsoleBackend(fail_silently=fail_silently)
    return SMTPBackend(
        host=config.smtp_host,
        port=config.smtp_port,
        username=config.smtp_user or None,
        password=config.smtp_password or None,
        use_ssl=config.smtp_security == SiteConfig.Security.SSL,
        use_tls=config.smtp_security == SiteConfig.Security.STARTTLS,
        timeout=getattr(settings, "EMAIL_TIMEOUT", 20),
        fail_silently=fail_silently,
    )


class ConfigEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        config = SiteConfig.get()
        self.from_email = config.from_email
        self.inner = backend_for(config, fail_silently)

    def open(self):
        return self.inner.open()

    def close(self):
        return self.inner.close()

    def send_messages(self, email_messages):
        for message in email_messages:
            # Expéditeur par défaut du code (settings.DEFAULT_FROM_EMAIL) remplacé par celui des réglages.
            if message.from_email in (None, "", settings.DEFAULT_FROM_EMAIL):
                message.from_email = self.from_email
        return self.inner.send_messages(email_messages)
