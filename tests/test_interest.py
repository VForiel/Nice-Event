"""« Ça m'intéresse » / « Pas pour moi », recommandations et page Découvrir."""

from django.urls import reverse

from aggregator.models import Source
from community.models import Attendance, EventInterest
from events import recommend
from events.models import Category, Event

from tests.test_events import Base, soon


class InterestTests(Base):
    def setUp(self):
        super().setUp()
        self.source = Source.objects.create(name="Opéra", slug="opera", kind="ical", url="https://exemple.org/a.ics")
        self.external = self.event(title="Tosca", organizer=None, source=self.source, external_id="1",
                                   external_url="https://exemple.org/tosca", status=Event.Status.PUBLISHED)
        self.client.force_login(self.alice)

    def vote(self, event, value, json=True, **extra):
        headers = {"HTTP_ACCEPT": "application/json"} if json else {}
        return self.client.post(reverse("events:interest", args=[event.slug]), {"value": value, **extra}, **headers)

    def test_toggle_on_external_event(self):
        self.assertEqual(self.vote(self.external, "yes").json(), {"value": 1})
        self.assertEqual(EventInterest.objects.get(user=self.alice).value, 1)
        self.assertEqual(self.vote(self.external, "no").json(), {"value": -1})
        self.assertEqual(self.vote(self.external, "no").json(), {"value": 0})  # recliquer annule
        self.assertFalse(EventInterest.objects.exists())
        self.assertEqual(self.vote(self.external, "yes", keep="1").json(), {"value": 1})
        self.assertEqual(self.vote(self.external, "yes", keep="1").json(), {"value": 1})  # page Découvrir : pas de bascule

    def test_without_javascript_back_to_the_page(self):
        response = self.vote(self.external, "yes", json=False, next="/evenements/?page=2")
        self.assertRedirects(response, "/evenements/?page=2", fetch_redirect_response=False)
        response = self.vote(self.external, "no", json=False, next="https://ailleurs.example/")
        self.assertRedirects(response, self.external.get_absolute_url(), fetch_redirect_response=False)

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        response = self.vote(self.external, "yes", json=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("community:login"), response["Location"])
        self.assertContains(self.client.get(self.external.get_absolute_url()), "Ça m'intéresse")

    def test_buttons_on_cards_and_detail_and_profile(self):
        self.vote(self.external, "yes")
        page = self.client.get(self.external.get_absolute_url())
        self.assertContains(page, 'class="interest interest-big"')
        self.assertContains(page, 'aria-pressed="true"')
        self.assertContains(self.client.get(reverse("events:list")), "data-interest")
        profile = self.client.get(self.alice.profile.get_absolute_url())
        self.assertContains(profile, "Ça l'intéresse")
        self.assertContains(profile, "Tosca")
        self.alice.profile.show_events = False
        self.alice.profile.save()
        bob = self.member("bob@example.org", "Bob")
        self.client.force_login(bob)
        self.assertNotContains(self.client.get(self.alice.profile.get_absolute_url()), "Tosca")


class RecommendTests(Base):
    def setUp(self):
        super().setUp()
        self.theatre = Category.objects.get(slug="spectacle")
        self.jazz = [self.event(title=f"Soirée jazz manouche {i}", starts_at=soon(i + 1)) for i in range(4)]
        self.plays = [self.event(title=f"Théâtre classique {i}", categories=[self.theatre], starts_at=soon(i + 1)) for i in range(4)]
        self.bob = self.member("bob@example.org", "Bob")

    def test_liked_category_and_words_come_first(self):
        EventInterest.objects.create(user=self.bob, event=self.jazz[0], value=1)
        Attendance.objects.create(user=self.bob, event=self.jazz[1])  # « J'y vais » compte comme un intérêt
        EventInterest.objects.create(user=self.bob, event=self.plays[0], value=-1)
        picks = recommend.recommend(self.bob, limit=4, per_category=4)
        self.assertEqual([e.pk for e in picks[:2]], [self.jazz[2].pk, self.jazz[3].pk])
        self.assertNotIn(self.jazz[0], picks)  # déjà noté
        self.assertNotIn(self.plays[0], picks)

    def test_home_section_needs_a_few_signals(self):
        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get(reverse("core:home")), "Recommandé pour toi")
        for event in self.jazz[:3]:
            EventInterest.objects.create(user=self.bob, event=event, value=1)
        page = self.client.get(reverse("core:home"))
        self.assertContains(page, "Recommandé pour toi")
        self.assertEqual(page.context["recommended"][0], self.jazz[3])

    def test_discover_page_and_feed(self):
        self.assertEqual(self.client.get(reverse("events:discover")).status_code, 302)  # connexion demandée
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(reverse("events:discover")), "data-discover")
        feed = self.client.get(reverse("events:discover_next")).json()["events"]
        self.assertTrue(feed)
        self.assertTrue({"title", "url", "interest", "when", "place", "price"} <= set(feed[0]))
        seen = ",".join(str(e.pk) for e in self.jazz + self.plays[:3])
        feed = self.client.get(reverse("events:discover_next") + "?vus=" + seen).json()["events"]
        self.assertEqual([e["id"] for e in feed], [self.plays[3].pk])
