"""Géocodage par le service de la Géoplateforme (IGN, Base Adresse Nationale) : gratuit, sans clé, données publiques.

Appelé côté serveur uniquement (le navigateur ne contacte jamais de service tiers) : suggestions d'adresses du
formulaire de publication (/api/adresses/) et position des lieux à l'enregistrement. Monaco n'est pas couvert par la
BAN : on y place le lieu au centre de la commune.
"""

import json
import logging
import urllib.parse
import urllib.request

from django.core.cache import cache

log = logging.getLogger(__name__)
URL = "https://data.geopf.fr/geocodage/search"
HEADERS = {"User-Agent": "Nice-Event/1.0 (+https://nice-event.fr)"}


def search(query, citycode="", limit=5):
    """Adresses de la BAN, limitées aux Alpes-Maritimes : [{label, name, citycode, lat, lon, score}]."""
    query = " ".join(query.split())[:200]
    if len(query) < 3:
        return []
    key = f"geocode:{citycode}:{limit}:{query.lower()}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    params = {"q": query, "limit": limit, "index": "address"}
    if citycode:
        params["citycode"] = citycode
    else:
        params.update({"lat": 43.70, "lon": 7.27})  # priorité aux résultats proches de Nice
    try:
        req = urllib.request.Request(f"{URL}?{urllib.parse.urlencode(params)}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as response:
            features = json.load(response).get("features", [])
    except (OSError, ValueError) as exc:
        log.warning("Géocodage indisponible : %s", exc)
        return []
    results = []
    for feature in features:
        props = feature.get("properties", {})
        if not str(props.get("citycode", "")).startswith("06"):
            continue
        lon, lat = feature["geometry"]["coordinates"]
        results.append({"label": props.get("label", ""), "name": props.get("name", ""), "city": props.get("city", ""),
                        "citycode": props.get("citycode", ""), "lat": lat, "lon": lon, "score": props.get("score", 0)})
    cache.set(key, results, 86400)
    return results


def locate(address, commune):
    """(lat, lon, précis) d'une adresse dans une commune ; centre de la commune à défaut."""
    if address and commune.insee.startswith("06"):
        found = search(f"{address} {commune.name}", citycode=commune.insee, limit=1)
        if found and found[0]["score"] >= 0.4:
            return found[0]["lat"], found[0]["lon"], True
    return commune.lat, commune.lon, False
