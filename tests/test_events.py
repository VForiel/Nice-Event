from datetime import datetime, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from community.models import Attendance, Friendship, Notification, Report
from events.models import Category, Event
from events.views import window
from siteconfig.models import SiteConfig
from venues.models import Commune, Venue

User = get_user_model()


def soon(days=3, hour=20):
    return timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=days), time(hour, 0)))


class Base(TestCase):
    def setUp(self):
        self.nice = Commune.objects.get(insee="06088")
        self.antibes = Commune.objects.get(insee="06004")
        self.venue = Venue.objects.create(name="Le Comptoir", address="12 rue Bonaparte", commune=self.nice, lat=43.70, lon=7.28)
        self.concert = Category.objects.get(slug="concert")
        self.alice = self.member("alice@example.org", "Alice")
        self.staff = User.objects.create_user("staff@example.org", "staff@example.org", "pw", is_staff=True)

    def member(self, email, name, confirmed=True, trusted=False):
        user = User.objects.create_user(email, email, "pw-Solide-123")
        user.profile.display_name, user.profile.email_confirmed, user.profile.trusted = name, confirmed, trusted
        user.profile.handle = ""
        user.profile.save()
        return user

    def event(self, **kw):
        cats = kw.pop("categories", [self.concert])
        data = {"title": "Concert", "summary": "Du jazz", "venue": self.venue, "starts_at": soon(), "organizer": self.alice}
        data.update(kw)
        e = Event.objects.create(**data)
        e.categories.set(cats)
        return e

    def form_data(self, **kw):
        data = {
            "title": "Apéro jazz", "categories": [self.concert.pk], "summary": "Un trio jazz face à la mer",
            "description": "", "date": (timezone.localdate() + timedelta(days=5)).isoformat(), "start_time": "19:30",
            "end_time": "22:00", "venue_name": "Plage du Castel", "address": "Quai des États-Unis", "commune": self.nice.pk,
            "lat": "43.6935", "lon": "7.283", "accessible": "", "price_kind": "free", "age_kind": "all", "language": "international",
            "spoken_list": ["fr", "en"], "organizer_name": "",
        }
        data.update(kw)
        return data


class PublishTests(Base):
    def test_unconfirmed_member_cannot_publish(self):
        bob = self.member("bob@example.org", "Bob", confirmed=False)
        self.client.force_login(bob)
        response = self.client.get(reverse("events:new"))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Confirme ton adresse", status_code=403)

    def test_first_event_is_moderated_then_trusted(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("events:new"), self.form_data())
        event = Event.objects.get(title="Apéro jazz")
        self.assertRedirects(response, reverse("events:published", args=[event.slug]))
        self.assertEqual(event.status, Event.Status.PENDING)
        self.assertEqual((event.venue.lat, event.venue.lon), (43.6935, 7.283))
        self.assertTrue(event.english_friendly)
        self.assertTrue(Notification.objects.filter(recipient=self.staff, verb="to_moderate").exists())
        # Invisible du public tant qu'il n'est pas validé
        self.client.logout()
        self.assertEqual(self.client.get(event.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get(reverse("events:list")), "Apéro jazz")
        # Validation par l'équipe : publié, auteur prévenu (courriel) et désormais de confiance
        self.client.force_login(self.staff)
        self.client.post(reverse("gestion:moderate", args=[event.pk]), {"decision": "approve"})
        event.refresh_from_db()
        self.assertEqual(event.status, Event.Status.PUBLISHED)
        self.alice.profile.refresh_from_db()
        self.assertTrue(self.alice.profile.trusted)
        self.assertEqual(mail.outbox[-1].to, ["alice@example.org"])
        # Le suivant est publié directement
        self.client.force_login(self.alice)
        self.client.post(reverse("events:new"), self.form_data(title="Deuxième"))
        self.assertEqual(Event.objects.get(title="Deuxième").status, Event.Status.PUBLISHED)

    def test_reject_notifies_author(self):
        event = self.event(status=Event.Status.PENDING)
        self.client.force_login(self.staff)
        self.client.post(reverse("gestion:moderate", args=[event.pk]), {"decision": "reject", "note": "Doublon"})
        event.refresh_from_db()
        self.assertEqual((event.status, event.moderation_note), (Event.Status.HIDDEN, "Doublon"))
        self.assertIn("Doublon", mail.outbox[-1].body)

    def test_weekly_repeat_creates_series(self):
        self.alice.profile.trusted = True
        self.alice.profile.save()
        self.client.force_login(self.alice)
        start = timezone.localdate() + timedelta(days=2)
        self.client.post(reverse("events:new"), self.form_data(
            date=start.isoformat(), repeat="week", repeat_until=(start + timedelta(weeks=3)).isoformat()))
        series = Event.objects.filter(title="Apéro jazz").order_by("starts_at")
        self.assertEqual(series.count(), 4)
        self.assertEqual(len({e.series for e in series}), 1)
        self.assertEqual(series[3].local_start.date(), start + timedelta(weeks=3))
        self.assertEqual(list(series[3].categories.all()), [self.concert])

    def test_validation(self):
        self.client.force_login(self.alice)
        past = (timezone.localdate() - timedelta(days=1)).isoformat()
        response = self.client.post(reverse("events:new"), self.form_data(
            date=past, categories=[c.pk for c in Category.objects.all()[:4]], price_kind="paid", age_kind="range", age_min="30", age_max="20"))
        form = response.context["form"]
        for field in ("date", "categories", "price_min", "age_max"):
            self.assertIn(field, form.errors)
        self.assertFalse(Event.objects.exists())

    def test_night_event_ends_next_day(self):
        self.alice.profile.trusted = True
        self.alice.profile.save()
        self.client.force_login(self.alice)
        self.client.post(reverse("events:new"), self.form_data(start_time="23:00", end_time="04:00"))
        event = Event.objects.get()
        self.assertEqual(event.local_end.date(), event.local_start.date() + timedelta(days=1))

    def test_new_venue_is_geocoded_when_no_position(self):
        self.alice.profile.trusted = True
        self.alice.profile.save()
        self.client.force_login(self.alice)
        with mock.patch("venues.geocode.search", return_value=[{"lat": 43.58, "lon": 7.12, "score": 0.9}]) as search:
            self.client.post(reverse("events:new"), self.form_data(venue_name="Pinède", address="Bd Baudoin", commune=self.antibes.pk, lat="", lon=""))
        search.assert_called_once()
        venue = Event.objects.get().venue
        self.assertEqual((venue.lat, venue.lon, venue.precise), (43.58, 7.12, True))

    def test_edit_notifies_attendees_on_cancel(self):
        event = self.event()
        bob = self.member("bob@example.org", "Bob")
        Attendance.objects.create(event=event, user=bob)
        self.client.force_login(self.alice)
        data = self.form_data(title=event.title, state="cancelled")
        self.client.post(reverse("events:edit", args=[event.slug]), data)
        event.refresh_from_db()
        self.assertEqual(event.state, Event.State.CANCELLED)
        self.assertTrue(Notification.objects.filter(recipient=bob, verb="changed", message="annulé").exists())

    def test_only_owner_or_staff_can_edit(self):
        event = self.event()
        self.client.force_login(self.member("eve@example.org", "Eve"))
        self.assertEqual(self.client.get(reverse("events:edit", args=[event.slug])).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("events:edit", args=[event.slug])).status_code, 200)


class ListTests(Base):
    def test_filters(self):
        free = self.event(title="Gratuit à Nice")
        paid = self.event(title="Payant à Antibes", price_kind="paid", price_min=12,
                          venue=Venue.objects.create(name="Pinède", commune=self.antibes), language="international")
        other = self.event(title="Expo lointaine", starts_at=soon(days=40), categories=[Category.objects.get(slug="expo")])
        url = reverse("events:list")
        page = self.client.get(url).content.decode()
        self.assertIn(free.title, page)
        self.assertIn(other.title, page)
        page = self.client.get(url, {"gratuit": "1", "quand": "semaine"}).content.decode()
        self.assertIn(free.title, page)
        self.assertNotIn(paid.title, page)
        self.assertNotIn(other.title, page)
        self.assertNotIn(free.title, self.client.get(url, {"zone": "nice", "en": "1"}).content.decode())
        self.assertIn(paid.title, self.client.get(url, {"en": "1"}).content.decode())
        self.assertIn(other.title, self.client.get(url, {"categorie": "expo"}).content.decode())
        self.assertIn(paid.title, self.client.get(url, {"q": "antibes"}).content.decode())
        self.assertNotIn(free.title, self.client.get(url, {"q": "antibes"}).content.decode())

    def test_weekend_window(self):
        monday = timezone.make_aware(datetime(2026, 11, 2, 10))
        start, end = window("weekend", monday)
        self.assertEqual(timezone.localtime(start), timezone.make_aware(datetime(2026, 11, 6, 18)))
        self.assertEqual(timezone.localtime(end).date(), datetime(2026, 11, 9).date())
        saturday = timezone.make_aware(datetime(2026, 11, 7, 15))
        start, _end = window("weekend", saturday)
        self.assertEqual(start, saturday)

    def test_past_and_hidden_events_are_not_listed(self):
        self.event(title="Passé", starts_at=timezone.now() - timedelta(days=2))
        self.event(title="Masqué", status=Event.Status.HIDDEN)
        page = self.client.get(reverse("events:list")).content.decode()
        self.assertNotIn("Passé", page)
        self.assertNotIn("Masqué", page)

    def test_map_data_and_ical(self):
        event = self.event(title="Sur la carte")
        data = self.client.get(reverse("events:map_data")).json()["events"]
        self.assertEqual(data[0]["title"], "Sur la carte")
        self.assertEqual(data[0]["emoji"], "🎵")
        self.assertEqual((data[0]["lat"], data[0]["lon"]), (43.7, 7.28))
        ics = self.client.get(reverse("events:agenda")).content.decode()
        self.assertIn("SUMMARY:Sur la carte", ics)
        self.assertIn(f"UID:event-{event.pk}@nice-event.fr", ics)
        self.assertEqual(self.client.get(reverse("events:ics", args=[event.slug])).status_code, 200)

    def test_detail_has_jsonld_and_share_links(self):
        event = self.event(title="Partage-moi")
        page = self.client.get(event.get_absolute_url()).content.decode()
        self.assertIn('"@type": "Event"', page)
        self.assertIn("https://wa.me/?text=", page)
        self.assertIn("https://bsky.app/intent/compose", page)
        self.assertEqual(Event.objects.get(pk=event.pk).views, 1)

    def test_pages_render(self):
        event = self.event()
        for url in [reverse("core:home"), reverse("events:map"), event.venue.get_absolute_url(), "/en/events/",
                    reverse("core:charter"), "/en/terms/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_price_label(self):
        self.assertEqual(str(self.event(price_kind="paid", price_min=18).price_label), "18 €")
        self.assertEqual(str(self.event(price_kind="paid", price_min=7.5, price_max=12).price_label), "7,50–12 €")


class CommunityTests(Base):
    def test_signup_sends_confirmation_and_confirm_link_works(self):
        response = self.client.post(reverse("community:signup"), {
            "display_name": "Chloé Martin", "email": "Chloe@Example.org", "password": "pw-Solide-123", "consent": "on"})
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="chloe@example.org")
        self.assertFalse(user.profile.email_confirmed)
        link = [line for line in mail.outbox[0].body.splitlines() if "/compte/confirmer/" in line][0]
        self.client.get(link.replace("http://localhost:8000", ""))
        user.profile.refresh_from_db()
        self.assertTrue(user.profile.email_confirmed)
        self.assertEqual(user.profile.handle, "chloe-martin")

    def test_confirmation_can_be_disabled(self):
        config = SiteConfig.get()
        config.require_email_confirmation = False
        config.save()
        self.client.post(reverse("community:signup"), {
            "display_name": "Dan", "email": "dan@example.org", "password": "pw-Solide-123", "consent": "on"})
        self.assertEqual(self.client.get(reverse("events:new")).status_code, 200)

    def test_attend_and_invite_friend(self):
        event = self.event()
        bob = self.member("bob@example.org", "Bob")
        Friendship.objects.create(from_user=self.alice, to_user=bob, accepted=True)
        self.client.force_login(bob)
        self.client.post(reverse("events:attend", args=[event.slug]))
        self.assertTrue(Attendance.objects.filter(event=event, user=bob).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.alice, verb="attending").exists())
        self.client.force_login(self.alice)
        page = self.client.get(reverse("events:list")).content.decode()
        self.assertIn("1 ami y va", page)
        carol = self.member("carol@example.org", "Carol")
        Friendship.objects.create(from_user=carol, to_user=self.alice, accepted=True)
        self.client.post(reverse("events:invite", args=[event.slug]), {"friends": [carol.pk, bob.pk + 1000]})
        self.assertTrue(Notification.objects.filter(recipient=carol, verb="invite", event=event).exists())
        self.assertIn("t'invite", mail.outbox[-1].subject)

    def test_full_event(self):
        event = self.event(capacity=1)
        Attendance.objects.create(event=event, user=self.alice)
        bob = self.member("bob@example.org", "Bob")
        self.client.force_login(bob)
        self.client.post(reverse("events:attend", args=[event.slug]))
        self.assertFalse(Attendance.objects.filter(user=bob).exists())

    def test_three_reports_hide_event(self):
        event = self.event()
        for i in range(3):
            self.client.force_login(self.member(f"r{i}@example.org", f"R{i}"))
            self.client.post(reverse("community:report", args=["evenement", event.slug]), {"reason": "Arnaque"})
        event.refresh_from_db()
        self.assertEqual(event.status, Event.Status.HIDDEN)
        self.assertEqual(Report.objects.count(), 3)

    def test_friend_flow_and_profile(self):
        bob = self.member("bob@example.org", "Bob")
        self.client.force_login(self.alice)
        self.client.post(reverse("community:friend", args=[bob.profile.handle, "add"]))
        self.client.force_login(bob)
        self.client.post(reverse("community:friend", args=[self.alice.profile.handle, "accept"]))
        self.assertTrue(Friendship.objects.get().accepted)
        self.assertContains(self.client.get(self.alice.profile.get_absolute_url()), "Alice")
        self.client.logout()
        self.assertEqual(self.client.get(self.alice.profile.get_absolute_url()).status_code, 403)

    def test_member_pages(self):
        self.client.force_login(self.alice)
        for name in ("community:settings", "community:members", "community:friends", "community:notifications"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.client.post(reverse("community:settings"), {"save_profile": "1", "p-display_name": "Alice B.",
                         "p-accent": "corail", "p-visibility": "public", "p-contact_visibility": "amis",
                         "p-interests": [self.concert.pk], "p-spoken_list": ["fr", "it"]})
        self.alice.profile.refresh_from_db()
        self.assertEqual((self.alice.profile.display_name, self.alice.profile.spoken), ("Alice B.", "fr,it"))
        self.assertEqual(list(self.alice.profile.interests.all()), [self.concert])

    def test_gestion_pages(self):
        self.event(status=Event.Status.PENDING)
        self.client.force_login(self.staff)
        for name in ("gestion:dashboard", "gestion:moderation", "gestion:events", "gestion:reports", "gestion:members"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("gestion:moderation")).status_code, 302)
