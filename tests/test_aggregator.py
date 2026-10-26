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


class PaginationTests(TestCase):
    def test_next_page_detection(self):
        from aggregator.connectors import next_page

        self.assertEqual(next_page('<link rel="next" href="/agenda/?p=2">', "https://a.example/agenda/", 2), "https://a.example/agenda/?p=2")
        self.assertEqual(next_page('<a href="https://a.example/agenda/page/2/">2</a>', "https://a.example/agenda/", 2),
                         "https://a.example/agenda/page/2/")
        self.assertIsNone(next_page('<a href="/agenda/page/7/">7</a>', "https://a.example/agenda/", 2))


class TitleTests(TestCase):
    def test_trailing_place_and_city_are_removed(self):
        from aggregator.importer import clean_title

        item = {"title": "Concert de piano solo avec Thierry Jam Place de l’Eglise Saorge", "place": "Place de l'Eglise", "city": "Saorge"}
        self.assertEqual(clean_title(item), "Concert de piano solo avec Thierry Jam")
        self.assertEqual(clean_title({"title": "Nice Jazz Festival", "place": "Nice", "city": "Nice"}), "Nice Jazz Festival")


class RequestedScanTests(TestCase):
    def test_flag_is_cleared_after_on_demand_scan(self):
        from django.core.management import call_command

        source = Source.objects.create(name="Asso", slug="asso", kind="ical", url="https://exemple.org/a.ics", scan_requested=True)
        with mock.patch("aggregator.importer.Fetcher", return_value=FakeFetcher({"https://exemple.org/a.ics": ics([])})):
            call_command("worker", run="scan-a-la-demande")
        source.refresh_from_db()
        self.assertFalse(source.scan_requested)
        self.assertIsNotNone(source.last_run_at)


class ConnectorTests(TestCase):
    def test_tribe_keeps_next_occurrence_of_series(self):
        source = Source.objects.create(name="Ville", slug="ville", kind="tribe", url="https://ville.example/",
                                       default_commune=Commune.objects.get(insee="06128"))
        def ev(i, d, url):
            return {"id": i, "url": url, "title": "Yoga au jardin", "excerpt": "<p>Séance douce.</p>",
                    "start_date": f"{d:%Y-%m-%d} 09:00:00", "end_date": f"{d:%Y-%m-%d} 10:00:00", "timezone": "Europe/Paris",
                    "all_day": False, "cost": "Gratuit", "cost_details": {"values": []},
                    "venue": {"venue": "Jardin public", "address": "Place de la Mairie", "city": "Saint-Paul-de-Vence",
                              "zip": "06570", "geo_lat": "43.69", "geo_lng": "7.12"}, "categories": [{"name": "Bien-être"}]}
        d1, d2 = day(3), day(10)
        payload = {"events": [ev(1, d1, f"https://ville.example/agenda/yoga/{d1:%Y-%m-%d}/"),
                              ev(2, d2, f"https://ville.example/agenda/yoga/{d2:%Y-%m-%d}/")], "total_pages": 1}
        fetcher = FakeFetcher({"https://ville.example/wp-json/tribe/events/v1/events": json.dumps(payload)})
        scan(source, fetcher)
        event = Event.objects.get(source=source)
        self.assertEqual(event.local_start.date(), d1.date())
        self.assertEqual((event.price_kind, event.venue.name, event.venue.commune.insee), ("free", "Jardin public", "06128"))
        self.assertEqual(event.external_id, "https://ville.example/agenda/yoga/")

    def test_wpnice(self):
        source = Source.objects.create(name="Nice", slug="nice", kind="wpnice", url="https://ville.example/wp-json/wp/v2/events",
                                       default_commune=Commune.objects.get(insee="06088"))
        d = day(6)
        events = [{"id": 7, "link": "https://ville.example/agenda/concert/", "title": {"rendered": "Concert du conservatoire"},
                   "excerpt": {"rendered": "<p>Élèves et professeurs.</p>"}, "event_types": [261],
                   "acf": {"event_dates": [{"start_date": f"{d:%Y%m%d}", "start_time": "20:00:00", "end_date": None,
                                            "end_time": "", "status": ""}], "place": 12, "free": False, "pricing": "Tarif : 12 €"}},
                  {"id": 8, "link": "https://ville.example/agenda/permanence/", "title": {"rendered": "Permanence"},
                   "excerpt": {"rendered": ""}, "event_types": [295],
                   "acf": {"event_dates": [{"start_date": f"{d:%Y%m%d}", "start_time": "09:00:00"}], "place": 12}}]
        place = {"title": {"rendered": "Auditorium"}, "acf": {"address": {"street_address": "127 avenue de Brancolar",
                 "postal_code": "06100", "city": "Nice"}, "route_links": [{"url": "x?ti=ADDRESS|43.7262,7.2733&tv=y"}]}}
        types = [{"id": 261, "slug": "concert"}, {"id": 295, "slug": "permanence"}]
        fetcher = FakeFetcher({"https://ville.example/wp-json/wp/v2/event_types": json.dumps(types),
                               "https://ville.example/wp-json/wp/v2/events": json.dumps(events),
                               "https://ville.example/wp-json/wp/v2/place/12": json.dumps(place)})
        with mock.patch("django.core.cache.cache.get", return_value=None):
            scan(source, fetcher)
        event = Event.objects.get(source=source)
        self.assertEqual((event.title, event.price_label, event.venue.name), ("Concert du conservatoire", "12 €", "Auditorium"))
        self.assertEqual((round(event.venue.lat, 4), event.local_start.hour), (43.7262, 20))
        self.assertIn("concert", [c.slug for c in event.categories.all()])

    def test_title_filter_default_place_and_online_events(self):
        nice = Commune.objects.get(insee="06088")
        Venue.objects.create(name="Allianz Riviera", commune=nice, address="", lat=43.705, lon=7.1926, precise=True)
        source = Source.objects.create(name="Club", slug="club", kind="ical", url="https://c.example/a.ics", default_commune=nice,
                                       title_pattern=r"^OGC Nice - ", default_place="Allianz Riviera")
        start = day(5)
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0"]
        for uid, title, desc in [("1", "OGC Nice - Lyon", "Ligue 1"), ("2", "Lyon - OGC Nice", "Ligue 1"),
                                 ("3", "OGC Nice - Webinaire tactique", "Online event on Zoom")]:
            lines += ["BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{title}", f"DESCRIPTION:{desc}",
                      f"DTSTART:{start.astimezone(UTC):%Y%m%dT%H%M%SZ}", "END:VEVENT"]
        fetcher = FakeFetcher({"https://c.example/a.ics": "\r\n".join(lines + ["END:VCALENDAR"])})
        scan(source, fetcher)
        event = Event.objects.get(source=source)
        self.assertEqual((event.title, event.venue.name), ("OGC Nice - Lyon", "Allianz Riviera"))

    def test_load_sources_command(self):
        from django.core.management import call_command

        call_command("load_sources", "--scan")
        self.assertTrue(Source.objects.filter(slug="ville-de-nice", kind="wpnice", scan_requested=True).exists())
        self.assertEqual(Source.objects.filter(slug__startswith="meetup-").count(), 17)
        call_command("load_sources")  # idempotente
        self.assertEqual(Source.objects.filter(slug="ogc-nice").count(), 1)
