"""Filtres : combinaisons logiques de conditions (ET / OU / SAUF), décrites en JSON.

    {"op": "and", "rules": [
        {"field": "categorie", "in": ["concert", "soiree"]},
        {"op": "or", "not": true, "rules": [{"field": "prix", "in": ["paid"]}, {"field": "zone", "in": ["monaco"]}]},
        {"field": "proximite", "lat": 43.7, "lon": 7.26, "km": 5, "label": "Place Masséna, Nice"},
        {"field": "regex", "value": "\\bski\\b", "not": true}
    ]}

Deux usages : la barre de filtres de l'agenda et de la carte (un menu déroulant = un groupe OU, les menus entre eux en
ET, voir `bar_rule`) et le filtre personnalisé de la page « Filtres & alertes » (gardé dans la session du visiteur,
enregistré et surveillé par une alerte pour les membres). Une règle mal formée est ignorée, sans erreur.
"""

import json
import math
import re
from datetime import date, datetime, time, timedelta

from django.db.models import F, FloatField, Q, Value
from django.db.models.functions import Power, Sqrt
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core.text import normalize
from venues.models import Zone, zone_filter

from .models import Event

MAX_DEPTH = 4
MAX_CONDITIONS = 40
MAX_REGEX = 120
NICE_EVENT = "nice-event"  # pseudo-source : événements publiés sur le site

# (clé, nom, explication courte) : liste des conditions proposées sur la page « Filtres & alertes ».
FIELDS = [
    ("categorie", _("Type d'événement"), _("Concert, soirée, rando, atelier…")),
    ("quand", _("Période"), _("Aujourd'hui, ce week-end, 30 prochains jours…")),
    ("dates", _("Plage de dates"), _("Entre deux dates précises")),
    ("jour", _("Jour de la semaine"), _("Seulement le samedi et le dimanche, par exemple")),
    ("heure", _("Heure de début"), _("Commence entre 18 h et 23 h, par exemple")),
    ("zone", _("Zone"), _("Nice, Métropole, Côte, arrière-pays, Monaco")),
    ("commune", _("Commune"), _("Une ou plusieurs communes")),
    ("proximite", _("Près d'une adresse"), _("À moins de N km d'une adresse ou de ta position")),
    ("prix", _("Prix"), _("Gratuit, prix libre, payant")),
    ("prix_max", _("Prix maximum"), _("Pas plus de N €")),
    ("age_range", _("Tranche d'âge"), _("Adapté à des personnes de N à M ans")),
    ("public", _("Public"), _("Tout public, famille, adultes")),
    ("langue", _("Langue"), _("En français, international, anglais parlé…")),
    ("accessible", _("Accessible en fauteuil"), _("Lieu déclaré accessible")),
    ("source", _("Source"), _("Nice-Event ou un agenda en particulier")),
    ("texte", _("Mots"), _("Contient tous ces mots (sans tenir compte des accents)")),
    ("regex", _("Expression régulière"), _("Motif avancé sur le titre et la description, ex. \\bski\\b")),
]
FIELD_KEYS = {k for k, _l, _h in FIELDS}
WEEKDAYS = [(1, _("lundi")), (2, _("mardi")), (3, _("mercredi")), (4, _("jeudi")), (5, _("vendredi")),
            (6, _("samedi")), (7, _("dimanche"))]
LANGUAGES = [
    ("fr", _("En français")),
    ("international", _("Accessible sans parler français")),
    ("none", _("Sans barrière de langue (musique, sport…)")),
    ("en", _("Anglais parlé sur place")),
]
PUBLICS = [("all", _("Tout public")), ("family", _("Famille et enfants")), ("adults", _("Adultes (18 ans et plus)"))]
# Quantificateur appliqué à un groupe qui en contient déjà un, « (a+)+ » : retour arrière explosif, refusé.
NESTED = re.compile(r"\([^)]*[+*}][^)]*\)\s*[+*{]")


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


def regex_error(pattern):
    """Message d'erreur si le motif est refusé (trop long, invalide, trop coûteux), sinon chaîne vide."""
    if not pattern:
        return str(_("Motif vide."))
    if len(pattern) > MAX_REGEX:
        return str(_("Motif trop long (%(n)s caractères au plus).") % {"n": MAX_REGEX})
    if NESTED.search(pattern):
        return str(_("Motif trop coûteux : évite les répétitions imbriquées comme (a+)+."))
    try:
        re.compile(pattern)
    except re.error as exc:
        return str(_("Motif invalide : %(e)s") % {"e": exc})
    return ""


def parse(raw):
    """Texte JSON -> règle (dict) ou None."""
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        rule = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return rule if isinstance(rule, dict) else None


def number(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if low <= value <= high and not math.isnan(value) else None


def day(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


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

    def leaf(self, rule):  # noqa: C901 (une branche par type de condition)
        field = rule.get("field")
        values = rule.get("in") if isinstance(rule.get("in"), list) else []
        values = [str(v) for v in values][:80]
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
        if field == "langue" and values:
            q = Q(language__in=[v for v in values if v in Event.Language.values])
            if "en" in values:
                q |= Q(spoken__contains="en")
            return q
        if field == "jour" and values:
            return Q(starts_at__iso_week_day__in=[int(v) for v in values if v.isdigit() and 1 <= int(v) <= 7])
        if field == "quand":
            from .views import window

            start, end = window(str(rule.get("value", "")))
            return Q(starts_at__lt=end, ends_at__gte=start) if start else None
        if field == "dates":
            first, last = day(rule.get("from")), day(rule.get("to"))
            if not first and not last:
                return None
            q = Q()
            if first:
                q &= Q(ends_at__gte=timezone.make_aware(datetime.combine(first, time(5, 0))))
            if last:
                q &= Q(starts_at__lt=timezone.make_aware(datetime.combine(last + timedelta(days=1), time(5, 0))))
            return q
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
        if field in ("age", "age_range"):
            # « age » (une seule valeur, ancien format) = tranche réduite à un âge.
            low = number(rule.get("min", rule.get("value")), 0, 120)
            high = number(rule.get("max", rule.get("value")), 0, 120)
            if low is None and high is None:
                return None
            low, high = low if low is not None else 0, high if high is not None else 120
            # L'événement accepte [âge min, âge max] (bornes vides = ouvertes) : il faut un recouvrement.
            q = (Q(age_min__isnull=True) | Q(age_min__lte=high)) & (Q(age_max__isnull=True) | Q(age_max__gte=low))
            if high < 18:
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
        if field == "regex":
            pattern = str(rule.get("value", ""))
            if regex_error(pattern):
                return None
            return (Q(title__iregex=pattern) | Q(summary__iregex=pattern) | Q(description__iregex=pattern)
                    | Q(title_en__iregex=pattern) | Q(venue__name__iregex=pattern))
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


def apply(events, rule):
    """Filtre le queryset avec la règle ; renvoie (événements, règle appliquée ?)."""
    compiler = Compiler()
    q = compiler.node(rule)
    if q is None:
        return events, False
    if compiler.aliases:
        events = events.alias(**compiler.aliases)
    return events.filter(q), True


def matches(rule, events):
    """Événements du queryset qui satisfont la règle (une règle vide ou illisible ne laisse rien passer : alertes)."""
    compiler = Compiler()
    q = compiler.node(rule)
    if q is None:
        return events.none()
    if compiler.aliases:
        events = events.alias(**compiler.aliases)
    return events.filter(q)


# Barre de filtres (agenda et carte) ---------------------------------------------------------------------------------

def bar_state(params, groups):
    """État des menus déroulants lu dans l'adresse. Accepte aussi les anciens paramètres (?gratuit=1, ?source=membres…)."""
    def many(name):
        return [v for v in params.getlist(name) if v]

    state = {
        "categorie": many("categorie"), "quand": params.get("quand", ""), "du": params.get("du", ""),
        "au": params.get("au", ""), "src": many("src"), "zone": many("zone"), "public": many("public"),
        "langue": many("langue"), "prix": many("prix"), "q": params.get("q", "").strip(),
        "age_min": params.get("age_min", ""), "age_max": params.get("age_max", ""),
        "pres": None,
    }
    if state["quand"] == "dates" and not (day(state["du"]) or day(state["au"])):
        state["quand"] = ""
    pres = params.get("pres", "").split(",")
    if len(pres) == 3:
        lat, lon, km = number(pres[0], 40, 46), number(pres[1], 4, 10), number(pres[2], 0.1, 200)
        if None not in (lat, lon, km):
            state["pres"] = {"lat": lat, "lon": lon, "km": km, "label": params.get("pres_label", "")[:120]}
    keys = [NICE_EVENT] + [k for k, _n in groups]
    origin = params.get("source", "")
    if origin == "membres":
        state["src"] = [NICE_EVENT]
    elif origin == "externes":
        state["src"] = [k for k, _n in groups]
    hidden = many("masquer")
    if hidden:
        state["src"] = [k for k in (state["src"] or keys) if k not in hidden]
    if params.get("gratuit"):
        state["prix"] = [Event.Price.FREE]
    if params.get("en"):
        state["langue"] = ["international", "none", "en"]
    if params.get("famille"):
        state["public"] = ["all", "family"]
    return state


def bar_rule(state):
    """Règle équivalente aux menus : OU à l'intérieur d'un menu, ET entre les menus."""
    rules = []
    if state["categorie"]:
        rules.append({"field": "categorie", "in": state["categorie"]})
    if state["quand"] == "dates":
        rules.append({"field": "dates", "from": state["du"], "to": state["au"]})
    elif state["quand"]:
        rules.append({"field": "quand", "value": state["quand"]})
    if state["src"]:
        rules.append({"field": "source", "in": state["src"]})
    place = []
    if state["zone"]:
        place.append({"field": "zone", "in": state["zone"]})
    if state["pres"]:
        place.append({"field": "proximite", **state["pres"]})
    if place:
        rules.append({"op": "or", "rules": place})
    age = []
    if state["public"]:
        age.append({"field": "public", "in": state["public"]})
    if state["age_min"] or state["age_max"]:
        age.append({"field": "age_range", "min": state["age_min"] or None, "max": state["age_max"] or None})
    if age:
        rules.append({"op": "or", "rules": age})
    if state["langue"]:
        rules.append({"field": "langue", "in": state["langue"]})
    if state["prix"]:
        rules.append({"field": "prix", "in": state["prix"]})
    if state["q"]:
        rules.append({"field": "texte", "value": state["q"]})
    return {"op": "and", "rules": rules}
