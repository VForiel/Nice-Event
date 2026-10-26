"""Envoi des publications : appelé par la tâche de fond (publications programmées) ou tout de suite depuis /gestion/."""

import logging
from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from siteconfig.models import SiteConfig

from . import networks
from .models import Post
from .texts import alt_text
from .visuals import visual_path, visual_url

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def claim(post_id):
    """Passe la publication en « envoi » si elle est toujours à envoyer (évite les doublons entre processus)."""
    with transaction.atomic():
        return Post.objects.filter(pk=post_id, status=Post.Status.SCHEDULED).update(status=Post.Status.SENDING) == 1


def send(post):
    config = SiteConfig.get()
    post.attempts += 1
    if not config.network_ready(post.network):
        post.status, post.error = Post.Status.FAILED, f"{post.get_network_display()} n'est pas configuré ou pas activé."
        post.save(update_fields=["status", "error", "attempts"])
        return post
    event = post.event
    fmt = post.visual_format
    try:
        image = visual_path(event, fmt)
        image_url = settings.SITE_URL + visual_url(event, fmt)
        external_id, url = networks.PUBLISHERS[post.network](post, config, image, image_url, alt_text(event))
    except (networks.PublishError, requests.RequestException, OSError, KeyError, ValueError) as exc:
        log.warning("Publication %s en échec : %s", post.pk, exc)
        retry = post.attempts < MAX_ATTEMPTS and isinstance(exc, requests.RequestException)
        post.status = Post.Status.SCHEDULED if retry else Post.Status.FAILED
        if retry:
            post.scheduled_at = timezone.now() + timedelta(minutes=5 * post.attempts)
        post.error = str(exc)[:2000]
        post.save(update_fields=["status", "error", "attempts", "scheduled_at"])
        return post
    post.status, post.external_id, post.external_url = Post.Status.PUBLISHED, str(external_id), url
    post.published_at, post.error = timezone.now(), ""
    post.save(update_fields=["status", "external_id", "external_url", "published_at", "error", "attempts"])
    return post


def send_due():
    sent = []
    for post_id in Post.objects.due().values_list("pk", flat=True)[:20]:
        if claim(post_id):
            post = send(Post.objects.select_related("event__venue__commune").get(pk=post_id))
            sent.append(f"{post.get_network_display()} #{post.pk} : {post.get_status_display()}")
    # Envoi interrompu (redémarrage pendant l'envoi) : on retente au passage suivant
    stuck = timezone.now() - timedelta(minutes=15)
    Post.objects.filter(status=Post.Status.SENDING, scheduled_at__lt=stuck, attempts__lt=MAX_ATTEMPTS).update(
        status=Post.Status.SCHEDULED)
    return "; ".join(sent) or "Rien à publier"


def check_accounts():
    config = SiteConfig.get()
    result = {}
    for network in ("instagram", "facebook", "x", "bluesky"):
        if config.network_ready(network):
            ok, message = networks.check(network, config)
            result[network] = {"ok": ok, "message": message}
    config.social_check, config.social_checked_at = result, timezone.now()
    config.save(update_fields=["social_check", "social_checked_at"])
    failed = [n for n, r in result.items() if not r["ok"]]
    if failed:
        raise RuntimeError(f"Comptes à revoir : {', '.join(failed)} ({result})")
    return f"{len(result)} compte(s) vérifié(s)"
