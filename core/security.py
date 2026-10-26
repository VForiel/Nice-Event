"""Protection contre les essais de mots de passe, à la manière de fail2ban (repris du site de l'AJC06).

- 5 échecs de connexion en 15 minutes depuis une même adresse IP : blocage d'une heure ;
- tentative avec un identifiant d'administration générique (« admin »…) : blocage immédiat de 24 heures.

Le blocage vaut pour tout le site et pour toutes les portes d'entrée : connexion des membres, admin Django.
"""

import ipaddress
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver
from django.http import HttpResponseForbidden
from django.template.loader import render_to_string
from django.utils import timezone

MAX_FAILURES = 5
WINDOW = timedelta(minutes=15)
BAN = timedelta(hours=1)
INSTANT_BAN = timedelta(hours=24)
FORBIDDEN_USERNAMES = {"admin", "administrator", "administrateur", "root", "wp-admin", "webmaster"}
KEEP_FAILURES = timedelta(days=7)  # au-delà, les échecs ne servent plus à rien


def throttled(key, limit, seconds):
    """Compteur simple en cache : vrai si la limite est déjà atteinte (sinon compte ce passage)."""
    count = cache.get(key, 0)
    if count >= limit:
        return True
    cache.set(key, count + 1, seconds)
    return False


def client_ip(request):
    """Adresse du visiteur. Derrière le reverse proxy de confiance (Caddy sur VPS1), X-Forwarded-For est fiable ;
    sans lui, seule REMOTE_ADDR l'est, l'en-tête pouvant être forgé."""
    ip = request.META.get("REMOTE_ADDR", "")
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        ip = forwarded or ip
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return ""


def ban(ip, duration, reason):
    from .models import Ban

    if not ip:
        return None
    until = timezone.now() + duration
    item, created = Ban.objects.get_or_create(ip=ip, defaults={"until": until, "reason": reason})
    if not created and item.until < until:
        item.until, item.reason = until, reason
        item.save(update_fields=["until", "reason"])
    return item


def is_banned(ip):
    from .models import Ban

    return bool(ip) and Ban.objects.filter(ip=ip, until__gt=timezone.now()).exists()


@receiver(user_login_failed, dispatch_uid="core_security_login_failed")
def on_login_failed(sender, credentials, request=None, **kwargs):
    from .models import LoginFailure

    if request is None:
        return
    ip = client_ip(request)
    username = (credentials.get("username") or "").strip().lower()[:150]
    LoginFailure.objects.filter(created_at__lt=timezone.now() - KEEP_FAILURES).delete()
    LoginFailure.objects.create(ip=ip, username=username)
    if username in FORBIDDEN_USERNAMES:
        ban(ip, INSTANT_BAN, f"identifiant « {username} »")
        return
    recent = LoginFailure.objects.filter(ip=ip, created_at__gte=timezone.now() - WINDOW).count()
    if recent >= MAX_FAILURES:
        ban(ip, BAN, f"{recent} échecs de connexion")


@receiver(user_logged_in, dispatch_uid="core_security_logged_in")
def on_logged_in(sender, request=None, user=None, **kwargs):
    from .models import LoginFailure

    if request is not None:
        LoginFailure.objects.filter(ip=client_ip(request)).delete()


class BanMiddleware:
    """Refuse toute requête d'une adresse bloquée ; à placer après WhiteNoise (les fichiers statiques n'ont pas besoin
    de ce contrôle, qui coûte une requête SQL) et avant les sessions."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_banned(client_ip(request)):
            return HttpResponseForbidden(render_to_string("banned.html"), content_type="text/html; charset=utf-8")
        return self.get_response(request)
