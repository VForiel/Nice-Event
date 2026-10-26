from datetime import datetime, timedelta
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import jobs
from core.models import Ban, ContactMessage, JobRun
from siteconfig.models import SiteConfig


class PageTests(TestCase):
    def test_public_pages(self):
        for url in ["/", "/en/", "/contact/", "/mentions-legales/", "/en/legal-notice/", "/confidentialite/", "/en/privacy/",
                    "/robots.txt", "/sitemap.xml"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_english_pages_are_in_english(self):
        self.assertContains(self.client.get("/en/legal-notice/"), "Legal notice")
        self.assertContains(self.client.get("/en/privacy/"), "Data controller")

    def test_404(self):
        self.assertContains(self.client.get("/nulle-part/"), "Prom", status_code=404)

    def test_csp_header_with_nonce(self):
        response = self.client.get("/")
        self.assertIn("script-src 'self' 'nonce-", response["Content-Security-Policy"])


class ContactTests(TestCase):
    def data(self, **extra):
        return {"name": "Alice", "email": "alice@example.org", "subject": "question", "message": "Bonjour", "consent": "on", **extra}

    def test_message_saved_and_sent_to_configured_address(self):
        config = SiteConfig.get()
        config.contact_email = "equipe@nice-event.fr"
        config.save()
        self.client.post(reverse("core:contact"), self.data())
        self.assertEqual(ContactMessage.objects.count(), 1)
        self.assertEqual(mail.outbox[0].to, ["equipe@nice-event.fr"])

    def test_honeypot(self):
        self.client.post(reverse("core:contact"), self.data(website="spam"))
        self.assertEqual(ContactMessage.objects.count(), 0)


class SecurityTests(TestCase):
    def test_generic_admin_username_bans_immediately(self):
        self.client.post("/admin/login/", {"username": "admin", "password": "x"})
        self.assertTrue(Ban.objects.filter(ip="127.0.0.1").exists())
        self.assertEqual(self.client.get("/").status_code, 403)


class SchedulerTests(TestCase):
    def at(self, hour, minute=0, day=0):
        return timezone.make_aware(datetime(2026, 11, 2 + day, hour, minute))

    def test_daily_at(self):
        due = jobs.daily_at("10:00", "16:00", "22:00")
        self.assertTrue(due(self.at(10, 1), None))
        self.assertFalse(due(self.at(10, 30), self.at(10, 0)))
        self.assertTrue(due(self.at(16, 0), self.at(10, 0)))
        self.assertFalse(due(self.at(9, 0), self.at(22, 0, day=-1)))
        # Worker arrêté hier soir et relancé le matin : le créneau de 22 h manqué est rattrapé une fois
        self.assertTrue(due(self.at(8, 0), self.at(16, 0, day=-1)))

    def test_every(self):
        due = jobs.every(5)
        now = timezone.now()
        self.assertTrue(due(now, None))
        self.assertFalse(due(now, now - timedelta(minutes=4)))
        self.assertTrue(due(now, now - timedelta(minutes=5)))

    def test_worker_runs_backup_and_records_it(self):
        # La copie à chaud de SQLite attendrait la fin de la transaction du test : on vérifie seulement l'appel.
        with mock.patch("core.jobs.call_command") as backup:
            call_command("worker", run="sauvegarde")
        backup.assert_called_once_with("backup_site")
        run = JobRun.objects.get(name="sauvegarde")
        self.assertTrue(run.last_ok, run.last_message)
        self.assertIsNotNone(run.last_finished)

    def test_failed_job_is_recorded(self):
        jobs.JOBS["boum"] = jobs.Job("boum", jobs.every(1), lambda: 1 / 0)
        try:
            call_command("worker", run="boum")
        finally:
            del jobs.JOBS["boum"]
        run = JobRun.objects.get(name="boum")
        self.assertFalse(run.last_ok)
        self.assertIn("ZeroDivisionError", run.last_message)
