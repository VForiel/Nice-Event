"""Lecture des sources : chaque connecteur renvoie des dictionnaires « événement externe » normalisés.

    {"id", "url", "title", "description", "start", "end", "all_day", "place", "address", "city", "postcode",
     "lat", "lon", "image", "free", "price", "age_min", "age_max", "keywords", "cancelled"}

(start/end : datetime avec fuseau ; les champs inconnus valent None ou "".)
"""

import html
import json
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import urljoin

from django.utils import timezone

from core.markdown import plain

LD_SCRIPT = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
NEXT_LINK = re.compile(r"""<link[^>]+rel=["']next["'][^>]*href=["']([^"']+)["']|<a[^>]+rel=["']next["'][^>]*href=["']([^"']+)["']""", re.I)
EVENT_TYPES = re.compile(r"Event$")


def clean(text):
    return re.sub(r"\s+", " ", html.unescape(plain(str(text or "")))).strip()


def as_datetime(value):
    """Date ou date-heure ISO (ou objet date/datetime) -> (datetime avec fuseau, journée entière ?)."""
    if value in (None, ""):
        return None, False
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return timezone.make_aware(datetime.combine(value, time(0, 0))), True
    else:
        value = str(value).strip()
        if len(value) == 10:
            try:
                return timezone.make_aware(datetime.combine(date.fromisoformat(value), time(0, 0))), True
            except ValueError:
                return None, False
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None, False
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt, False


def first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


# iCal -------------------------------------------------------------------------------------------------------------------


def read_ical(source, fetcher):
    from icalendar import Calendar

    calendar = Calendar.from_ical(fetcher.get(source.url))
    items = []
    for component in calendar.walk("VEVENT"):
        start, all_day = as_datetime(component.decoded("DTSTART", None))
        if start is None:
            continue
        end, _ = as_datetime(component.decoded("DTEND", None)) if component.get("DTEND") else (None, False)
        if all_day and end:
            end -= timedelta(minutes=1)  # DTEND exclusif pour les journées entières
        geo = component.get("GEO")
        location = clean(component.get("LOCATION", ""))
        place, _sep, address = location.partition(",")
        items.append({
            "id": str(component.get("UID", "")) or f"{start.isoformat()}-{component.get('SUMMARY')}",
            "url": str(component.get("URL", "")) or source.website or source.url,
            "title": clean(component.get("SUMMARY", "")),
            "description": clean(component.get("DESCRIPTION", "")),
            "start": start, "end": end, "all_day": all_day,
            "place": place.strip(), "address": address.strip(), "city": "", "postcode": "",
            "lat": geo.latitude if geo else None, "lon": geo.longitude if geo else None,
            "image": "", "free": None, "price": None, "age_min": None, "age_max": None,
            "keywords": " ".join(str(c) for c in (component.get("CATEGORIES").cats if component.get("CATEGORIES") else [])),
            "cancelled": str(component.get("STATUS", "")).upper() == "CANCELLED",
        })
    return items, True  # le flux est complet : un événement absent a disparu de la source


# JSON-LD (schema.org Event) -------------------------------------------------------------------------------------------


def ld_blocks(page):
    for match in LD_SCRIPT.finditer(page):
        try:
            data = json.loads(match.group(1).strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                yield node
                for key in ("@graph", "itemListElement", "item", "subEvent"):
                    child = node.get(key)
                    if isinstance(child, list):
                        stack.extend(child)
                    elif isinstance(child, dict):
                        stack.append(child)


def is_event(node):
    types = node.get("@type")
    types = types if isinstance(types, list) else [types]
    return any(isinstance(t, str) and EVENT_TYPES.search(t) for t in types)


def ld_event(node, page_url):
    start, all_day = as_datetime(node.get("startDate"))
    if start is None or not node.get("name"):
        return None
    end, _ = as_datetime(node.get("endDate"))
    location = first(node.get("location")) or {}
    if isinstance(location, str):
        location = {"name": location}
    address = location.get("address") or {}
    if isinstance(address, str):
        address = {"streetAddress": address}
    geo = location.get("geo") or {}
    offers = first(node.get("offers")) or {}
    price = offers.get("price") if isinstance(offers, dict) else None
    try:
        price = float(str(price).replace(",", ".")) if price not in (None, "") else None
    except ValueError:
        price = None
    free = True if node.get("isAccessibleForFree") in (True, "true", "True") or price == 0 else (False if price else None)
    image = first(node.get("image"))
    if isinstance(image, dict):
        image = image.get("url", "")
    url = node.get("url") or page_url
    return {
        "id": url, "url": url, "title": clean(node.get("name")), "description": clean(node.get("description")),
        "start": start, "end": end, "all_day": all_day,
        "place": clean(location.get("name")), "address": clean(address.get("streetAddress")),
        "city": clean(address.get("addressLocality")), "postcode": clean(address.get("postalCode")),
        "lat": _float(geo.get("latitude")), "lon": _float(geo.get("longitude")),
        "image": image or "", "free": free, "price": price if price else None,
        "age_min": None, "age_max": None,
        "keywords": clean(" ".join(filter(None, [str(node.get("keywords") or ""), str(node.get("@type"))]))),
        "cancelled": "Cancelled" in str(node.get("eventStatus", "")),
    }


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


MAX_DETAILS = 80


def read_jsonld(source, fetcher, known_fresh=frozenset()):
    """Page de liste : événements décrits directement, ou liste (ItemList) de pages d'événements à ouvrir.

    `known_fresh` : pages d'événements déjà vues il y a peu, qu'on ne retélécharge pas (on les signale juste vues).
    """
    items, seen, detail_urls, page_url = [], set(), [], source.url
    for _page in range(max(1, source.max_pages)):
        page = fetcher.get(page_url)
        for node in ld_blocks(page):
            if is_event(node):
                event = ld_event(node, page_url)
                if event and event["url"] not in seen:
                    seen.add(event["url"])
                    items.append(event)
            elif node.get("@type") == "ListItem" and node.get("url") and not isinstance(node.get("item"), dict):
                detail_urls.append(urljoin(page_url, node["url"]))
        match = NEXT_LINK.search(page)
        if not match:
            break
        page_url = urljoin(page_url, html.unescape(match.group(1) or match.group(2)))
    fetched = 0
    for url in dict.fromkeys(detail_urls):
        if url in seen:
            continue
        if url in known_fresh:
            items.append({"id": url, "url": url, "unchanged": True})
            continue
        if fetched >= MAX_DETAILS:
            break
        fetched += 1
        try:
            page = fetcher.get(url)
        except Exception:  # une page en erreur ne bloque pas le reste du scan
            continue
        for node in ld_blocks(page):
            if is_event(node):
                event = ld_event(node, url)
                if event:
                    event["id"] = event["url"] = url
                    items.append(event)
                    break
    return items, False  # liste partielle (pagination) : un absent n'a pas forcément disparu


# OpenAgenda (API v2) ---------------------------------------------------------------------------------------------------

OPENAGENDA_UID = re.compile(r"(\d{5,})")


def read_openagenda(source, fetcher):
    match = OPENAGENDA_UID.search(source.url)
    if not match:
        raise ValueError("Adresse OpenAgenda sans identifiant numérique d'agenda.")
    if not source.api_key:
        raise ValueError("Clé d'API OpenAgenda manquante (réglages de la source).")
    uid = match.group(1)
    items, after = [], None
    for _page in range(20):
        params = {"key": source.api_key, "detailed": 1, "monolingual": "fr", "size": 100,
                  "relative[]": ["current", "upcoming"]}
        if after:
            params["after[]"] = after
        data = json.loads(fetcher.get(f"https://api.openagenda.com/v2/agendas/{uid}/events", params=params,
                                      check_robots=False))
        for ev in data.get("events", []):
            timings = sorted(ev.get("timings") or [], key=lambda t: t.get("begin", ""))
            now = timezone.now()
            upcoming = [t for t in timings if (as_datetime(t.get("end"))[0] or now) >= now] or timings[-1:]
            if not upcoming:
                continue
            start, _ = as_datetime(upcoming[0].get("begin"))
            end, _ = as_datetime(upcoming[0].get("end"))
            loc = ev.get("location") or {}
            image = ev.get("image") or {}
            conditions = clean(ev.get("conditions"))
            free = True if re.search(r"gratuit|libre|free", conditions, re.I) else None
            age = ev.get("age") or {}
            items.append({
                "id": str(ev.get("uid")), "url": f"https://openagenda.com/agendas/{uid}/events/{ev.get('slug')}",
                "title": clean(ev.get("title")), "description": clean(ev.get("description")),
                "start": start, "end": end, "all_day": False,
                "place": clean(loc.get("name")), "address": clean(loc.get("address")), "city": clean(loc.get("city")),
                "postcode": clean(loc.get("postalCode")), "lat": _float(loc.get("latitude")), "lon": _float(loc.get("longitude")),
                "image": f"{image.get('base', '')}{image.get('filename', '')}" if image.get("filename") else "",
                "free": free, "price": None, "age_min": age.get("min"), "age_max": age.get("max"),
                "keywords": clean(" ".join((ev.get("keywords") or {}).get("fr", []) if isinstance(ev.get("keywords"), dict) else [])),
                "cancelled": ev.get("status") == 6,
            })
        after = data.get("after")
        if not after or not data.get("events"):
            break
    return items, True


READERS = {"ical": read_ical, "jsonld": read_jsonld, "openagenda": read_openagenda}
