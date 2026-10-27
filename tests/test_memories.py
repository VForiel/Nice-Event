import io
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from community.models import Attendance, Comment, Friendship, Media, Report
from core.embeds import parse

from .test_events import Base

MEDIA = tempfile.mkdtemp()


def jpeg(name="photo.jpg"):
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "#1f6fd1").save(buf, "JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


def mp4(name="clip.mp4"):
    return SimpleUploadedFile(name, b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2000, content_type="video/mp4")


class EmbedTests(Base):
    def test_players_and_platforms(self):
        self.assertEqual(parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3").player,
                         "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")
        self.assertEqual(parse("https://youtu.be/dQw4w9WgXcQ").player, "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")
        self.assertEqual(parse("https://vimeo.com/76979871").player, "https://player.vimeo.com/video/76979871?dnt=1")
        self.assertEqual(parse("https://www.dailymotion.com/video/x8abcd1").player,
                         "https://geo.dailymotion.com/player.html?video=x8abcd1")
        self.assertEqual(parse("https://photos.app.goo.gl/abc").provider, "Google Photos")
        self.assertEqual(parse("https://fr.pinterest.com/pin/123/").provider, "Pinterest")
        self.assertEqual(parse("https://pin.it/abc").provider, "Pinterest")
        self.assertEqual(parse("https://exemple.org/album").provider, "exemple.org")
        self.assertIsNone(parse("javascript:alert(1)"))
        self.assertIsNone(parse("http://exemple.org"))


@override_settings(MEDIA_ROOT=MEDIA)
class CommentTests(Base):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def test_comment_without_rating_before_event(self):
        event = self.event()
        self.client.force_login(self.alice)
        self.client.post(reverse("community:comment_new", args=[event.slug]), {"body": "Qui vient ?", "rating": "5"})
        comment = Comment.objects.get()
        self.assertEqual(comment.body, "Qui vient ?")
        self.assertIsNone(comment.rating)  # pas de note avant le début
        response = self.client.get(event.get_absolute_url())
        self.assertContains(response, "Qui vient ?")
        self.assertNotContains(response, "rate-stars")

    def test_only_latest_rating_counts(self):
        event = self.event(starts_at=timezone.now() - timedelta(days=2))
        bob = self.member("bob@example.org", "Bob")
        self.client.force_login(self.alice)
        url = reverse("community:comment_new", args=[event.slug])
        self.client.post(url, {"rating": "2"})
        self.client.post(url, {"body": "Finalement super", "rating": "4"})
        self.client.force_login(bob)
        self.client.post(url, {"rating": "5"})
        self.assertEqual(Comment.objects.filter(rating__isnull=False).count(), 2)
        self.assertEqual(Comment.objects.filter(author=self.alice).count(), 1)  # note seule remplacée
        response = self.client.get(event.get_absolute_url())
        self.assertEqual(response.context["rating_average"], 4.5)
        self.assertEqual(response.context["rating_count"], 2)

    def test_empty_comment_refused_and_delete_rights(self):
        event = self.event()
        self.client.force_login(self.alice)
        self.client.post(reverse("community:comment_new", args=[event.slug]), {"body": "  "})
        self.assertFalse(Comment.objects.exists())
        comment = Comment.objects.create(event=event, author=self.alice, body="Salut")
        bob = self.member("bob@example.org", "Bob")
        self.client.force_login(bob)
        self.assertEqual(self.client.post(reverse("community:comment_delete", args=[comment.pk])).status_code, 404)
        self.client.force_login(self.staff)
        self.client.post(reverse("community:comment_delete", args=[comment.pk]))
        self.assertFalse(Comment.objects.exists())

    def test_three_reports_hide_comment(self):
        event = self.event()
        comment = Comment.objects.create(event=event, author=self.alice, body="Pub")
        for i in range(3):
            self.client.force_login(self.member(f"r{i}@example.org", f"R{i}"))
            self.client.post(reverse("community:report", args=["commentaire", comment.pk]), {"reason": "spam"})
        comment.refresh_from_db()
        self.assertTrue(comment.is_hidden)
        self.assertEqual(Report.objects.filter(comment=comment).count(), 3)
        self.assertNotContains(self.client.get(event.get_absolute_url()), "Pub</p>")


@override_settings(MEDIA_ROOT=MEDIA)
class MediaTests(Base):
    def test_several_files_and_links(self):
        event = self.event()
        self.client.force_login(self.alice)
        response = self.client.post(reverse("community:media_new", args=[event.slug]), {
            "files": [jpeg("a.jpg"), jpeg("b.jpg"), mp4()],
            "links": "https://youtu.be/dQw4w9WgXcQ\nphotos.app.goo.gl/abc",
            "caption": "Super soirée", "consent": "on",
        })
        self.assertRedirects(response, event.get_absolute_url() + "#souvenirs", fetch_redirect_response=False)
        self.assertEqual(Media.objects.filter(kind="photo").count(), 2)
        self.assertTrue(Media.objects.filter(kind="photo").first().image.name.endswith(".webp"))
        self.assertEqual(Media.objects.filter(kind="video").count(), 1)
        self.assertEqual(sorted(Media.objects.filter(kind="lien").values_list("url", flat=True)),
                         ["https://photos.app.goo.gl/abc", "https://youtu.be/dQw4w9WgXcQ"])
        page = self.client.get(event.get_absolute_url())
        self.assertContains(page, 'data-embed="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"')
        self.assertContains(page, "Google Photos")
        self.assertContains(page, "<video")
        self.assertIn("youtube-nocookie.com", page["Content-Security-Policy"])

    def test_bad_files_are_explained(self):
        event = self.event()
        self.client.force_login(self.alice)
        response = self.client.post(reverse("community:media_new", args=[event.slug]), {
            "files": [SimpleUploadedFile("x.heic", b"pas une image"), SimpleUploadedFile("v.avi", b"RIFF....")],
            "consent": "on",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Google Photos")
        self.assertContains(response, "MP4, MOV ou WebM")
        self.assertFalse(Media.objects.exists())

    def test_consent_required_and_anonymous_redirected(self):
        event = self.event()
        url = reverse("community:media_new", args=[event.slug])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.alice)
        self.client.post(url, {"links": "https://youtu.be/dQw4w9WgXcQ"})
        self.assertFalse(Media.objects.exists())

    def test_video_byte_ranges(self):
        event = self.event()
        item = Media.objects.create(event=event, uploader=self.alice, kind="video", video=mp4())
        response = self.client.get(item.video.url, HTTP_RANGE="bytes=0-9")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], f"bytes 0-9/{item.video.size}")
        self.assertEqual(len(b"".join(response.streaming_content)), 10)
        self.assertEqual(self.client.get(item.video.url).status_code, 200)


class PastEventsTests(Base):
    def test_past_events_visibility(self):
        past = self.event(title="Concert passé", starts_at=timezone.now() - timedelta(days=5))
        bob = self.member("bob@example.org", "Bob")
        Attendance.objects.create(event=past, user=bob)
        url = bob.profile.get_absolute_url()
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(url), "Concert passé")
        bob.profile.past_events = "amis"
        bob.profile.save()
        self.assertNotContains(self.client.get(url), "Concert passé")
        Friendship.objects.create(from_user=self.alice, to_user=bob, accepted=True)
        self.assertContains(self.client.get(url), "Concert passé")
        bob.profile.past_events = "moi"
        bob.profile.save()
        self.assertNotContains(self.client.get(url), "Concert passé")
        self.client.force_login(bob)
        self.assertContains(self.client.get(url), "Concert passé")
