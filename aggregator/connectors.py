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

from .fetch import FetchError

from core.markdown import plain
from core.text import repair

LD_SCRIPT = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
NEXT_LINK = re.compile(r"""<link[^>]+rel=["']next["'][^>]*href=["']([^"']+)["']|<a[^>]+rel=["']next["'][^>]*href=["']([^"']+)["']""", re.I)
EVENT_TYPES = re.compile(r"Event$")
ONLINE = re.compile(r"\bonline\b|\ben ligne\b|zoom\.us|zoom link|teams\.microsoft|meet\.google|webinar|webinaire|visio")


def clean(text):
    """Texte brut sur une ligne, entités HTML décodées et encodage cassé réparé (certaines sources sont en double UTF-8)."""
    return re.sub(r"\s+", " ", repair(html.unescape(plain(str(text or ""))))).strip()


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


PRICE = re.compile(r"(?<![\d,.])(\d{1,4}(?:[,.]\d{1,2})?)\s*(?:€|euros?\b|EUR\b)|€\s*(\d{1,4}(?:[,.]\d{1,2})?)", re.I)
FREE = re.compile(r"\b(?:entr[ée]e (?:libre|gratuite)|acc[eè]s (?:libre|gratuit)|gratuit(?:e)? pour tous|free (?:entry|admission)|"
                  r"admission (?:is )?free|[ée]v[ée]nement gratuit)\b", re.I)
OG_IMAGE = re.compile(r"""<meta[^>]+(?:property|name)=["'](?:og:image|twitter:image)(?::src)?["'][^>]*content=["']([^"']+)["']"""
                      r"""|<meta[^>]+content=["']([^"']+)["'][^>]*(?:property|name)=["'](?:og:image|twitter:image)["']""", re.I)


def price_from_text(text):
    """(gratuit ?, prix) lus dans un texte libre : « Entrée libre », « Tarif : 10€ », « inscription 30 euros »."""
    text = text or ""
    if FREE.search(text):
        return True, None
    prices = [float((a or b).replace(",", ".")) for a, b in PRICE.findall(text)]
    prices = [p for p in prices if 0 < p < 2000]
    return None, (min(prices) if prices else None)


def page_details(page, url):
    """Image et prix d'une page d'événement : données JSON-LD si présentes, sinon balises og:image et texte."""
    found = {"image": "", "free": None, "price": None}
    for node in ld_blocks(page):
        if is_event(node):
            event = ld_event(node, url) or {}
            found.update({k: event.get(k) for k in ("image", "free", "price") if event.get(k) not in (None, "")})
            break
    if not found["image"]:
        match = OG_IMAGE.search(page)
        if match:
            found["image"] = html.unescape(match.group(1) or match.group(2))
    if found["image"]:
        found["image"] = urljoin(url, found["image"])
    return found


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
        text = f"{component.get('SUMMARY', '')} {component.get('DESCRIPTION', '')}".lower()
        if not location and not geo and ONLINE.search(text):
            continue  # événement en ligne (Zoom, Teams…) : rien à faire sur place
        place, _sep, address = location.partition(",")
        free, price = price_from_text(str(component.get("DESCRIPTION", "")))
        image = ""
        for key in ("IMAGE", "ATTACH"):
            for value in component.get(key, []) if isinstance(component.get(key), list) else [component.get(key)]:
                if value and re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", str(value), re.I):
                    image = image or str(value)
        items.append({
            "id": str(component.get("UID", "")) or f"{start.isoformat()}-{component.get('SUMMARY')}",
            "url": str(component.get("URL", "")) or source.website or source.url,
            "title": clean(component.get("SUMMARY", "")),
            "description": clean(component.get("DESCRIPTION", "")),
            "start": start, "end": end, "all_day": all_day,
            "place": place.strip(), "address": address.strip(), "city": "", "postcode": "",
            "lat": geo.latitude if geo else None, "lon": geo.longitude if geo else None,
            "image": image, "free": free, "price": price, "age_min": None, "age_max": None,
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


def next_page(page, page_url, number):
    """Page suivante d'une liste : lien rel="next", sinon lien vers « page/N/ » ou « ?page=N » (pagination WordPress…)."""
    match = NEXT_LINK.search(page)
    if match:
        return urljoin(page_url, html.unescape(match.group(1) or match.group(2)))
    pattern = re.compile(rf"""href=["']([^"']*(?:/page/{number}/?|[?&](?:page|paged)={number})(?:[&#][^"']*)?)["']""")
    match = pattern.search(page)
    return urljoin(page_url, html.unescape(match.group(1))) if match else None


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
    price = (offers.get("price") or offers.get("lowPrice")) if isinstance(offers, dict) else None
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

    `known_fresh` : pages d'événements déjà vues il y a peu (ou écartées récemment), qu'on ne retélécharge pas.
    """
    items, seen, detail_urls, page_url = [], set(), [], source.url
    pattern = re.compile(source.link_pattern) if source.link_pattern else None
    for _page in range(max(1, source.max_pages)):
        page = fetcher.get(page_url)
        if page.lstrip().startswith("["):  # liste de l'API WordPress (/wp-json/wp/v2/<type>) : liens des pages
            try:
                detail_urls += [i["link"] for i in json.loads(page) if isinstance(i, dict) and i.get("link")]
            except ValueError:
                pass
            break
        if pattern:
            for href in re.findall(r"""href=["']([^"'#]+)["']""", page):
                link = urljoin(page_url, html.unescape(href))
                if pattern.search(link):
                    detail_urls.append(link)
        for node in ld_blocks(page):
            if is_event(node):
                event = ld_event(node, page_url)
                if event and event["url"] not in seen:
                    seen.add(event["url"])
                    items.append(event)
            elif node.get("@type") == "ListItem" and node.get("url") and not isinstance(node.get("item"), dict):
                detail_urls.append(urljoin(page_url, node["url"]))
        following = next_page(page, page_url, _page + 2)
        if not following:
            break
        page_url = following
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


# API WordPress de la Ville de Nice (nice.fr, opera-nice.org : même modèle, champs ACF « event_dates »…) ------------------

WP_SKIP_TYPES = {"permanence", "depistage", "reunion-dinformation", "groupe-de-paroles", "formation"}
WP_COORDS = re.compile(r"\|(-?\d+\.\d+),(-?\d+\.\d+)")
WP_PRICE = re.compile(r"(\d+(?:[,.]\d+)?)\s*(?:€|euros?)")


def wp_date(day, at):
    if not day:
        return None
    try:
        when = datetime.strptime(day, "%Y%m%d")
    except ValueError:
        return None
    if at:
        try:
            when = datetime.combine(when.date(), time.fromisoformat(at[:8]))
        except ValueError:
            pass
    return timezone.make_aware(when)


def wp_place(fetcher, root, place_id):
    """Lieu de l'API (titre, adresse, coordonnées tirées des liens d'itinéraire), gardé une semaine en cache."""
    from django.core.cache import cache

    key = f"agg:wp-place:{root}:{place_id}"
    place = cache.get(key)
    if place is None:
        try:
            data = json.loads(fetcher.get(f"{root}/wp-json/wp/v2/place/{place_id}"))
        except (ValueError, FetchError):
            data = {}
        acf = data.get("acf") or {}
        address = acf.get("address") or {}
        coords = WP_COORDS.search(json.dumps(acf.get("route_links") or ""))
        place = {"place": clean((data.get("title") or {}).get("rendered")), "address": clean(address.get("street_address")),
                 "city": clean(address.get("city")), "postcode": clean(address.get("postal_code")),
                 "lat": float(coords.group(1)) if coords else None, "lon": float(coords.group(2)) if coords else None}
        cache.set(key, place, 7 * 86400)
    return place


WP_MEDIA_PER_SCAN = 60  # requêtes d'images par scan : les suivantes attendent le prochain scan


def wp_media(fetcher, root, media_id, budget):
    """Adresse de l'image mise en avant (taille moyenne-grande si elle existe), gardée un mois en cache."""
    from django.core.cache import cache

    if not media_id:
        return ""
    key = f"agg:wp-media:{root}:{media_id}"
    url = cache.get(key)
    if url is None:
        if budget[0] <= 0:
            return ""
        budget[0] -= 1
        try:
            data = json.loads(fetcher.get(f"{root}/wp-json/wp/v2/media/{media_id}", params={"_fields": "source_url,media_details"}))
            sizes = (data.get("media_details") or {}).get("sizes") or {}
            url = next((sizes[s]["source_url"] for s in ("large", "medium_large", "full") if s in sizes), data.get("source_url") or "")
        except (ValueError, FetchError, KeyError, TypeError, AttributeError):
            url = ""
        cache.set(key, url, 30 * 86400)
    return url


def read_wpnice(source, fetcher):
    root = source.url.split("/wp-json/")[0]
    endpoint = source.url.split("?")[0]
    types = {}
    try:
        for t in json.loads(fetcher.get(f"{root}/wp-json/wp/v2/event_types", params={"per_page": 100})):
            types[t["id"]] = t["slug"]
    except (ValueError, KeyError, TypeError, FetchError):
        pass
    now = timezone.now()
    items = []
    media_budget = [WP_MEDIA_PER_SCAN]
    for page in range(1, max(1, source.max_pages) + 1):
        try:
            batch = json.loads(fetcher.get(endpoint, params={
                "per_page": 100, "page": page, "orderby": "modified", "order": "desc",
                "_fields": "id,link,title,excerpt,acf,event_types,featured_media"}))
        except (FetchError, ValueError):
            break
        if not isinstance(batch, list) or not batch:
            break
        upcoming_in_page = 0
        for ev in batch:
            acf = ev.get("acf") or {}
            if acf.get("archived"):
                continue
            slugs = [types.get(t, "") for t in ev.get("event_types") or []]
            if slugs and all(s in WP_SKIP_TYPES for s in slugs):
                continue
            dates = []
            for d in acf.get("event_dates") or []:
                start = wp_date(d.get("start_date"), d.get("start_time"))
                end = wp_date(d.get("end_date") or (d.get("start_date") if d.get("end_time") else None), d.get("end_time"))
                if start and (end or start) >= now:
                    dates.append((start, end, d.get("status") or ""))
            if not dates:
                continue
            upcoming_in_page += 1
            start, end, status = min(dates, key=lambda x: x[0])
            all_day = not any(d.get("start_time") for d in acf.get("event_dates") or [])
            place = wp_place(fetcher, root, acf["place"]) if isinstance(acf.get("place"), int) else {}
            pricing = clean(acf.get("pricing"))
            price = WP_PRICE.search(pricing)
            items.append({
                "id": str(ev["id"]), "url": ev.get("link") or source.website,
                "title": clean((ev.get("title") or {}).get("rendered")),
                "description": clean((ev.get("excerpt") or {}).get("rendered")),
                "start": start, "end": end if end and end > start else None, "all_day": all_day,
                "place": place.get("place") or clean(acf.get("location")), "address": place.get("address", ""),
                "city": place.get("city", ""), "postcode": place.get("postcode", ""),
                "lat": place.get("lat"), "lon": place.get("lon"),
                "image": wp_media(fetcher, root, ev.get("featured_media"), media_budget) if source.images_allowed else "",
                "free": True if acf.get("free") else None,
                "price": float(price.group(1).replace(",", ".")) if price and not acf.get("free") and float(price.group(1).replace(",", ".")) > 0 else None,
                "age_min": None, "age_max": None, "keywords": " ".join(s.replace("-", " ") for s in slugs),
                "cancelled": status in ("canceled", "cancelled"),
            })
        if upcoming_in_page < 5:  # les pages suivantes, moins récemment modifiées, sont des archives
            break
    return items, False


# The Events Calendar (extension WordPress très répandue chez les communes) : API REST publique -------------------------

OCCURRENCE = re.compile(r"/\d{4}-\d{2}-\d{2}/?$")


def tribe_date(value, tz):
    if not value:
        return None
    try:
        naive = datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    try:
        from zoneinfo import ZoneInfo

        return naive.replace(tzinfo=ZoneInfo(tz or "Europe/Paris"))
    except (KeyError, ValueError):
        return timezone.make_aware(naive)


def read_tribe(source, fetcher):
    """Événements à venir, toutes pages ; une série répétée (une URL par date) ne garde que sa prochaine date."""
    root = source.url.split("/wp-json/")[0].rstrip("/")
    endpoint = f"{root}/wp-json/tribe/events/v1/events"
    today = timezone.localdate().isoformat()
    series = {}
    for page in range(1, max(1, source.max_pages) * 4 + 1):
        try:
            data = json.loads(fetcher.get(endpoint, params={"per_page": 50, "page": page, "start_date": today},
                                          check_robots=False))
        except (FetchError, ValueError):
            break
        for ev in data.get("events") or []:
            venue = ev.get("venue") if isinstance(ev.get("venue"), dict) else {}
            start = tribe_date(ev.get("start_date"), ev.get("timezone"))
            if start is None:
                continue
            end = tribe_date(ev.get("end_date"), ev.get("timezone"))
            cost = clean(ev.get("cost"))
            values = (ev.get("cost_details") or {}).get("values") or []
            free = True if re.search(r"gratuit|free|libre", cost, re.I) or values == ["0"] else None
            price = None
            if not free and values:
                try:
                    price = float(str(values[0]).replace(",", "."))
                except ValueError:
                    price = None
            base = OCCURRENCE.sub("/", ev.get("url") or "")
            item = {
                "id": base or str(ev.get("id")), "url": ev.get("url") or base,
                "title": clean(ev.get("title")), "description": clean(ev.get("excerpt")) or clean(ev.get("description")),
                "start": start, "end": end if end and end > start else None, "all_day": bool(ev.get("all_day")),
                "place": clean(venue.get("venue")), "address": clean(venue.get("address")), "city": clean(venue.get("city")),
                "postcode": clean(venue.get("zip")), "lat": _float(venue.get("geo_lat")), "lon": _float(venue.get("geo_lng")),
                "image": ((ev.get("image") or {}).get("sizes", {}).get("large") or ev.get("image") or {}).get("url", "")
                if isinstance(ev.get("image"), dict) else "",
                "free": free, "price": price or None, "age_min": None, "age_max": None,
                "keywords": " ".join(c.get("name", "") for c in ev.get("categories") or []),
                "cancelled": False,
            }
            if base not in series or start < series[base]["start"]:
                series[base] = item
        if page >= int(data.get("total_pages") or 1):
            break
    return list(series.values()), True


READERS = {"ical": read_ical, "jsonld": read_jsonld, "openagenda": read_openagenda, "wpnice": read_wpnice, "tribe": read_tribe}
