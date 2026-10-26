"""Génération iCalendar (RFC 5545) sans dépendance."""

from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

from core import markdown


def _escape(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line):
    """Coupe les lignes à 75 octets comme l'exige la norme."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, chunk = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(chunk) + len(b) > (75 if not out else 74):
            out.append(chunk.decode("utf-8"))
            chunk = b""
        chunk += b
    out.append(chunk.decode("utf-8"))
    return "\r\n ".join(out)


def _utc(dt):
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def vevent(event):
    url = settings.SITE_URL + event.get_absolute_url()
    lines = ["BEGIN:VEVENT", f"UID:event-{event.pk}@nice-event.fr", f"DTSTAMP:{_utc(event.updated_at or timezone.now())}"]
    if event.all_day:
        last = timezone.localtime(event.ends_at).date()
        lines.append(f"DTSTART;VALUE=DATE:{event.local_start:%Y%m%d}")
        lines.append(f"DTEND;VALUE=DATE:{last + timedelta(days=1):%Y%m%d}")
    else:
        lines.append(f"DTSTART:{_utc(event.starts_at)}")
        lines.append(f"DTEND:{_utc(event.ends_at)}")
    title = event.title_tr
    if event.is_cancelled:
        title = _("ANNULÉ : %(title)s") % {"title": title}
        lines.append("STATUS:CANCELLED")
    lines.append(f"SUMMARY:{_escape(title)}")
    description = event.summary_tr
    plain = markdown.plain(event.description_tr, 1200)
    if plain:
        description += "\n\n" + plain
    description += "\n\n" + str(event.price_label)
    if event.ticket_url:
        description += "\n" + _("Billetterie : %(url)s") % {"url": event.ticket_url}
    lines.append(f"DESCRIPTION:{_escape(description + chr(10) + chr(10) + url)}")
    lines.append(f"LOCATION:{_escape(event.venue.full_address)}")
    if event.venue.lat is not None:
        lines.append(f"GEO:{event.venue.lat:.5f};{event.venue.lon:.5f}")
    lines += [f"URL:{url}", "END:VEVENT"]
    return lines


def calendar(events, name="Nice-Event"):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Nice-Event//Agenda//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "X-WR-TIMEZONE:Europe/Paris",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
    ]
    for event in events:
        lines += vevent(event)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
