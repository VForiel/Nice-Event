"""Transforme les événements lus par les connecteurs en événements du site (création, mise à jour, disparition)."""

import hashlib
import html
import logging
import math
import re
from datetime import timedelta

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.utils import timezone

from core.markdown import plain
from core.text import normalize
from events.models import Category, Event
from venues import geocode
from venues.models import Commune, Venue

from .connectors import READERS, page_details, price_from_text
from .fetch import Fetcher, FetchError

log = logging.getLogger(__name__)

MAX_SPAN = timedelta(days=45)  # au-delà, c'est une saison entière (animation hebdomadaire…) : on ne l'affiche pas
KEEP_PAST = timedelta(days=180)
SUMMARY = 200
MAX_DETAIL_PAGES = 40  # pages d'événements ouvertes par scan pour trouver image ou prix (le reste aux scans suivants)
DETAILS_MEMORY = 14 * 86400

# Mots-clés -> catégorie (texte sans accents) ; les deux premières catégories trouvées sont retenues.
KEYWORDS = [
    ("cinema", ["cinema", "film", "projection", "cine "]),
    ("expo", ["exposition", "expo ", "musee", "vernissage", "galerie"]),
    ("marche", ["marche", "brocante", "vide grenier", "puces", "foire", "salon"]),
    ("humour", ["humour", "stand up", "one man", "one woman", "humoriste", "comedy"]),
    ("concert", ["concert", "musique", "jazz", "rock", "world tour", "tournee", "en live", "orchestre", "recital", "chorale", "symphon", "piano", "rap ",
                 "MusicEvent"]),
    ("spectacle", ["theatre", "spectacle", "danse", "opera", "ballet", "cirque", "marionnette", "TheaterEvent",
                   "DanceEvent", "performance"]),
    ("match", ["competition sportive", "championnat", " match "]),
    ("festival", ["festival", "Festival"]),
    ("traditions", ["fete ", "halloween", "commemoration", "carnaval", "festin", "feu d artifice", "procession", "fete de", "noel"]),
    ("gastronomie", ["degustation", "gastronom", "vin ", "oenolog", "repas", "diner", "food", "FoodEvent"]),
    ("atelier", ["atelier", "stage ", "cours ", "initiation", "masterclass"]),
    ("conference", ["conference", "rencontre", "debat", "table ronde", "lecture", "visite guidee", "EducationEvent"]),
    ("plein-air", ["randonnee", "balade", "nature", "sentier"]),
    ("sport", ["course", "marathon", "trail", "tournoi", "regate", "SportsEvent"]),
    ("bien-etre", ["yoga", "meditation", "bien etre", "sophrologie"]),
    ("solidarite", ["solidaire", "benevol", "collecte", "don du sang"]),
    ("jeux", ["jeux", "jeu de societe", "escape game", "gaming"]),
    ("langues", ["language", "langue", "english", "tandem"]),
    ("famille", ["enfant", "famille", "jeune public", "conte", "ChildrensEvent"]),
    ("soiree", ["soiree", "dj ", "clubbing", "party"]),
]


def guess_categories(item, default):
    text = f" {normalize(item['title'])} {normalize(item['description'][:400])} {normalize(item.get('keywords', ''))} "
    raw = item.get("keywords", "")
    found = []
    for slug, words in KEYWORDS:
        if any((w in raw) if w[:1].isupper() else (w in text) for w in words):
            found.append(slug)
        if len(found) == 2:
            break
    cats = list(Category.objects.filter(slug__in=found))
    if not cats:
        cats = [default] if default else list(Category.objects.filter(slug="autre"))
    return cats


class Places:
    """Rapprochement ville / code postal / coordonnées -> commune des Alpes-Maritimes ou Monaco."""

    def __init__(self):
        self.communes = list(Commune.objects.all())
        self.by_name = {normalize(c.name): c for c in self.communes}
        self.by_postcode = {}
        for c in self.communes:
            for code in c.postcodes.split(","):
                self.by_postcode.setdefault(code, []).append(c)

    def commune(self, item, default):
        city = normalize(item.get("city") or "")
        if city in self.by_name:
            return self.by_name[city]
        for candidate in self.by_postcode.get((item.get("postcode") or "").strip(), []):
            if not city or normalize(candidate.name) in city or city in normalize(candidate.name):
                return candidate
        if len(self.by_postcode.get((item.get("postcode") or "").strip(), [])) == 1:
            return self.by_postcode[item["postcode"].strip()][0]
        address = normalize(f"{item.get('address', '')} {item.get('place', '')}")
        for name, commune in sorted(self.by_name.items(), key=lambda kv: -len(kv[0])):
            if len(name) > 3 and f" {name} " in f" {address} ":
                return commune
        if item.get("lat") is not None and item.get("lon") is not None:
            nearest = min(self.communes, key=lambda c: (c.lat - item["lat"]) ** 2 + ((c.lon - item["lon"]) * 0.72) ** 2)
            distance = math.hypot(nearest.lat - item["lat"], (nearest.lon - item["lon"]) * 0.72) * 111
            if distance < 8:
                return nearest
        return default


def venue_for(item, commune, default_place=""):
    name = (place_name(item) or default_place or commune.name)[:120]
    address = (item.get("address") or "")[:200]
    venue = Venue.objects.filter(name__iexact=name, commune=commune, address__iexact=address).first()
    if venue:
        return venue
    lat, lon = item.get("lat"), item.get("lon")
    precise = lat is not None and lon is not None
    if not precise:
        lat, lon, precise = geocode.locate(address or name, commune)
    return Venue.objects.create(name=name, address=address, commune=commune, lat=lat, lon=lon, precise=precise)


def flat(text):
    """Minuscules et apostrophes droites, sans changer la longueur (les positions restent valables)."""
    return text.lower().replace("’", "'")


def strip_tail(text, tail):
    tail = (tail or "").strip()
    if len(tail) >= 4:
        at = flat(text).rfind(" " + flat(tail))
        if at > len(text) // 3 and at + len(tail) + 1 >= len(text.rstrip(" .")):
            return text[:at].rstrip(" -–,·")
    return text


def place_name(item):
    """Nom du lieu sans la ville collée à la fin (« Place de l'Église Saorge » -> « Place de l'Église »)."""
    return strip_tail((item.get("place") or "").strip(), item.get("city"))


def clean_title(item):
    """Certains agendas collent le lieu et la ville à la fin du titre (« Concert de piano Place de l'Église Saorge »)."""
    title = item["title"].strip()
    for tail in (item.get("city"), item.get("place"), place_name(item)):
        title = strip_tail(title, tail)
    return title


def excerpt(text):
    text = html.unescape(plain(text or ""))  # Markdown réécrit « & » en « &amp; »
    if len(text) <= SUMMARY:
        return text
    return text[: SUMMARY - 1].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def duplicate_of(item, commune, exclude_source):
    """Même titre, même jour, même commune, déjà présent (publié par un membre ou via une autre source)."""
    day = timezone.localtime(item["start"]).date()
    title = normalize(item["title"])
    candidates = Event.objects.filter(venue__commune=commune, starts_at__date=day).exclude(source=exclude_source)
    return next((e for e in candidates if normalize(e.title) == title), None)


SKIP_MEMORY = 7 * 86400


def skip_key(source, url):
    return f"agg:skip:{source.pk}:{hashlib.sha1(url.encode()).hexdigest()}"


class Known:
    """Pages à ne pas retélécharger : vues il y a moins de 20 h, ou écartées (passées, hors zone) depuis moins d'une semaine."""

    def __init__(self, source, fresh):
        self.source, self.fresh = source, fresh

    def __contains__(self, url):
        return url in self.fresh or cache.get(skip_key(self.source, url)) is not None


def remember_skip(source, item):
    if source.kind == "jsonld" and item.get("url"):
        cache.set(skip_key(source, item["url"]), 1, SKIP_MEMORY)


def details_page(source, item, fetcher):
    """Image et prix lus sur la page de l'événement ; None si elle n'est pas à ouvrir (déjà essayée, page générale)."""
    url = item.get("url") or ""
    if not url.startswith("http") or url.rstrip("/") in {(source.website or "").rstrip("/"), source.url.rstrip("/")}:
        return None
    key = f"agg:details:{hashlib.sha1(url.encode()).hexdigest()}"
    if cache.get(key) is not None:
        return None
    cache.set(key, 1, DETAILS_MEMORY)
    try:
        return page_details(fetcher.get(url), url)
    except Exception as exc:  # page en erreur ou interdite par robots.txt : on fait sans
        log.info("Page %s non lue : %s", url, exc)
        return {"image": "", "free": None, "price": None}


def scan(source, fetcher=None):
    """Lit une source et met à jour ses événements ; renvoie le compte rendu et met à jour la source."""
    fetcher = fetcher or Fetcher()
    now = timezone.now()
    stats = {"found": 0, "created": 0, "updated": 0, "skipped": 0, "duplicates": 0, "outside": 0}
    places = Places()
    try:
        reader = READERS[source.kind]
        if source.kind == "jsonld":
            fresh = set(source.events.filter(updated_at__gte=now - timedelta(hours=20)).values_list("external_url", flat=True))
            items, complete = reader(source, fetcher, known_fresh=Known(source, fresh))
        else:
            items, complete = reader(source, fetcher)
    except (FetchError, ValueError, KeyError) as exc:
        source.last_run_at, source.last_ok, source.last_message = now, False, str(exc)[:2000]
        source.save(update_fields=["last_run_at", "last_ok", "last_message"])
        raise
    seen = set()
    budget = {"pages": MAX_DETAIL_PAGES}
    title_filter = re.compile(source.title_pattern) if source.title_pattern else None
    for item in items:
        stats["found"] += 1
        external_id = str(item["id"])[:300]
        seen.add(external_id)
        if item.get("unchanged"):
            source.events.filter(external_id=external_id).update(missing_since=None, updated_at=now)
            continue
        if title_filter and not title_filter.search(item.get("title") or ""):
            stats["skipped"] += 1
            continue
        start, end = item["start"], item.get("end")
        if end and end <= start:
            # « 19 h – 0 h » saisi sur un seul jour : la fin est le lendemain (au-delà, fin incohérente ignorée)
            end = end + timedelta(days=1) if end + timedelta(days=1) > start else None
        if not item.get("title") or (end or start) < now or (end and end - start > MAX_SPAN and "expo" not in normalize(item["title"])):
            stats["skipped"] += 1
            remember_skip(source, item)
            continue
        commune = places.commune(item, source.default_commune)
        if commune is None:
            stats["outside"] += 1
            remember_skip(source, item)
            continue
        existing = Event.objects.filter(source=source, external_id=external_id).first()
        if existing is None and duplicate_of(item, commune, source):
            stats["duplicates"] += 1
            continue
        event = existing or Event(source=source, external_id=external_id)
        event.title = clean_title(item)[:140]
        event.summary = excerpt(item["description"]) or f"{item['title'][:150]} — voir le site de l'organisateur."
        event.description = ""  # seul un court extrait est repris ; le détail reste chez la source
        full = item.get("full")
        if full:  # source partenaire (AJC06) : tout est repris
            event.summary = excerpt(full["summary"] or full["description"]) or event.summary
            event.description = full["description"]
            event.title_en, event.summary_en = full["title_en"][:140], excerpt(full["summary_en"])
            event.description_en = full["description_en"]
            event.ticket_url = full["ticket_url"][:500]
            event.organizer_name = full["organizer"][:120]
            if full["language"] in Event.Language.values:
                event.language = full["language"]
        event.external_url = item["url"][:500]
        event.starts_at, event.end, event.all_day = start, end, bool(item.get("all_day"))
        event.venue = venue_for(item, commune, source.default_place)
        if not item.get("free") and not item.get("price"):
            item["free"], item["price"] = price_from_text(item.get("description"))
        if item.get("free"):
            event.price_kind = Event.Price.FREE
        elif item.get("price"):
            event.price_kind, event.price_min = Event.Price.PAID, item["price"]
        else:
            event.price_kind = Event.Price.UNKNOWN
        if item.get("age_min"):
            event.age_kind, event.age_min, event.age_max = Event.Age.RANGE if item.get("age_max") else Event.Age.FROM, item["age_min"], item.get("age_max")
        event.state = Event.State.CANCELLED if item.get("cancelled") else Event.State.SCHEDULED
        if not full:
            event.organizer_name = ""
        event.missing_since = None
        if event.status == Event.Status.HIDDEN and event.moderation_note.startswith("Absent de la source"):
            event.status, event.moderation_note = Event.Status.PUBLISHED, ""
        if existing is None:
            event.status = Event.Status.PUBLISHED
        event.save()
        wanted = list(Category.objects.filter(slug__in=full["categories"])) if full and full["categories"] else None
        if wanted:
            event.categories.set(wanted)
        elif existing is None:
            event.categories.set(guess_categories(item, source.default_category))
        stats["created" if existing is None else "updated"] += 1
        wants_image = source.images_allowed and not event.photo and not item.get("image")
        if not full and (wants_image or event.price_kind == Event.Price.UNKNOWN) and budget["pages"] > 0:
            details = details_page(source, item, fetcher)
            if details is not None:
                budget["pages"] -= 1
                if wants_image and details["image"]:
                    item["image"] = details["image"]
                if event.price_kind == Event.Price.UNKNOWN and (details["free"] or details["price"]):
                    if details["free"]:
                        event.price_kind = Event.Price.FREE
                    else:
                        event.price_kind, event.price_min = Event.Price.PAID, details["price"]
                    event.save(update_fields=["price_kind", "price_min"])
        image = item.get("image") or ""
        if full and event.photo and image != event.external_image:
            # Source partenaire : l'affiche a changé (ou a été retirée) depuis le dernier scan, on suit.
            event.photo.delete(save=False)
            event.photo = ""
            event.external_image = ""
            event.save(update_fields=["photo", "external_image"])
        if source.images_allowed and image and not event.photo:
            try:
                data = fetcher.get(image, binary=True)
                event.external_image = image[:500]
                event.photo.save(f"{source.slug}-{event.pk}.jpg", ContentFile(data), save=True)
            except (FetchError, OSError, ValueError) as exc:
                log.info("Image non reprise pour %s : %s", event.pk, exc)
    if complete:
        # Disparu du flux : « peut-être annulé », puis masqué s'il manque encore 24 h plus tard.
        missing = source.events.filter(ends_at__gte=now, status=Event.Status.PUBLISHED).exclude(external_id__in=seen)
        missing.filter(missing_since__isnull=True).update(missing_since=now)
        missing.filter(missing_since__lt=now - timedelta(hours=24)).update(
            status=Event.Status.HIDDEN, moderation_note="Absent de la source depuis plus de 24 h")
    source.events.filter(ends_at__lt=now - KEEP_PAST).delete()
    source.last_empty_runs = 0 if stats["found"] else source.last_empty_runs + 1
    source.last_run_at, source.last_ok = now, True
    source.last_found, source.last_created, source.last_updated = stats["found"], stats["created"], stats["updated"]
    source.last_message = (f"{stats['found']} trouvés, {stats['created']} nouveaux, {stats['updated']} mis à jour, "
                           f"{stats['duplicates']} doublons, {stats['outside']} hors zone, {stats['skipped']} ignorés "
                           f"(passés ou trop longs) ; {fetcher.count} requêtes.")
    # Seulement les champs du compte rendu : ne pas réécrire une demande de scan posée ou effacée entre-temps.
    source.save(update_fields=["last_empty_runs", "last_run_at", "last_ok", "last_found", "last_created",
                               "last_updated", "last_message"])
    return source.last_message


def scan_all():
    from .models import Source

    report, failed = [], []
    fetcher = Fetcher()
    for source in Source.objects.filter(is_active=True):
        try:
            report.append(f"{source.name} : {scan(source, fetcher)}")
        except Exception as exc:  # une source en panne n'empêche pas les autres
            log.exception("Scan de %s en échec", source.name)
            failed.append(f"{source.name} : {exc}")
    if failed:
        raise RuntimeError("\n".join(failed + report))
    return "\n".join(report) or "Aucune source active"
