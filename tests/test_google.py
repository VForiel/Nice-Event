"""Connexion avec Google : rapprochement des comptes, création, contrôles du jeton."""

import base64
import io
import json
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from community import google
from community.models import GoogleAccount
from siteconfig.models import SiteConfig


def id_token(**claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{payload}.signature"


class GoogleTests(TestCase):
    def setUp(self):
        translation.activate("fr")
        cache.clear()
        SiteConfig.objects.update_or_create(pk=1, defaults={"google_client_id": "client.apps.googleusercontent.com",
                                                            "google_client_secret": "secret"})
        cache.clear()

    def go(self, email="lea@gmail.com", sub="1234", verified=True, tamper=None):
        start = self.client.get(reverse("community:google_start") + "?next=/evenements/")
        query = parse_qs(urlparse(start["Location"]).query)
        claims = {"iss": "https://accounts.google.com", "aud": "client.apps.googleusercontent.com",
                  "exp": time.time() + 600, "nonce": query["nonce"][0], "sub": sub, "email": email,
                  "email_verified": verified, "name": "Léa Martin"}
        claims.update(tamper or {})
        answer = io.BytesIO(json.dumps({"id_token": id_token(**claims)}).encode())
        with mock.patch("urllib.request.urlopen", return_value=answer) as call:
            response = self.client.get(reverse("community:google_callback"), {"state": query["state"][0], "code": "abc"})
        return response, call

    def test_new_account_is_created_confirmed(self):
        response, call = self.go()
        self.assertEqual(call.call_args.args[0].full_url, google.TOKEN)
        user = User.objects.get(email="lea@gmail.com")
        self.assertTrue(user.is_active and user.profile.email_confirmed and user.has_usable_password())
        self.assertEqual(user.profile.display_name, "Léa Martin")
        self.assertRedirects(response, "/evenements/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_existing_confirmed_account_then_google_id(self):
        user = User.objects.create_user("lea@gmail.com", "Lea@gmail.com", "pw")  # confirmée par défaut
        self.go()
        self.assertTrue(GoogleAccount.objects.filter(user=user, sub="1234").exists())
        self.client.logout()
        self.go(email="autre@gmail.com")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertEqual(User.objects.count(), 1)

    def test_unconfirmed_account_is_not_taken_over(self):
        user = User.objects.create_user("lea@gmail.com", "lea@gmail.com", "pw")
        user.profile.email_confirmed = False
        user.profile.save()
        response, _call = self.go()
        self.assertRedirects(response, reverse("community:login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_checks_on_the_token(self):
        for tamper in ({"aud": "autre"}, {"nonce": "x"}, {"exp": time.time() - 5}, {"iss": "https://evil.example"}):
            self.go(tamper=tamper)
            self.assertNotIn("_auth_user_id", self.client.session, tamper)
        self.go(verified=False)
        self.assertFalse(User.objects.exists())

    def test_forged_state_and_unconfigured(self):
        self.client.get(reverse("community:google_start"))
        response = self.client.get(reverse("community:google_callback"), {"state": "faux", "code": "abc"})
        self.assertRedirects(response, reverse("community:login"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("community:login")), "Continuer avec Google")
        SiteConfig.objects.update(google_client_secret="")
        cache.clear()
        self.assertNotContains(self.client.get(reverse("community:login")), "Continuer avec Google")
        self.assertEqual(self.client.get(reverse("community:google_start")).status_code, 404)
