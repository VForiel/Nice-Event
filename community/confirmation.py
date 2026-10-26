"""Confirmation de l'adresse électronique.

Le compte est utilisable dès l'inscription (« J'y vais », amis…), mais publier un événement demande d'avoir ouvert le
lien envoyé par courriel (réglage « confirmation du courriel pour publier » de /gestion/reglages/).
"""

import logging

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext as _

log = logging.getLogger(__name__)


class ConfirmationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "community.confirmation"

    def _make_hash_value(self, user, timestamp):
        # L'état de confirmation fait partie du jeton : une fois l'adresse confirmée, le lien ne sert plus.
        return f"{user.pk}{user.profile.email_confirmed}{user.email}{timestamp}"


tokens = ConfirmationTokenGenerator()


def required():
    from siteconfig.models import SiteConfig

    return SiteConfig.get().require_email_confirmation


def can_publish(user):
    return user.is_authenticated and (user.profile.email_confirmed or user.is_staff or not required())


def link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return settings.SITE_URL + reverse("community:confirm", args=[uid, tokens.make_token(user)])


def send(user):
    context = {"name": user.profile.display_name, "link": link(user)}
    try:
        send_mail(_("Nice-Event : confirme ton adresse"), render_to_string("community/confirm_email.txt", context),
                  None, [user.email], fail_silently=False)
        return True
    except Exception:
        log.exception("Courriel de confirmation non envoyé à l'utilisateur %s", user.pk)
        return False
