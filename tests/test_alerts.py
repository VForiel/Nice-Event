import json
from datetime import datetime, time, timedelta
from unittest import mock
from urllib.parse import urlencode

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from aggregator.importer import scan
from aggregator.models import Source
from alerts import send
from alerts.models import Channel
from community.models import Notification
from events.models import Category, Event, SavedFilter
from events.rules import regex_error
from venues.models import Commune, Venue

from .test_aggregator import FakeFetcher
from .test_events import Base, soon


class BarTests(Base):
    """Menus de l'agenda et de la carte : OU dans un menu, ET entre les menus, filtre personnalisé de la session."""

    def setUp(self):
        super().setUp()
        self.antibes_venue = Venue.objects.create(name="Port Vauban", commune=self.antibes, lat=43.585, lon=7.128)
        self.meetup = Source.objects.create(name="Meetup", slug="meetup-a", kind="ical", url="https://m.example/a.ics")
        Source.objects.create(name="Meetup", slug="meetup-b", kind="ical", url="https://m.example/b.ics")
        self.party = Category.objects.get(slug="soiree")
        self.jazz = self.event(title="Jazz à Nice", price_kind="paid", price_min=25, language="international")
        self.free_antibes = self.event(title="Concert gratuit Antibes", venue=self.antibes_venue, price_kind="free",
                                       age_kind="range", age_min=6, age_max=12, description="Avec un atelier de danse")
        self.meetup_party = self.event(title="Soirée Meetup", categories=[self.party], source=self.meetup,
                                       external_id="1", organizer=None, age_kind="adults")

    def titles(self, params=(), url=None):
        response = self.client.get((url or reverse("events:list")) + "?" + urlencode(list(params)))
        return sorted(e.title for _day, items in response.context["days"] for e in items)

    def test_menus(self):
        everything = ["Concert gratuit Antibes", "Jazz à Nice", "Soirée Meetup"]
        self.assertEqual(self.titles(), everything)
        self.assertEqual(self.titles([("categorie", "concert")]), everything[:2])
        self.assertEqual(self.titles([("categorie", "_aucun")]), [])
        self.assertEqual(self.titles([("src", "nice-event")]), everything[:2])
        self.assertEqual(self.titles([("src", "meetup")]), ["Soirée Meetup"])
        # Zone OU proximité (Antibes, à 3 km)
        self.assertEqual(self.titles([("zone", "monaco"), ("pres", "43.58,7.12,3")]), ["Concert gratuit Antibes"])
        # Âge : public OU tranche, ET prix
        self.assertEqual(self.titles([("age_min", "8"), ("age_max", "10")]), everything[:2])
        self.assertEqual(self.titles([("public", "adults"), ("prix", "free"), ("prix", "unknown")]), ["Soirée Meetup"])
        self.assertEqual(self.titles([("langue", "international")]), ["Jazz à Nice"])
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        far = (timezone.localdate() + timedelta(days=20)).isoformat()
        self.assertEqual(self.titles([("quand", "dates"), ("du", tomorrow), ("au", far)]), everything)
        self.assertEqual(self.titles([("quand", "dates"), ("du", far)]), [])
        # Anciens liens toujours compris
        self.assertEqual(self.titles([("gratuit", "1")]), ["Concert gratuit Antibes", "Soirée Meetup"])
        self.assertEqual(self.titles([("source", "membres")]), everything[:2])
        # Résultats partiels (mise à jour sans recharger) et données de la carte
        response = self.client.get(reverse("events:list") + "?categorie=soiree&partiel=1")
        self.assertTemplateUsed(response, "events/_results.html")
        self.assertNotContains(response, "<html")
        data = self.client.get(reverse("events:map_data") + "?zone=nice").json()
        self.assertEqual(sorted(e["title"] for e in data["events"]), ["Jazz à Nice", "Soirée Meetup"])

    def test_date_range_lists_its_own_days(self):
        expo = self.event(title="Exposition", starts_at=soon(1, 10), end=soon(30, 18))
        self.event(title="Avant", starts_at=soon(5))
        self.event(title="Pendant", starts_at=soon(10))
        self.event(title="Après", starts_at=soon(12))
        first = timezone.localdate() + timedelta(days=10)
        params = [("quand", "dates"), ("du", first.isoformat()), ("au", (first + timedelta(days=1)).isoformat())]
        response = self.client.get(reverse("events:list") + "?" + urlencode(params + [("partiel", "1")]))
        days = [(day, [e.title for e in items]) for day, items in response.context["days"]]
        # L'exposition commencée avant la plage s'affiche à son premier jour, avant les événements du jour
        self.assertEqual(days, [(first, ["Exposition", "Pendant"])])
        # Un seul jour touché dans le calendrier : ce jour-là seulement
        self.assertEqual(self.titles(params[:2]), ["Exposition", "Pendant"])
        self.assertIn(expo.title, self.titles([("quand", "dates"), ("du", (first + timedelta(days=2)).isoformat())]))

    def test_custom_filter_for_the_session(self):
        rule = {"op": "and", "rules": [{"field": "regex", "value": "danse", "not": True},
                                       {"field": "categorie", "in": ["concert"]}]}
        response = self.client.post(reverse("alerts:use"), {"rule": json.dumps(rule), "name": "Sans danse", "to": "carte"})
        self.assertRedirects(response, reverse("events:map"), fetch_redirect_response=False)
        response = self.client.get(reverse("events:list"))
        self.assertContains(response, "Sans danse")
        self.assertEqual(self.titles(), ["Jazz à Nice"])
        self.assertEqual([e["title"] for e in self.client.get(reverse("events:map_data")).json()["events"]], ["Jazz à Nice"])
        self.client.post(reverse("alerts:clear"))
        self.assertEqual(len(self.titles()), 3)
        # Règle vide : refusée
        response = self.client.post(reverse("alerts:use"), {"rule": json.dumps({"op": "and", "rules": []})})
        self.assertRedirects(response, reverse("alerts:filters"), fetch_redirect_response=False)

    def test_preview_and_regex(self):
        url = reverse("alerts:preview")
        rule = {"op": "or", "rules": [{"field": "regex", "value": r"\bjazz\b"}, {"field": "age_range", "min": 7, "max": 7}]}
        data = self.client.get(url, {"regle": json.dumps(rule)}).json()
        self.assertEqual(data["count"], 3)  # jazz, ou âge 7 (tranche 6-12, et les événements sans âge précisé)
        data = self.client.get(url, {"regle": json.dumps({"op": "and", "rules": [{"field": "regex", "value": "(a+)+"}]})}).json()
        self.assertIsNone(data["count"])
        self.assertTrue(data["errors"])
        self.assertTrue(regex_error("[abc"))
        self.assertEqual(regex_error(r"\bski|randonn"), "")
        self.assertEqual(self.client.get(reverse("alerts:filters")).status_code, 200)

    def test_saved_filters_and_alerts(self):
        url = reverse("alerts:save")
        rule = {"op": "and", "rules": [{"field": "categorie", "in": ["concert"]}]}
        self.assertEqual(self.client.post(url, {"name": "x", "rule": json.dumps(rule)}).status_code, 302)  # connexion
        self.client.force_login(self.alice)
        saved = self.client.post(url, {"name": "Concerts", "rule": json.dumps(rule), "alert": "1", "frequency": "now"}).json()
        self.assertTrue(saved["alert"])
        renamed = self.client.post(url, {"id": saved["id"], "name": "Mes concerts", "rule": json.dumps(rule)}).json()
        self.assertEqual(renamed["id"], saved["id"])
        self.assertEqual(SavedFilter.objects.get().name, "Mes concerts")
        self.assertEqual(self.client.post(url, {"name": "", "rule": "{}"}).status_code, 400)
        response = self.client.get(reverse("alerts:filters"))
        self.assertContains(response, "Mes concerts")
        bob = self.member("bob@example.org", "Bob")
        self.client.force_login(bob)
        self.assertEqual(self.client.post(reverse("alerts:alert", args=[saved["id"]]), {"alert": "0"}).status_code, 404)
        self.client.post(reverse("alerts:delete", args=[saved["id"]]))
        self.assertTrue(SavedFilter.objects.exists())  # pas le sien
        self.client.force_login(self.alice)
        self.client.post(reverse("alerts:alert", args=[saved["id"]]), {"alert": "1", "frequency": "daily"})
        self.assertEqual(SavedFilter.objects.get().frequency, "daily")
        self.client.post(reverse("alerts:delete", args=[saved["id"]]))
        self.assertFalse(SavedFilter.objects.exists())

    def test_channels(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("alerts:channels"), {"email": "on", "discord": "on", "discord_webhook": "https://evil.example/x"})
        self.assertRedirects(response, reverse("alerts:filters") + "#canaux", fetch_redirect_response=False)
        self.assertFalse(Channel.objects.exists())  # adresse refusée : rien enregistré
        self.client.post(reverse("alerts:channels"), {"email": "on", "discord": "on",
                                                      "discord_webhook": "https://discord.com/api/webhooks/1/abc"})
        self.assertEqual(set(Channel.objects.filter(is_active=True).values_list("kind", flat=True)), {"email", "discord"})
        self.assertEqual(self.client.get("/sw.js")["Content-Type"], "application/javascript")


class AlertSendingTests(Base):
    def setUp(self):
        super().setUp()
        self.saved = SavedFilter.objects.create(user=self.alice, name="Concerts à Nice", alert=True,
                                                alert_since=timezone.now() - timedelta(minutes=1),
                                                rule={"op": "and", "rules": [{"field": "categorie", "in": ["concert"]}]})
        Channel.objects.create(user=self.alice, kind=Channel.Kind.EMAIL)
        Channel.objects.create(user=self.alice, kind=Channel.Kind.DISCORD, config={"webhook": "https://discord.com/api/webhooks/1/abc"})

    def test_new_matching_event_is_sent_once_on_every_channel(self):
        old = self.event(title="Déjà là")
        Event.objects.filter(pk=old.pk).update(published_at=timezone.now() - timedelta(days=1))
        self.event(title="Nouveau concert")
        self.event(title="Autre chose", categories=[Category.objects.get(slug="sport")])
        with mock.patch("alerts.send.requests.post") as post:
            send.run()
            send.run()
        self.assertEqual(list(Notification.objects.filter(verb="alert").values_list("event__title", flat=True)), ["Nouveau concert"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Nouveau concert", mail.outbox[0].body)
        self.assertEqual(post.call_count, 1)
        self.assertIn("Nouveau concert", json.dumps(post.call_args.kwargs["json"], ensure_ascii=False))

    def test_daily_digest_waits_for_the_evening(self):
        self.saved.frequency = SavedFilter.Frequency.DAILY
        self.saved.save()
        self.event(title="Concert un")
        self.event(title="Concert deux")
        morning = timezone.make_aware(datetime.combine(timezone.localdate(), time(9, 0)))
        evening = timezone.make_aware(datetime.combine(timezone.localdate(), time(18, 30)))
        with mock.patch("alerts.send.requests.post"):
            send.run(now=morning)
            self.assertEqual(len(mail.outbox), 0)
            send.run(now=evening)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("2 nouveaux événements", mail.outbox[0].subject)

    def test_vapid_keys_are_created_once(self):
        keys = send.vapid_keys()
        self.assertEqual(send.vapid_keys(), keys)
        self.assertEqual(len(keys["public"]), 87)  # point P-256 non compressé, base64url


class Ajc06Tests(TestCase):
    def test_feed_is_imported_with_all_details(self):
        nice = Commune.objects.get(insee="06088")
        source = Source.objects.create(name="AJC06", slug="ajc06", kind="ajc06", url="https://ajc.example/nice-event.json",
                                       default_commune=nice)
        start = (timezone.localdate() + timedelta(days=4)).isoformat()
        feed = {"events": [{
            "id": 12, "url": "https://ajc.example/evenements/halloween/", "title": "Soirée Halloween 🎃",
            "summary": "Costumes bienvenus", "description": "## Programme\n\nQuiz, *bal* et soupe au potiron.",
            "title_en": "Halloween party", "start": f"{start}T20:00:00+01:00", "end": None, "all_day": False,
            "place": "Le Comptoir", "address": "12 rue Bonaparte, 06300 Nice", "lat": 43.70, "lon": 7.28,
            "image": "", "price": "Gratuit", "registration_url": "https://ajc.example/inscription",
            "types": ["soiree", "asso"], "organizer": "AJC06 (sortie proposée par un·e membre)"}]}
        with mock.patch("venues.geocode.search", return_value=[]):
            scan(source, FakeFetcher({source.url: json.dumps(feed)}))
        event = Event.objects.get(source=source)
        self.assertEqual((event.title, event.title_en, event.summary), ("Soirée Halloween 🎃", "Halloween party", "Costumes bienvenus"))
        self.assertIn("soupe au potiron", event.description)
        self.assertEqual(event.price_kind, Event.Price.FREE)
        self.assertEqual(event.ticket_url, "https://ajc.example/inscription")
        self.assertEqual(sorted(event.categories.values_list("slug", flat=True)), ["rencontres", "soiree"])
        self.assertEqual(event.venue.commune, nice)
        response = self.client.get(reverse("events:from_source", args=["ajc06", "12"]))
        self.assertRedirects(response, event.get_absolute_url())
        response = self.client.get(reverse("events:detail", args=[event.slug]))
        self.assertContains(response, "<h2>Programme</h2>", html=True)
        # Décoché côté AJC06 : disparaît du flux, puis de Nice-Event
        with mock.patch("venues.geocode.search", return_value=[]):
            scan(source, FakeFetcher({source.url: json.dumps({"events": []})}))
        self.assertIsNotNone(Event.objects.get(source=source).missing_since)
        response = self.client.get(reverse("events:from_source", args=["ajc06", "999"]))
        self.assertRedirects(response, reverse("events:list"))

    def test_poster_follows_the_source(self):
        import io
        import shutil
        import tempfile

        from django.test import override_settings
        from PIL import Image

        def png(color):
            buffer = io.BytesIO()
            Image.new("RGB", (40, 30), color).save(buffer, "PNG")
            return buffer.getvalue()

        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        nice = Commune.objects.get(insee="06088")
        source = Source.objects.create(name="AJC06", slug="ajc06", kind="ajc06", url="https://ajc.example/f.json",
                                       default_commune=nice)
        start = (timezone.localdate() + timedelta(days=4)).isoformat()

        def feed(image):
            return json.dumps({"events": [{"id": 1, "title": "Rando", "start": f"{start}T09:00:00+01:00",
                                           "place": "Col", "address": "06300 Nice", "image": image, "types": []}]})

        pages = {"https://ajc.example/a.png?v=1": png("red"), "https://ajc.example/a.png?v=2": png("blue")}
        with override_settings(MEDIA_ROOT=media), mock.patch("venues.geocode.search", return_value=[]):
            scan(source, FakeFetcher({source.url: feed("https://ajc.example/a.png?v=1"), **pages}))
            first = Event.objects.get(source=source)
            self.assertEqual(first.external_image, "https://ajc.example/a.png?v=1")
            scan(source, FakeFetcher({source.url: feed("https://ajc.example/a.png?v=1"), **pages}))
            self.assertEqual(Event.objects.get(source=source).photo.name, first.photo.name)  # inchangée : rien à refaire
            scan(source, FakeFetcher({source.url: feed("https://ajc.example/a.png?v=2"), **pages}))
            event = Event.objects.get(source=source)
            self.assertEqual(event.external_image, "https://ajc.example/a.png?v=2")
            with event.photo.open("rb") as f:
                self.assertEqual(Image.open(f).getpixel((1, 1))[:3], (0, 0, 255))
            scan(source, FakeFetcher({source.url: feed(""), **pages}))
            self.assertFalse(Event.objects.get(source=source).photo)  # affiche retirée côté AJC06
