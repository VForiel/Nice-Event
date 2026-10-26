"""Filtre avancé : combinaisons logiques de conditions (ET / OU / SAUF), passées dans l'adresse (?regle=…) en JSON.

    {"op": "and", "rules": [
        {"field": "categorie", "in": ["concert", "soiree"]},
        {"op": "or", "not": true, "rules": [{"field": "prix", "in": ["paid"]}, {"field": "zone", "in": ["monaco"]}]},
        {"field": "proximite", "lat": 43.7, "lon": 7.26, "km": 5, "label": "Nice"}
    ]}

Chaque condition (ou groupe) peut être inversée avec "not". Une règle mal formée est ignorée, sans erreur.
"""

import json
import math

from django.db.models import F, FloatField, Q, Value
from django.db.models.functions import Power, Sqrt
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core.text import normalize
from venues.models import Zone, zone_filter

from .models import Event

MAX_DEPTH = 4
MAX_CONDITIONS = 40
NICE_EVENT = "nice-event"  # pseudo-source : événements publiés sur le site

FIELDS = [
    ("categorie", _("Catégorie")),
    ("quand", _("Période")),
    ("jour", _("Jour de la semaine")),
    ("heure", _("Heure de début")),
    ("zone", _("Zone")),
    ("commune", _("Commune")),
    ("proximite", _("À proximité de")),
    ("prix", _("Prix")),
    ("prix_max", _("Prix maximum")),
    ("age", _("Adapté à l'âge")),
    ("public", _("Public")),
    ("anglais", _("EN friendly")),
    ("accessible", _("Accessible en fauteuil")),
    ("source", _("Source")),
    ("texte", _("Contient les mots")),
]
WEEKDAYS = [(1, _("lundi")), (2, _("mardi")), (3, _("mercredi")), (4, _("jeudi")), (5, _("vendredi")),
            (6, _("samedi")), (7, _("dimanche"))]


def source_groups():
    """[(clé, nom)] des sources externes actives, regroupées par nom (tous les groupes Meetup = « Meetup »)."""
    from aggregator.models import Source

    names = sorted(set(Source.objects.filter(is_active=True).values_list("name", flat=True)), key=normalize)
    return [(slugify(name), name) for name in names]


def source_q(keys, groups=None):
    """Q() des événements venant des sources demandées (clés de source_groups, ou « nice-event »)."""
    names = dict(groups if groups is not None else source_groups())
    q = Q(source__name__in=[names[k] for k in keys if k in names])
    if NICE_EVENT in keys:
        q |= Q(source__isnull=True)
    return q


def parse(raw):
    """Texte JSON de l'adresse -> règle (dict) ou None."""
    if not raw:
        return None
    try:
        rule = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return rule if isinstance(rule, dict) else None


class Compiler:
    def __init__(self):
        self.aliases = {}
        self.count = 0
        self._groups = None

    @property
    def groups(self):
        if self._groups is None:
            self._groups = source_groups()
        return self._groups

    def node(self, rule, depth=0):
        if not isinstance(rule, dict) or depth > MAX_DEPTH:
            return None
        if "rules" in rule:
            children = rule["rules"] if isinstance(rule["rules"], list) else []
            parts = [q for q in (self.node(r, depth + 1) for r in children) if q is not None]
            if not parts:
                return None
            q = parts[0]
            for part in parts[1:]:
                q = (q | part) if rule.get("op") == "or" else (q & part)
        else:
            self.count += 1
            if self.count > MAX_CONDITIONS:
                return None
            q = self.leaf(rule)
            if q is None:
                return None
        return ~q if rule.get("not") else q

    def leaf(self, rule):
        field = rule.get("field")
        values = rule.get("in") if isinstance(rule.get("in"), list) else []
        values = [str(v) for v in values][:60]
        if field == "categorie" and values:
            through = Event.categories.through.objects.filter(category__slug__in=values)
            return Q(pk__in=through.values("event_id"))
        if field == "zone" and values:
            q = Q()
            for zone in values:
                if zone in Zone.values:
                    q |= zone_filter(zone)
            return q or None
        if field == "commune" and values:
            return Q(venue__commune__slug__in=values)
        if field == "source" and values:
            return source_q(values, self.groups)
        if field == "prix" and values:
            return Q(price_kind__in=[v for v in values if v in Event.Price.values])
        if field == "public" and values:
            return Q(age_kind__in=[v for v in values if v in Event.Age.values])
        if field == "jour" and values:
            return Q(starts_at__iso_week_day__in=[int(v) for v in values if v.isdigit() and 1 <= int(v) <= 7])
        if field == "quand":
            from .views import window

            start, end = window(str(rule.get("value", "")))
            return Q(starts_at__lt=end, ends_at__gte=start) if start else None
        if field == "heure":
            low, high = number(rule.get("min"), 0, 23), number(rule.get("max"), 0, 23)
            if low is None and high is None:
                return None
            q = Q(all_day=False)
            if low is not None:
                q &= Q(starts_at__hour__gte=int(low))
            if high is not None:
                q &= Q(starts_at__hour__lte=int(high))
            return q
        if field == "prix_max":
            limit = number(rule.get("value"), 0, 100000)
            if limit is None:
                return None
            return (Q(price_kind__in=[Event.Price.FREE, Event.Price.PWYW])
                    | Q(price_kind=Event.Price.PAID, price_min__lte=limit))
        if field == "age":
            age = number(rule.get("value"), 0, 120)
            if age is None:
                return None
            q = (Q(age_min__isnull=True) | Q(age_min__lte=age)) & (Q(age_max__isnull=True) | Q(age_max__gte=age))
            if age < 18:
                q &= ~Q(age_kind=Event.Age.ADULTS)
            return q
        if field == "anglais":
            return Q(language__in=[Event.Language.INTERNATIONAL, Event.Language.NONE]) | Q(spoken__contains="en")
        if field == "accessible":
            return Q(accessible=Event.Access.YES)
        if field == "texte":
            words = normalize(str(rule.get("value", ""))).split()[:6]
            if not words:
                return None
            q = Q()
            for word in words:
                q &= Q(search__contains=word)
            return q
        if field == "proximite":
            lat, lon = number(rule.get("lat"), 40, 46), number(rule.get("lon"), 4, 10)
            km = number(rule.get("km"), 0.1, 200)
            if lat is None or lon is None or km is None:
                return None
            name = f"_distance{len(self.aliases)}"
            # Distance à plat (équirectangulaire) : largement assez précise à l'échelle du département.
            self.aliases[name] = Sqrt(
                Power(F("venue__lat") - Value(lat, FloatField()), 2)
                + Power((F("venue__lon") - Value(lon, FloatField())) * Value(math.cos(math.radians(lat)), FloatField()), 2)
            ) * Value(111.2, FloatField())
            return Q(**{f"{name}__lte": km})
        return None


def number(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if low <= value <= high and not math.isnan(value) else None


def apply(events, rule):
    """Filtre le queryset avec la règle ; renvoie (événements, règle appliquée ?)."""
    compiler = Compiler()
    q = compiler.node(rule)
    if q is None:
        return events, False
    if compiler.aliases:
        events = events.alias(**compiler.aliases)
    return events.filter(q), True
