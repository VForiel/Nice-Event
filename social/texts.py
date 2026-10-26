"""Textes proposés pour chaque réseau, modifiables avant publication dans /gestion/."""

from django.conf import settings
from django.utils import translation

from .models import LIMIT

X_URL_LENGTH = 23  # X compte toute adresse pour 23 caractères


def length(network, text):
    """Longueur au sens du réseau (X raccourcit les liens)."""
    from .networks import URL

    if network == "x":
        return len(URL.sub("x" * X_URL_LENGTH, text))
    return len(text)


def shorten(text, limit):
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def default_text(event, network, signature=""):
    from core.templatetags.ne import clock, day_short

    with translation.override("fr"):
        cat = event.main_category
        emoji = cat.emoji if cat else "📍"
        start = event.local_start
        when = day_short(start) + ("" if event.all_day else f" · {clock(start)}")
        place = f"{event.venue.name}, {event.venue.commune.name}"
        price = str(event.price_label)
        extras = " · EN friendly" if event.english_friendly else ""
        url = settings.SITE_URL + event.get_absolute_url()
        title = event.title
        summary = event.summary
        if event.state == event.State.CANCELLED:
            title = f"ANNULÉ — {title}"
    head = f"{emoji} {title}\n📅 {when}\n📍 {place}\n🎟️ {price}{extras}"
    tail = signature.strip()
    if network == "instagram":
        body = f"{head}\n\n{summary}\n\nInfos et inscription : lien en bio · nice-event.fr"
        return shorten(f"{body}\n\n{tail}".strip(), LIMIT[network])
    if network == "facebook":
        return f"{head}\n\n{summary}\n\n👉 {url}\n\n{tail}".strip()
    # X et Bluesky : textes courts, le résumé se raccourcit d'abord, la signature saute si besoin.
    limit = LIMIT[network]
    for with_tail in (True, False):
        fixed = f"{head}\n\n\n\n{url}" + (f"\n{tail}" if with_tail and tail else "")
        room = limit - length(network, fixed)
        if room >= 40 or not with_tail:
            short = shorten(summary, max(0, room))
            parts = [head, short, url] if short else [head, url]
            text = "\n\n".join(parts) + (f"\n{tail}" if with_tail and tail else "")
            if length(network, text) <= limit:
                return text
    return shorten(f"{title}\n{url}", limit)


def alt_text(event):
    with translation.override("fr"):
        cat = event.main_category
        return (f"Visuel de l'événement « {event.title} » ({cat.name if cat else 'événement'}), "
                f"{event.venue.name}, {event.venue.commune.name}. {event.summary}")[:1000]
