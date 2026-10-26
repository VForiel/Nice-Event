import io
import shutil
import tempfile
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from events.models import Category, Event
from siteconfig.models import SiteConfig
from social import networks
from social.models import LIMIT, Post
from social.texts import default_text, length
from social.visuals import FORMATS, render, visual_path
from venues.models import Commune, Venue

User = get_user_model()
MEDIA = tempfile.mkdtemp()


def jpeg(size=(1600, 1000), color=(61, 127, 192)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return ContentFile(buf.getvalue(), "photo.jpg")


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.content, self.text = data, status, b"x", str(data)

    def json(self):
        return self.data


@override_settings(MEDIA_ROOT=MEDIA)
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        nice = Commune.objects.get(insee="06088")
        venue = Venue.objects.create(name="Théâtre de Verdure", address="Jardin Albert Ier", commune=nice, lat=43.69, lon=7.27)
        self.event = Event.objects.create(
            title="Un très long titre de concert de jazz manouche sous les étoiles de la Baie des Anges",
            summary="Trois musiciens, une scène en plein air et la mer en fond : une soirée à ne pas manquer cet été.",
            venue=venue, starts_at=timezone.now() + timedelta(days=4), language="international")
        self.event.categories.set([Category.objects.get(slug="concert")])
        self.staff = User.objects.create_user("staff@example.org", "staff@example.org", "pw", is_staff=True)


class VisualTests(Base):
    def test_all_formats_with_and_without_photo(self):
        for fmt, size in FORMATS.items():
            with self.subTest(fmt=fmt, photo=False):
                self.assertEqual(render(self.event, fmt).size, size)
        self.event.photo.save("p.jpg", jpeg(), save=True)
        for fmt, size in FORMATS.items():
            with self.subTest(fmt=fmt, photo=True):
                self.assertEqual(render(self.event, fmt).size, size)

    def test_cache_is_refreshed_when_event_changes(self):
        first = visual_path(self.event, "og")
        self.assertTrue(first.exists())
        self.assertEqual(visual_path(self.event, "og"), first)
        self.event.title = "Nouveau titre"
        self.event.save()
        second = visual_path(self.event, "og")
        self.assertNotEqual(first, second)
        self.assertFalse(first.exists())

    def test_public_visual_url(self):
        response = self.client.get(reverse("events:visual", args=[self.event.slug, "story"]) + "?telecharger=1")
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(self.client.get(reverse("events:visual", args=[self.event.slug, "autre"])).status_code, 404)
        self.event.status = Event.Status.PENDING
        self.event.save()
        self.assertEqual(self.client.get(reverse("events:visual", args=[self.event.slug, "og"])).status_code, 404)


class TextTests(Base):
    def test_texts_fit_network_limits(self):
        for network, limit in LIMIT.items():
            with self.subTest(network=network):
                text = default_text(self.event, network, "#Nice #CoteDAzur #NiceEvent #Jazz")
                self.assertLessEqual(length(network, text), limit)
                self.assertIn("Théâtre de Verdure", text)
        self.assertIn("lien en bio", default_text(self.event, "instagram"))
        self.assertIn("http", default_text(self.event, "x"))

    def test_x_counts_links_as_23(self):
        self.assertEqual(length("x", "a https://nice-event.fr/evenements/un-tres-long-slug-qui-depasse/"), 25)

    def test_bluesky_facets_use_utf8_offsets(self):
        text = "Fête ! https://nice-event.fr/e/ ok"
        facet = networks.link_facets(text)[0]
        start = facet["index"]["byteStart"]
        self.assertEqual(text.encode()[start:facet["index"]["byteEnd"]].decode(), "https://nice-event.fr/e/")

    def test_oauth1_signature_matches_reference(self):
        # Exemple de la documentation de X (« Creating a signature »)
        config = SimpleNamespace(x_api_key="xvz1evFS4wEEPTGEFPHBog", x_api_secret="kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
                                 x_access_token="370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
                                 x_access_secret="LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE")
        with mock.patch("social.networks.secrets.token_hex", return_value="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg"), \
             mock.patch("social.networks.time.time", return_value=1318622958):
            header = networks.oauth1_header("POST", "https://api.twitter.com/1.1/statuses/update.json", config,
                                             {"include_entities": "true", "status": "Hello Ladies + Gentlemen, a signed OAuth request!"})
        self.assertIn('oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"', header)


class DiffusionTests(Base):
    def configure_bluesky(self):
        config = SiteConfig.get()
        config.bluesky_enabled, config.bluesky_handle, config.bluesky_app_password = True, "nice-event.bsky.social", "app-pw"
        config.save()

    def bluesky_calls(self):
        def post(url, **kwargs):
            if url.endswith("createSession"):
                return FakeResponse({"accessJwt": "jwt", "did": "did:plc:abc", "handle": "nice-event.bsky.social"})
            if url.endswith("uploadBlob"):
                self.assertLessEqual(len(kwargs["data"]), 950_000)
                return FakeResponse({"blob": {"ref": "blob"}})
            record = kwargs["json"]["record"]
            self.assertTrue(record["facets"])
            self.assertEqual(record["embed"]["$type"], "app.bsky.embed.images")
            return FakeResponse({"uri": "at://did:plc:abc/app.bsky.feed.post/3kxyz"})
        return post

    def test_publish_now_on_bluesky(self):
        self.configure_bluesky()
        self.client.force_login(self.staff)
        page = self.client.get(reverse("gestion:diffuse", args=[self.event.pk]))
        self.assertContains(page, "Bluesky")
        text = page.context["form"].initial.get("text_bluesky") or page.context["form"]["text_bluesky"].initial
        with mock.patch("social.networks.requests.post", side_effect=self.bluesky_calls()):
            self.client.post(reverse("gestion:diffuse", args=[self.event.pk]),
                             {"on_bluesky": "on", "text_bluesky": text, "when": "now"})
        post = Post.objects.get()
        self.assertEqual(post.status, Post.Status.PUBLISHED, post.error)
        self.assertEqual(post.external_url, "https://bsky.app/profile/nice-event.bsky.social/post/3kxyz")

    def test_unconfigured_network_is_refused(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("gestion:diffuse", args=[self.event.pk]),
                                    {"on_x": "on", "text_x": "Salut", "when": "now"})
        self.assertContains(response, "Choisis au moins un réseau")
        self.assertFalse(Post.objects.exists())

    def test_scheduled_post_is_sent_by_worker(self):
        self.configure_bluesky()
        self.client.force_login(self.staff)
        at = timezone.localtime() + timedelta(hours=2)
        self.client.post(reverse("gestion:diffuse", args=[self.event.pk]), {
            "on_bluesky": "on", "text_bluesky": "Concert ! https://nice-event.fr/", "when": "later",
            "scheduled_at": at.strftime("%Y-%m-%dT%H:%M")})
        post = Post.objects.get()
        self.assertEqual(post.status, Post.Status.SCHEDULED)
        with mock.patch("social.networks.requests.post", side_effect=self.bluesky_calls()):
            call_command("worker", run="publications")
            post.refresh_from_db()
            self.assertEqual(post.status, Post.Status.SCHEDULED)  # pas encore l'heure
            Post.objects.update(scheduled_at=timezone.now() - timedelta(minutes=1))
            call_command("worker", run="publications")
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.PUBLISHED)

    def test_api_error_is_recorded(self):
        self.configure_bluesky()
        post = Post.objects.create(event=self.event, network="bluesky", text="Coucou")
        bad = FakeResponse({"error": "AuthFactorTokenRequired", "message": "Mot de passe refusé"}, status=401)
        with mock.patch("social.networks.requests.post", return_value=bad):
            call_command("worker", run="publications")
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.FAILED)
        self.assertIn("Mot de passe refusé", post.error)

    def test_settings_keep_social_secrets(self):
        superuser = User.objects.create_superuser("root@example.org", "root@example.org", "pw")
        self.client.force_login(superuser)
        self.configure_bluesky()
        page = self.client.get(reverse("gestion:settings")).content.decode()
        self.assertNotIn("app-pw", page)
