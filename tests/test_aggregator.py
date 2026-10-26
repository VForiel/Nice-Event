import json
from datetime import UTC, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from aggregator.importer import scan
from aggregator.models import Source
from events.models import Category, Event
from venues.models import Commune, Venue

User = get_user_model()


def day(n, hour=20):
    return (timezone.localtime() + timedelta(days=n)).replace(hour=hour, minute=0, second=0, microsecond=0)


class FakeFetcher:
    def __init__(self, pages):
        self.pages, self.count, self.requested = pages, 0, []

    def get(self, url, params=None, check_robots=True, binary=False):
        self.count += 1
        self.requested.append(url)
        return self.pages[url]


def ics(events):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//FR"]
    for uid, title, start, location in events:
        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{title}", f"DTSTART:{start.astimezone(UTC):%Y%m%dT%H%M%SZ}",
                  f"DTEND:{(start + timedelta(hours=2)).astimezone(UTC):%Y%m%dT%H%M%SZ}", f"LOCATION:{location}",
                  "DESCRIPTION:Une belle soirée de jazz au bord de l'eau.", "URL:https://exemple.org/e", "END:VEVENT"]
    return "\r\n".join(lines + ["END:VCALENDAR"])


def ld(data):
    return f'<html><head><script type="application/ld+json">{json.dumps(data)}</script></head><body></body></html>'


class ImporterTests(TestCase):
    def setUp(self):
        self.nice = Commune.objects.get(insee="06088")
        self.source = Source.objects.create(name="Asso", slug="asso", kind="ical", url="https://exemple.org/a.ics",
                                            default_commune=self.nice)

    def test_ical_create_update_and_disappear(self):
        feed = {"https://exemple.org/a.ics": ics([("1", "Concert de jazz", day(3), "Le Comptoir, 12 rue Bonaparte"),
                                                  ("2", "Vieux concert", day(-3), "Ailleurs")])}
        with mock.patch("venues.geocode.search", return_value=[]):
            report = scan(self.source, FakeFetcher(feed))
        self.assertIn("1 nouveaux", report)
        event = Event.objects.get(source=self.source)
        self.assertEqual((event.title, event.venue.name, event.venue.commune, event.status),
                         ("Concert de jazz", "Le Comptoir", self.nice, Event.Status.PUBLISHED))
        self.assertEqual(event.description, "")  # seul un extrait est repris
        self.assertTrue(event.summary.startswith("Une belle soirée"))
        self.assertEqual(event.price_kind, Event.Price.UNKNOWN)
        self.assertIn("concert", [c.slug for c in event.categories.all()])
        # Deuxième scan identique : mise à jour, pas de doublon
        with mock.patch("venues.geocode.search", return_value=[]):
            scan(self.source, FakeFetcher(feed))
        self.assertEqual(Event.objects.filter(source=self.source).count(), 1)
        # Disparu du flux : marqué, puis masqué 24 h plus tard
        empty = {"https://exemple.org/a.ics": ics([])}
        scan(self.source, FakeFetcher(empty))
        event.refresh_from_db()
        self.assertIsNotNone(event.missing_since)
        Event.objects.filter(pk=event.pk).update(missing_since=timezone.now() - timedelta(hours=25))
        scan(self.source, FakeFetcher(empty))
        event.refresh_from_db()
        self.assertEqual(event.status, Event.Status.HIDDEN)

    def test_member_event_wins_over_external_copy(self):
        venue = Venue.objects.create(name="Le Comptoir", commune=self.nice, lat=43.7, lon=7.28)
        member = Event.objects.create(title="Concert de Jazz !", summary="x", venue=venue, starts_at=day(3))
        feed = {"https://exemple.org/a.ics": ics([("1", "Concert de jazz", day(3, 21), "Le Comptoir")])}
        with mock.patch("venues.geocode.search", return_value=[]):
            report = scan(self.source, FakeFetcher(feed))
        self.assertIn("1 doublons", report)
        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(Event.objects.get(), member)

    def test_jsonld_list_with_detail_pages(self):
        self.source.kind, self.source.url, self.source.default_commune = "jsonld", "https://ot.example/agenda/", None
        self.source.save()
        detail = {"@context": "https://schema.org", "@type": "MusicEvent", "name": "Fête de la musique au port",
                  "startDate": day(5).isoformat(), "endDate": (day(5) + timedelta(hours=4)).isoformat(),
                  "description": "Scènes ouvertes sur le quai.", "isAccessibleForFree": True,
                  "location": {"@type": "Place", "name": "Port Lympia",
                               "address": {"addressLocality": "Nice", "postalCode": "06300", "streetAddress": "Quai Lunel"}}}
        season = dict(detail, name="Animation de saison", startDate=day(1).isoformat(), endDate=(day(1) + timedelta(days=120)).isoformat())
        far = dict(detail, name="Concert à Marseille", location={"name": "Dôme", "address": {"addressLocality": "Marseille", "postalCode": "13004"}})
        pages = {
            "https://ot.example/agenda/": ld({"@type": "ItemList", "itemListElement": [
                {"@type": "ListItem", "url": "/e/1"}, {"@type": "ListItem", "url": "/e/2"}, {"@type": "ListItem", "url": "/e/3"}]}),
            "https://ot.example/e/1": ld(detail), "https://ot.example/e/2": ld(season), "https://ot.example/e/3": ld(far),
        }
        with mock.patch("venues.geocode.search", return_value=[]):
            report = scan(self.source, FakeFetcher(pages))
        self.assertIn("1 nouveaux", report)
        self.assertIn("1 hors zone", report)
        event = Event.objects.get(source=self.source)
        self.assertEqual((event.title, event.price_kind, event.external_url), ("Fête de la musique au port", "free", "https://ot.example/e/1"))
        self.assertIn("concert", [c.slug for c in event.categories.all()])
        # Page vue récemment : pas retéléchargée au scan suivant
        fetcher = FakeFetcher(pages)
        with mock.patch("venues.geocode.search", return_value=[]):
            scan(self.source, fetcher)
        self.assertNotIn("https://ot.example/e/1", fetcher.requested)

    def test_openagenda(self):
        self.source.kind, self.source.url, self.source.api_key = "openagenda", "https://openagenda.com/agendas/12345678", "k"
        self.source.save()
        payload = {"events": [{"uid": 99, "slug": "atelier-poterie", "title": "Atelier poterie", "description": "Pour les 6-12 ans.",
                               "timings": [{"begin": day(-10).isoformat(), "end": (day(-10) + timedelta(hours=2)).isoformat()},
                                           {"begin": day(4).isoformat(), "end": (day(4) + timedelta(hours=2)).isoformat()}],
                               "location": {"name": "Maison des associations", "city": "Antibes", "postalCode": "06600",
                                            "latitude": 43.58, "longitude": 7.12},
                               "conditions": "Gratuit sur inscription", "age": {"min": 6, "max": 12}}], "after": None}
        fetcher = FakeFetcher({"https://api.openagenda.com/v2/agendas/12345678/events": json.dumps(payload)})
        scan(self.source, fetcher)
        event = Event.objects.get(source=self.source)
        self.assertEqual(event.venue.commune.name, "Antibes")
        self.assertEqual(event.local_start.date(), day(4).date())
        self.assertEqual((event.price_kind, event.age_min, event.age_max), ("free", 6, 12))
        self.assertEqual(event.external_url, "https://openagenda.com/agendas/12345678/events/atelier-poterie")

    def test_external_event_page_and_list(self):
        feed = {"https://exemple.org/a.ics": ics([("1", "Concert de jazz", day(3), "Le Comptoir")])}
        with mock.patch("venues.geocode.search", return_value=[]):
            scan(self.source, FakeFetcher(feed))
        event = Event.objects.get()
        page = self.client.get(event.get_absolute_url())
        self.assertContains(page, 'href="https://exemple.org/e"')
        self.assertNotContains(page, reverse("events:attend", args=[event.slug]))
        self.assertContains(self.client.get(reverse("events:list"), {"source": "externes"}), "via Asso")

    def test_gestion_sources(self):
        root = User.objects.create_superuser("root@example.org", "root@example.org", "pw")
        self.client.force_login(root)
        self.assertEqual(self.client.get(reverse("gestion:sources")).status_code, 200)
        self.client.post(reverse("gestion:source_new"), {"name": "Ville", "kind": "ical", "url": "https://ville.example/a.ics",
                                                         "is_active": "on", "max_pages": 3})
        source = Source.objects.get(name="Ville")
        self.assertTrue(source.scan_requested)
        self.assertEqual(source.slug, "ville")
        response = self.client.post(reverse("gestion:source_new"), {"name": "OA", "kind": "openagenda",
                                    "url": "https://openagenda.com/agendas/1234567", "max_pages": 3})
        self.assertContains(response, "clé d&#x27;API")
