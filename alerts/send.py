"""Recherche des nouveaux événements de chaque alerte et envoi sur les canaux choisis par le membre.

Toujours : une notification sur le site. En plus, selon les réglages du membre : courriel, Discord (webhook),
Telegram (bot du site), notification du navigateur (Web Push, clés VAPID du site).
"""

import base64
import json
import logging
import re
from html import escape

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone, translation

from community.models import Notification
from events import rules
from events.models import Event, SavedFilter

from .models import Channel, Hit, PushSubscription

log = logging.getLogger(__name__)

DISCORD_WEBHOOK = re.compile(r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+$")
TELEGRAM_CHAT = re.compile(r"^(-?\d{1,20}|@\w{4,64})$")
MAX_PER_MESSAGE = 10


# Recherche ------------------------------------------------------------------------------------------------------------

def new_matches(saved):
    """Événements publiés depuis la mise en route de l'alerte, à venir, pas encore signalés."""
    events = Event.objects.published().upcoming().select_related("venue__commune")
    if saved.alert_since:
        events = events.filter(published_at__gte=saved.alert_since)
    events = rules.matches(saved.rule, events).exclude(pk__in=saved.hits.values("event_id"))
    return list(events.order_by("starts_at")[:50])


def collect():
    """Note les nouveaux événements de toutes les alertes (envoyés plus tard pour les résumés)."""
    found = 0
    for saved in SavedFilter.objects.filter(alert=True, user__is_active=True):
        for event in new_matches(saved):
            Hit.objects.get_or_create(saved_filter=saved, event=event)
            found += 1
    return found


def due(saved, now):
    if saved.frequency == SavedFilter.Frequency.NOW:
        return True
    local = timezone.localtime(now)
    if local.hour < 18:
        return False
    last = timezone.localtime(saved.last_sent_at) if saved.last_sent_at else None
    if saved.frequency == SavedFilter.Frequency.DAILY:
        return last is None or last.date() < local.date()
    return local.weekday() == 3 and (last is None or (local.date() - last.date()).days >= 6)


def run(now=None):
    """Tâche planifiée : recherche puis envoi de ce qui est dû. Renvoie un compte rendu."""
    now = now or timezone.now()
    collect()
    sent = 0
    for saved in SavedFilter.objects.filter(alert=True, user__is_active=True).select_related("user"):
        if not due(saved, now):
            continue
        hits = list(saved.hits.filter(sent_at__isnull=True, event__status=Event.Status.PUBLISHED,
                                      event__ends_at__gte=now).select_related("event__venue__commune")
                    .order_by("event__starts_at"))
        if not hits:
            continue
        deliver(saved, [h.event for h in hits])
        Hit.objects.filter(pk__in=[h.pk for h in hits]).update(sent_at=now)
        SavedFilter.objects.filter(pk=saved.pk).update(last_sent_at=now)
        sent += 1
    return f"{sent} alerte(s) envoyée(s)"


# Envoi ----------------------------------------------------------------------------------------------------------------

def absolute(event):
    return settings.SITE_URL + event.get_absolute_url()


def when(event):
    from core.templatetags.ne import day_short, hours

    with translation.override("fr"):
        return f"{day_short(event.local_start)} · {hours(event)}"


def deliver(saved, events):
    """Envoie les événements (déjà triés) au membre, sur tous ses canaux actifs."""
    user = saved.user
    for event in events[:MAX_PER_MESSAGE]:
        Notification.objects.create(recipient=user, actor=None, verb=Notification.Verb.ALERT, event=event,
                                    message=saved.name[:300])
    channels = {c.kind: c for c in Channel.objects.filter(user=user, is_active=True)}
    if Channel.Kind.EMAIL in channels:
        send_email(saved, events)
    for kind, sender in ((Channel.Kind.DISCORD, send_discord), (Channel.Kind.TELEGRAM, send_telegram),
                         (Channel.Kind.PUSH, send_push)):
        if kind in channels:
            try:
                sender(channels[kind], saved, events)
            except Exception:  # un canal en panne n'empêche pas les autres
                log.exception("Alerte %s : envoi %s impossible", saved.pk, kind)


def title_for(saved, events):
    if len(events) == 1:
        return f"Nice-Event · {saved.name} : {events[0].title}"
    return f"Nice-Event · {saved.name} : {len(events)} nouveaux événements"


def send_email(saved, events):
    if not saved.user.email:
        return
    context = {"saved": saved, "events": [(e, when(e), absolute(e)) for e in events[:MAX_PER_MESSAGE]],
               "more": max(0, len(events) - MAX_PER_MESSAGE), "site": settings.SITE_URL}
    with translation.override("fr"):
        body = render_to_string("alerts/alert_email.txt", context)
    try:
        send_mail(title_for(saved, events), body, None, [saved.user.email], fail_silently=False)
    except Exception:
        log.exception("Courriel d'alerte non envoyé (filtre %s)", saved.pk)


def send_discord(channel, saved, events):
    url = channel.config.get("webhook", "")
    if not DISCORD_WEBHOOK.match(url):
        return
    embeds = [{"title": e.title[:250], "url": absolute(e), "color": 0x1F6FD1,
               "description": f"{when(e)}\n{e.venue.name}, {e.venue.commune.name}\n{e.price_label}"[:2000]}
              for e in events[:MAX_PER_MESSAGE]]
    requests.post(url, json={"username": "Nice-Event", "content": f"🔔 Alerte « {saved.name} »", "embeds": embeds},
                  timeout=10).raise_for_status()


def send_telegram(channel, saved, events):
    from siteconfig.models import SiteConfig

    token = SiteConfig.get().telegram_bot_token
    chat = channel.config.get("chat_id", "")
    if not token or not TELEGRAM_CHAT.match(chat):
        return
    lines = [f"🔔 <b>{escape(saved.name)}</b>"]
    for e in events[:MAX_PER_MESSAGE]:
        lines.append(f"\n<b><a href=\"{escape(absolute(e))}\">{escape(e.title)}</a></b>\n📅 {escape(when(e))}\n"
                     f"📍 {escape(e.venue.name)}, {escape(e.venue.commune.name)}")
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id": chat, "text": "\n".join(lines), "parse_mode": "HTML", "disable_web_page_preview": True},
                  timeout=10).raise_for_status()


def send_push(channel, saved, events):
    from pywebpush import WebPushException, webpush

    keys = vapid_keys()
    first = events[0]
    payload = json.dumps({
        "title": title_for(saved, events),
        "body": f"{when(first)} · {first.venue.name}" if len(events) == 1 else ", ".join(e.title for e in events[:4]),
        "url": first.get_absolute_url() if len(events) == 1 else "/notifications/",
        "tag": f"alerte-{saved.pk}",
    })
    for sub in PushSubscription.objects.filter(user=saved.user):
        try:
            webpush({"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}, payload,
                    vapid_private_key=keys["private"], vapid_claims={"sub": "mailto:contact@nice-event.fr"}, ttl=86400)
        except WebPushException as exc:
            if exc.response is not None and exc.response.status_code in (404, 410):
                sub.delete()  # abonnement révoqué par le navigateur
            else:
                log.warning("Notification du navigateur non envoyée : %s", exc)


def vapid_keys():
    """Clés VAPID du site, créées au premier besoin : {"public": base64url (navigateur), "private": base64url}."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from siteconfig.models import SiteConfig

    config = SiteConfig.get()
    if not config.vapid_private_key:
        key = ec.generate_private_key(ec.SECP256R1())
        private = key.private_numbers().private_value.to_bytes(32, "big")
        public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        config.vapid_private_key = b64(private)
        config.vapid_public_key = b64(public)
        config.save(update_fields=["vapid_private_key", "vapid_public_key"])
    return {"public": config.vapid_public_key, "private": config.vapid_private_key}


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def test(user):
    """Message d'essai sur chaque canal actif ; renvoie {canal: "ok" | message d'erreur}."""
    event = Event.objects.published().upcoming().select_related("venue__commune").first()
    report = {}
    if event is None:
        return {"site": "aucun événement à venir pour l'essai"}
    fake = SavedFilter(user=user, name="Essai", rule={})
    for channel in Channel.objects.filter(user=user, is_active=True):
        try:
            if channel.kind == Channel.Kind.EMAIL:
                send_mail(title_for(fake, [event]), render_to_string("alerts/alert_email.txt", {
                    "saved": fake, "events": [(event, when(event), absolute(event))], "more": 0,
                    "site": settings.SITE_URL}), None, [user.email], fail_silently=False)
            elif channel.kind == Channel.Kind.DISCORD:
                send_discord(channel, fake, [event])
            elif channel.kind == Channel.Kind.TELEGRAM:
                send_telegram(channel, fake, [event])
            elif channel.kind == Channel.Kind.PUSH:
                send_push(channel, fake, [event])
            report[channel.get_kind_display()] = "ok"
        except Exception as exc:
            report[channel.get_kind_display()] = str(exc)[:200]
    return report
