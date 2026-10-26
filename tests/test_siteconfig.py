from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.core.mail.backends.console import EmailBackend as ConsoleBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from siteconfig.crypto import decrypt, encrypt
from siteconfig.mail import ConfigEmailBackend, backend_for
from siteconfig.models import ConfigChange, SiteConfig


class CryptoTests(TestCase):
    def test_round_trip_and_empty(self):
        token = encrypt("s3cret")
        self.assertNotIn("s3cret", token)
        self.assertEqual(decrypt(token), "s3cret")
        self.assertEqual(encrypt(""), "")
        self.assertEqual(decrypt(""), "")

    def test_unreadable_token_gives_empty_string(self):
        self.assertEqual(decrypt("pas-un-jeton"), "")

    def test_password_is_encrypted_at_rest(self):
        config = SiteConfig.get()
        config.smtp_password = "mot-de-passe-smtp"
        config.save()
        with connection.cursor() as cursor:
            cursor.execute("SELECT smtp_password FROM siteconfig_siteconfig WHERE id = 1")
            raw = cursor.fetchone()[0]
        self.assertNotIn("mot-de-passe-smtp", raw)
        self.assertEqual(SiteConfig.get().smtp_password, "mot-de-passe-smtp")


class MailBackendTests(TestCase):
    def test_console_until_smtp_is_set(self):
        self.assertIsInstance(backend_for(SiteConfig.get()), ConsoleBackend)

    def test_smtp_settings_come_from_database(self):
        config = SiteConfig.get()
        config.smtp_host, config.smtp_port, config.smtp_security = "smtp.mail.ovh.net", 465, "ssl"
        config.smtp_user, config.smtp_password = "contact@nice-event.fr", "pw"
        config.save()
        backend = backend_for(SiteConfig.get())
        self.assertIsInstance(backend, SMTPBackend)
        self.assertEqual((backend.host, backend.port, backend.username, backend.password), ("smtp.mail.ovh.net", 465, "contact@nice-event.fr", "pw"))
        self.assertTrue(backend.use_ssl)
        self.assertFalse(backend.use_tls)

    def test_default_sender_is_replaced(self):
        config = SiteConfig.get()
        config.from_email = "Nice-Event <bonjour@nice-event.fr>"
        config.save()
        backend = ConfigEmailBackend()
        sent = []
        backend.inner.send_messages = lambda msgs: sent.extend(msgs) or len(msgs)
        backend.send_messages([EmailMessage("a", "b", settings.DEFAULT_FROM_EMAIL, ["x@example.org"]),
                               EmailMessage("a", "b", "autre@example.org", ["x@example.org"])])
        self.assertEqual(sent[0].from_email, "Nice-Event <bonjour@nice-event.fr>")
        self.assertEqual(sent[1].from_email, "autre@example.org")


class SettingsPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("vincent", "v@example.org", "pw")
        self.staff = User.objects.create_user("modo", "m@example.org", "pw", is_staff=True)

    def post_settings(self, **overrides):
        data = {"smtp_host": "smtp.mail.ovh.net", "smtp_port": 465, "smtp_security": "ssl",
                "smtp_user": "contact@nice-event.fr", "smtp_password": "", "from_email": "Nice-Event <contact@nice-event.fr>",
                "contact_email": "contact@nice-event.fr", "scan_times": "10:00,16:00,22:00", "meta_api_version": "v24.0",
                "social_signature": "#Nice"}
        data.update(overrides)
        return self.client.post(reverse("gestion:settings"), data)

    def test_only_superusers(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("gestion:settings")).status_code, 302)
        self.assertEqual(self.client.get(reverse("gestion:dashboard")).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("gestion:settings")).status_code, 200)

    def test_password_kept_when_left_blank_and_never_displayed(self):
        self.client.force_login(self.admin)
        self.post_settings(smtp_password="secret-1")
        self.assertEqual(SiteConfig.get().smtp_password, "secret-1")
        self.post_settings(smtp_host="ssl0.ovh.net")
        config = SiteConfig.get()
        self.assertEqual((config.smtp_host, config.smtp_password), ("ssl0.ovh.net", "secret-1"))
        page = self.client.get(reverse("gestion:settings")).content.decode()
        self.assertNotIn("secret-1", page)
        self.post_settings(clear_smtp_password="on")
        self.assertEqual(SiteConfig.get().smtp_password, "")

    def test_changes_are_logged_without_values(self):
        self.client.force_login(self.admin)
        self.post_settings(smtp_password="secret-2")
        change = ConfigChange.objects.get()
        self.assertEqual(change.user, self.admin)
        self.assertIn("Mot de passe", change.fields)
        self.assertNotIn("secret-2", change.fields)
        self.post_settings()  # rien ne change
        self.assertEqual(ConfigChange.objects.count(), 1)

    def test_test_email_uses_saved_settings(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("gestion:test_email"), {"to": "v@example.org"}, follow=True)
        self.assertContains(response, "Aucun serveur SMTP")
