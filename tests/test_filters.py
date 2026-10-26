import json
from datetime import timedelta
from unittest import mock
from urllib.parse import quote

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from aggregator.connectors import page_details, price_from_text
from aggregator.importer import scan
from aggregator.models import Source
from core.text import decode, repair, without_emoji
from events.forms import add_months, repetition
from events.models import Category, Event, SavedFilter
from venues.models import Commune, Venue

from .test_aggregator import FakeFetcher, day, ics
from .test_events import Base, soon


class TextTests(TestCase):
    def test_repair_mojibake(self):
        self.assertEqual(repair("ApÃ©ro crÃ©atif ðŸŽ¨"), "Apéro créatif 🎨")
        self.assertEqual(repair("Ã\x89vÃ©nements La FourmiliÃ¨re"), "Événements La Fourmilière")
        self.assertEqual(repair("une histoire Ã raconter"), "une histoire à raconter")  # A0 devenu espace
        self.assertEqual(repair("Ã‰tÃ© â€” cafÃ©"), "Été — café")
        for good in ("Apéro 🎨 déjà là", "à» né°", "Café « crème »"):
            self.assertEqual(repair(good), good)

    def test_decode_prefers_valid_utf8(self):
        self.assertEqual(decode("Apéro 🎨".encode(), "iso-8859-1"), "Apéro 🎨")
        self.assertEqual(decode("Apéro".encode("cp1252")), "Apéro")

    def test_without_emoji(self):
        self.assertEqual(without_emoji("🔹 Apéro Web Nice ! 🔹"), "Apéro Web Nice !")


class RepetitionTests(Base):
    def test_rules(self):
        from datetime import date

        self.assertEqual(add_months(date(2027, 1, 31), 1), date(2027, 2, 28))
        self.assertEqual(len(repetition(date(2027, 1, 1), date(2027, 1, 10), "day")), 10)
        self.assertEqual(repetition(date(2027, 1, 31), date(2027, 4, 30), "month"),
                         [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)])
        self.assertEqual(len(repetition(date(2027, 3, 1), date(2030, 3, 1), "year")), 4)
        self.assertEqual(repetition(date(2027, 1, 1), date(2027, 1, 20), "day", 7),
                         [date(2027, 1, 1), date(2027, 1, 8), date(2027, 1, 15)])

    def publish(self, **kw):
        self.alice.profile.trusted = True
        self.alice.profile.save()
        self.client.force_login(self.alice)
        return self.client.post(reverse("events:new"), self.form_data(**kw))

    def test_monthly_series_keeps_local_time(self):
        start = timezone.localdate() + timedelta(days=2)
        self.publish(date=start.isoformat(), repeat="month", repeat_until=add_months(start, 5).isoformat())
        series = list(Event.objects.filter(title="Apéro jazz").order_by("starts_at"))
        self.assertEqual(len(series), 6)
        self.assertEqual({e.local_start.strftime("%H:%M") for e in series}, {"19:30"})  # malgré le changement d'heure
        self.assertEqual({e.local_end - e.local_start for e in series}, {timedelta(hours=2, minutes=30)})

    def test_custom_and_limits(self):
        start = timezone.localdate() + timedelta(days=2)
        self.publish(date=start.isoformat(), repeat="custom", repeat_every="3", repeat_unit="day",
                     repeat_until=(start + timedelta(days=9)).isoformat())
        self.assertEqual(Event.objects.filter(title="Apéro jazz").count(), 4)
        response = self.publish(title="Trop", date=start.isoformat(), repeat="day",
                                repeat_until=(start + timedelta(days=100)).isoformat())
        self.assertIn("repeat_until", response.context["form"].errors)
        response = self.publish(title="Trop loin", date=start.isoformat(), repeat="week",
                                repeat_until=(start + timedelta(days=400)).isoformat())
        self.assertIn("repeat_until", response.context["form"].errors)


class FilterTests(Base):
    def setUp(self):
        super().setUp()
        self.antibes_venue = Venue.objects.create(name="Port Vauban", commune=self.antibes, lat=43.585, lon=7.128)
        self.meetup = Source.objects.create(name="Meetup", slug="meetup-a", kind="ical", url="https://m.example/a.ics")
        Source.objects.create(name="Meetup", slug="meetup-b", kind="ical", url="https://m.example/b.ics")
        self.party = Category.objects.get(slug="soiree")
        self.jazz = self.event(title="Jazz à Nice", price_kind="paid", price_min=25)
        self.free_antibes = self.event(title="Concert gratuit Antibes", venue=self.antibes_venue, price_kind="free")
        self.meetup_party = self.event(title="Soirée Meetup", categories=[self.party], source=self.meetup,
                                       external_id="1", organizer=None, age_kind="adults")

    def titles(self, **params):
        query = "&".join(f"{k}={quote(v if isinstance(v, str) else json.dumps(v))}" for k, v in params.items())
        response = self.client.get(reverse("events:list") + "?" + query)
        return sorted(e.title for _day, items in response.context["days"] for e in items)

    def test_only_nice_event_and_hidden_sources(self):
        everything = ["Concert gratuit Antibes", "Jazz à Nice", "Soirée Meetup"]
        self.assertEqual(self.titles(), everything)
        self.assertEqual(self.titles(source="membres"), everything[:2])
        self.assertEqual(self.titles(masquer="meetup"), everything[:2])
        self.assertEqual(self.titles(masquer="nice-event"), ["Soirée Meetup"])

    def test_advanced_rules(self):
        rule = {"op": "or", "rules": [{"field": "categorie", "in": ["soiree"]},
                                      {"field": "proximite", "lat": 43.58, "lon": 7.12, "km": 3}]}
        self.assertEqual(self.titles(regle=rule), ["Concert gratuit Antibes", "Soirée Meetup"])
        rule = {"op": "and", "rules": [{"field": "categorie", "in": ["concert"]},
                                       {"not": True, "field": "prix_max", "value": 10}]}
        self.assertEqual(self.titles(regle=rule), ["Jazz à Nice"])
        rule = {"op": "and", "rules": [{"field": "age", "value": 12},
                                       {"op": "or", "not": True, "rules": [{"field": "commune", "in": ["antibes"]}]}]}
        self.assertEqual(self.titles(regle=rule), ["Jazz à Nice"])
        rule = {"op": "and", "rules": [{"field": "source", "in": ["meetup"]}]}
        self.assertEqual(self.titles(regle=rule), ["Soirée Meetup"])
        self.assertEqual(len(self.titles(regle="pas du json")), 3)  # règle illisible : ignorée
        response = self.client.get(reverse("events:map_data") + "?regle=" + quote(json.dumps(
            {"op": "and", "rules": [{"field": "commune", "in": ["antibes"]}]})))
        self.assertEqual([e["title"] for e in response.json()["events"]], ["Concert gratuit Antibes"])

    def test_saved_filters(self):
        url = reverse("events:api_filter_save")
        rule = {"op": "and", "rules": [{"field": "categorie", "in": ["concert"]}]}
        self.assertEqual(self.client.post(url, {"name": "x", "rule": json.dumps(rule)}).status_code, 302)  # connexion
        self.client.force_login(self.alice)
        saved = self.client.post(url, {"name": "Concerts", "rule": json.dumps(rule)}).json()
        self.client.post(url, {"name": "Concerts", "rule": json.dumps({"op": "or", "rules": []})})
        self.assertEqual(SavedFilter.objects.filter(user=self.alice).count(), 1)
        self.assertEqual(self.client.post(url, {"name": "", "rule": "{}"}).status_code, 400)
        response = self.client.get(reverse("events:list"))
        self.assertEqual(response.context["filter_spec"]["saved"][0]["name"], "Concerts")
        other = self.member("bob@example.org", "Bob")
        self.client.force_login(other)
        self.client.post(reverse("events:api_filter_delete", args=[saved["id"]]))
        self.assertTrue(SavedFilter.objects.filter(pk=saved["id"]).exists())  # pas le sien
        self.client.force_login(self.alice)
        self.client.post(reverse("events:api_filter_delete", args=[saved["id"]]))
        self.assertFalse(SavedFilter.objects.exists())


class EnrichmentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.nice = Commune.objects.get(insee="06088")

    def test_price_from_text(self):
        self.assertEqual(price_from_text("inscription 30 euros pour l'atelier"), (None, 30.0))
        self.assertEqual(price_from_text("Tarif : 10€ / 7,50 € réduit"), (None, 7.5))
        self.assertEqual(price_from_text("Entrée libre et gratuite"), (True, None))
        self.assertEqual(price_from_text("Rendez-vous à 19 h"), (None, None))

    def test_page_details(self):
        page = '<meta property="og:image" content="/img/affiche.jpg">'
        self.assertEqual(page_details(page, "https://ex.org/e/1")["image"], "https://ex.org/img/affiche.jpg")
        page = ('<script type="application/ld+json">{"@type": "Event", "name": "A", "startDate": "2030-01-01", '
                '"image": "https://ex.org/a.jpg", "offers": {"@type": "AggregateOffer", "lowPrice": "12"}}</script>')
        self.assertEqual(page_details(page, "https://ex.org/e/1"), {"image": "https://ex.org/a.jpg", "free": False, "price": 12.0})

    def test_scan_reads_price_and_image_from_event_page(self):
        source = Source.objects.create(name="Asso", slug="asso", kind="ical", url="https://exemple.org/a.ics",
                                       default_commune=self.nice)
        feed = ics([("1", "ApÃ©ro jazz", day(3), "Le Comptoir, 12 rue Bonaparte")])
        fetcher = FakeFetcher({
            "https://exemple.org/a.ics": feed,
            "https://exemple.org/e": '<meta property="og:image" content="https://exemple.org/p.jpg"> 15 €',
            "https://exemple.org/p.jpg": b"pas une image",
        })
        with mock.patch("venues.geocode.search", return_value=[]):
            scan(source, fetcher)
        event = Event.objects.get(source=source)
        self.assertEqual(event.title, "Apéro jazz")
        self.assertIn("https://exemple.org/e", fetcher.requested)
        self.assertIn("https://exemple.org/p.jpg", fetcher.requested)  # image tentée (refusée : pas une image)
        self.assertEqual(event.price_kind, Event.Price.UNKNOWN)  # le prix de la page n'est pris que s'il est structuré
        with mock.patch("venues.geocode.search", return_value=[]):
            scan(source, fetcher)
        self.assertEqual(fetcher.requested.count("https://exemple.org/e"), 1)  # page lue une seule fois
