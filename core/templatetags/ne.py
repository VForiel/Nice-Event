from datetime import timedelta

from django import template
from django.urls import translate_url
from django.utils import timezone
from django.utils.dateformat import format as dformat
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from core.i18n import is_english
from core.images import thumbnail_url

register = template.Library()

# Tracés 24×24, trait 2 px (repris de l'AJC06, plus les pictogrammes de catégories de Nice-Event).
ICONS = {
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "arrow-left": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "external": '<path d="M14 5h5v5M19 5l-8 8M18 14v5H5V6h5"/>',
    "calendar": '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    "pin": '<path d="M12 21s-6-5.6-6-11a6 6 0 0 1 12 0c0 5.4-6 11-6 11z"/><circle cx="12" cy="10" r="2.2"/>',
    "ticket": '<path d="M4 8a2 2 0 0 0 2-2h12a2 2 0 0 0 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 0-2 2H6a2 2 0 0 0-2-2v-2a2 2 0 0 0 0-4z"/><path d="M14 6v12" stroke-dasharray="2 2"/>',
    "euro": '<path d="M17 6.5A6 6 0 0 0 8 12a6 6 0 0 0 9 5.5M5 10.5h8M5 13.5h8"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    "rss": '<path d="M5 5a14 14 0 0 1 14 14M5 11a8 8 0 0 1 8 8"/><circle cx="6" cy="18" r="1.2"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7"/>',
    "heart": '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z"/>',
    "download": '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16v4zM13 7l4 4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14a6.5 6.5 0 0 1 3.5 6"/>',
    "instagram": '<rect x="3.5" y="3.5" width="17" height="17" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.2" cy="6.8" r=".6" fill="currentColor"/>',
    "whatsapp": '<path d="M4.5 19.5l1.2-3.6A8 8 0 1 1 8.4 18.6z"/><path d="M9.2 8.6c.2-.5.6-.5.9-.5h.5c.2 0 .4.1.5.4l.7 1.6c.1.2 0 .5-.1.6l-.5.6c-.1.2-.1.4 0 .5a6 6 0 0 0 2.8 2.6c.2.1.4 0 .5-.1l.6-.7c.2-.2.4-.2.6-.1l1.6.8c.2.1.3.3.3.5 0 .7-.4 1.4-1.1 1.6-.7.3-1.6.3-3-.3a8.6 8.6 0 0 1-4.1-4c-.6-1.2-.4-2.3-.2-2.9z" fill="currentColor" stroke="none"/>',
    "discord": '<path d="M8.5 7.5C7 7.8 5.8 8.3 4.8 9 3.4 11.4 3 14 3.2 16.6c1.3 1 2.8 1.7 4.3 2.1l1-1.6M15.5 7.5c1.5.3 2.7.8 3.7 1.5 1.4 2.4 1.8 5 1.6 7.6-1.3 1-2.8 1.7-4.3 2.1l-1-1.6M7.5 16.5c2.8 1.3 6.2 1.3 9 0M9 7.2a12 12 0 0 1 6 0"/><circle cx="9.3" cy="13" r="1.1"/><circle cx="14.7" cy="13" r="1.1"/>',
    "facebook": '<path d="M14 21v-7.5h2.6l.4-3H14V8.7c0-.9.3-1.5 1.6-1.5H17V4.5a19 19 0 0 0-2.3-.1C12.4 4.4 11 5.8 11 8.3v2.2H8.5v3H11V21"/>',
    "linkedin": '<rect x="3.5" y="3.5" width="17" height="17" rx="2.5"/><path d="M8 10.5V17M8 7.3v.2M12 17v-3.8a2.2 2.2 0 0 1 4.4 0V17M12 10.5V17"/>',
    # Catégories (mêmes tracés que la maquette design/maquette.html)
    "music": '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    "party": '<circle cx="12" cy="11" r="7"/><path d="M5 11h14M12 4c2.5 2 2.5 12 0 14M12 4c-2.5 2-2.5 12 0 14M12 18v3"/>',
    "sea": '<circle cx="17" cy="6" r="3"/><path d="M2 15c2.5-2 4.5-2 7 0s4.5 2 7 0 4.5-2 6 0M2 20c2.5-2 4.5-2 7 0s4.5 2 7 0 4.5-2 6 0"/>',
    "hike": '<path d="M2 20l7-11 4 6 3-4 6 9z"/><path d="M8 11l2 2 2-1"/>',
    "food": '<path d="M8 3h8l-1 7a3 3 0 0 1-6 0z"/><path d="M12 13v8M8 21h8"/>',
    "lang": '<path d="M4 5h9v7H8l-4 3z"/><path d="M13 9h7v7l-3-2h-4"/>',
    "meet": '<circle cx="8" cy="8" r="3"/><circle cx="16" cy="8" r="3"/><path d="M3 20c0-3 2-5 5-5s5 2 5 5M11 20c0-3 2-5 5-5s5 2 5 5"/>',
    "show": '<path d="M3 4h18M5 4v16M19 4v16M5 4c0 6 7 6 7 0 0 6 7 6 7 0"/><path d="M3 20h18"/>',
    "market": '<path d="M3 9h18l-2 11H5z"/><path d="M8 9l2-5M16 9l-2-5"/>',
    "kids": '<circle cx="12" cy="13" r="7"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="6.5" r="2.5"/><path d="M9.5 15.5c1.5 1.3 3.5 1.3 5 0"/>',
    "share": '<circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4"/>',
    "messenger": '<path d="M12 3.5c-4.8 0-8.5 3.5-8.5 8 0 2.4 1.1 4.6 2.9 6.1V21l3-1.7c.8.2 1.7.3 2.6.3 4.8 0 8.5-3.5 8.5-8s-3.7-8.1-8.5-8.1z"/><path d="M7.5 13.5l3-3.2 2.2 2 3.8-2.8-3 3.3-2.2-2z"/>',
    "bluesky": '<path d="M12 11c-1.6-3.2-5.4-7-7.8-7C3 4 3 5.6 3 6.6c0 1.6 1 5.4 3.6 5.9-2.6.5-3.4 2.1-1.8 3.8 3 3.2 4.6-.8 5.6-3 .6-1.2 1.2-1.2 1.2-1.2s.6 0 1.2 1.2c1 2.2 2.6 6.2 5.6 3 1.6-1.7.8-3.3-1.8-3.8 2.6-.5 3.6-4.3 3.6-5.9C21 5.6 21 4 19.8 4c-2.4 0-6.2 3.8-7.8 7z"/>',
    "x": '<path d="M4 4l16 16M20 4l-6.8 7.4M10.8 12.6L4 20"/>',
    "telegram": '<path d="M21 4.5L2.8 11.6c-.8.3-.8 1.4.1 1.7l4.5 1.5 1.7 5.3c.2.7 1.1.9 1.6.4l2.5-2.4 4.7 3.5c.6.4 1.4.1 1.6-.6L21.9 5.6c.2-.8-.5-1.4-.9-1.1z"/><path d="M7.4 14.8L18 7.5l-8 8.2"/>',
    "smile": '<circle cx="12" cy="12" r="9"/><path d="M8 14.5c1 1.5 2.4 2.2 4 2.2s3-.7 4-2.2M9 9.5v.5M15 9.5v.5"/>',
    "film": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 9.5h4M3 14.5h4M17 9.5h4M17 14.5h4"/>',
    "frame": '<rect x="3.5" y="4" width="17" height="16" rx="1.5"/><path d="M6.5 16.5l4-5 3 3.5 2-2 2 3.5"/><circle cx="15.5" cy="8.5" r="1.3"/>',
    "tent": '<path d="M3 20h18M12 4l-8 16M12 4l8 16M12 4v16M12 13l-3 7M12 13l3 7"/>',
    "confetti": '<path d="M4 20l4.5-12 7.5 7.5z"/><path d="M14 4v2M19 9h2M17 6l1.5-1.5M12 9c1-1 1.5-2.5 1-4M15 12c1-1 2.5-1.5 4-1"/>',
    "run": '<circle cx="15" cy="4.5" r="2"/><path d="M6 20l3.5-5 3 2 1-5.5 3 2.5 2.5-.5M13.5 11.5l-4-1.5-3 3M9.5 15l-2 1.5"/>',
    "stadium": '<ellipse cx="12" cy="9" rx="9" ry="4"/><path d="M3 9v6c0 2.2 4 4 9 4s9-1.8 9-4V9"/><path d="M8 12.6V18M16 12.6V18"/>',
    "brush": '<path d="M14.5 4.5l5 5L11 18l-5-5z"/><path d="M6 13c-2 0-3 1.5-3 3 0 1.5-1 2.5-1 2.5s4 1 6-1c1-1 1-2.5-.5-3.5"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/>',
    "handshake": '<path d="M3 11l4-4 3 1 3-2 4 1 4 4M7 7v8l4 4c.8.8 2 .8 2.8 0l4.2-4.2M10 12.5l2.5 2.5M12.5 10.5L15 13"/>',
    "leaf": '<path d="M5 19c0-8 5-13 15-14-1 10-6 15-14 15"/><path d="M5 19c3-4 6-7 10-9"/>',
    "dice": '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="9" cy="9" r="1" fill="currentColor"/><circle cx="15" cy="15" r="1" fill="currentColor"/><circle cx="15" cy="9" r="1" fill="currentColor"/><circle cx="9" cy="15" r="1" fill="currentColor"/>',
    "filter": '<path d="M4 6h16M7 12h10M10 18h4"/>',
    "map": '<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>',
    "bell": '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
}


@register.simple_tag
def icon(name, size=20, label=""):
    paths = ICONS[name]
    aria = format_html('role="img" aria-label="{}"', label) if label else mark_safe('aria-hidden="true"')
    return format_html(
        '<svg class="icon icon-{}" width="{}" height="{}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" {}>{}</svg>',
        name, size, size, aria, mark_safe(paths),
    )


@register.simple_tag(takes_context=True)
def lang_url(context, lang):
    """Adresse de la page courante dans l'autre langue (/mentions-legales/ <-> /en/legal-notice/)."""
    return translate_url(context["request"].get_full_path(), lang)


@register.filter
def thumb(image, size=480):
    """{{ event.photo|thumb:192 }} : URL d'une copie réduite pour les listes et vignettes."""
    return thumbnail_url(image, int(size))


MONTHS_SHORT = {
    "fr": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
DAYS_SHORT = {
    "fr": ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}


def _lang():
    return "en" if is_english() else "fr"


@register.filter
def day_short(value):
    """« ven. 30 oct. » / « Fri 30 Oct »."""
    lang = _lang()
    return f"{DAYS_SHORT[lang][value.weekday()]} {value.day} {MONTHS_SHORT[lang][value.month - 1]}"


@register.filter
def weekday_short(value):
    return DAYS_SHORT[_lang()][value.weekday()]


def clock(t):
    if is_english():
        return f"{t.hour}:{t.minute:02d}"
    return f"{t.hour} h {t.minute:02d}" if t.minute else f"{t.hour} h"


@register.filter
def hours(event):
    """« 19 h 30 – 23 h », « dès 19 h 30 », « toute la journée »."""
    if event.all_day:
        return _("Toute la journée")
    start, end = event.local_start, event.local_end
    if end and not event.multi_day:
        return f"{clock(start)} – {clock(end)}"
    if end:
        return _("Dès %(heure)s") % {"heure": clock(start)}
    return clock(start)


@register.filter
def when(event):
    """« samedi 7 novembre », « du sam. 7 au lun. 9 nov. »."""
    start = event.local_start
    if not event.multi_day:
        return dformat(start, "l j F")
    end = event.local_end
    return _("du %(a)s au %(b)s") % {"a": day_short(start), "b": day_short(end)}


@register.simple_tag
def day_heading(day):
    """<b>Aujourd'hui</b><span>vendredi 30 octobre</span>, ou <b>samedi 7 novembre</b>."""
    today = timezone.localdate()
    near = {today: _("Aujourd'hui"), today + timedelta(days=1): _("Demain")}.get(day)
    full = dformat(day, "l j F")
    if near:
        return format_html("<b>{}</b><span>{}</span>", near, full)
    return format_html("<b>{}</b>", full[:1].upper() + full[1:])


@register.simple_tag(takes_context=True)
def toggle_param(context, name, value):
    """Adresse de la page courante avec le filtre name=value ajouté ou retiré (puces de filtre)."""
    query = context["request"].GET.copy()
    query.pop("page", None)
    values = query.getlist(name)
    if value in values:
        values.remove(value)
    elif name == "categorie":
        values.append(value)
    else:
        values = [value]
    query.setlist(name, values)
    encoded = query.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.filter
def has_param(request, spec):
    """{{ request|has_param:"categorie=concert" }}"""
    name, _sep, value = spec.partition("=")
    return value in request.GET.getlist(name)
