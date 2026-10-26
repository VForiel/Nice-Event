"""Notifications sur le site, doublées d'un courriel pour celles qui comptent (si le membre l'accepte)."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import translation

from .models import Notification

log = logging.getLogger(__name__)

# Notifications qui partent aussi par courriel.
BY_EMAIL = {Notification.Verb.INVITE, Notification.Verb.APPROVED, Notification.Verb.REJECTED, Notification.Verb.CHANGED}


def notify(recipient, actor, verb, event=None, message=""):
    if actor is not None and recipient.pk == actor.pk:
        return None
    item = Notification.objects.create(recipient=recipient, actor=actor, verb=verb, event=event, message=message[:300])
    profile = getattr(recipient, "profile", None)
    if verb in BY_EMAIL and recipient.email and profile and profile.email_notifications:
        send_email(item)
    return item


def send_email(item):
    context = {"n": item, "site": settings.SITE_URL}
    with translation.override("fr"):
        subject = render_to_string("community/notification_subject.txt", context).strip()
        body = render_to_string("community/notification_email.txt", context)
    try:
        send_mail(subject, body, None, [item.recipient.email], fail_silently=False)
    except Exception:
        log.exception("Courriel de notification non envoyé (notification %s)", item.pk)
