"""Recommandations : quels événements à venir ont le plus de chances de plaire à un membre ?

Signaux du membre : « Ça m'intéresse » et « J'y vais » comptent pour (+1), « Pas pour moi » contre (-1).
Chaque événement est décrit par des caractéristiques regroupées en familles :

    cat    ses catégories            (« cat:concert »)
    mot    les mots de son titre     (« mot:jazz »)
    src    son origine               (« src:12 » pour une source, « src:site » pour un événement publié ici)
    lieu   sa commune                (« lieu:88 »)
    prix   gratuit ou payant         (« prix:free »)

Le goût du membre pour une caractéristique est (pour - contre) / (pour + contre + 1) : entre -1 et 1, prudent tant
qu'il y a peu de signaux. Le score d'un événement est la somme, famille par famille, de la moyenne des goûts de ses
caractéristiques multipliée par le poids de la famille, plus un peu de popularité, d'amis et de proximité dans le
temps. Une part d'aléatoire (« exploration ») fait découvrir d'autres choses sur la page Découvrir.
"""

import math
import random
from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from core.text import normalize

from .models import Event

WEIGHTS = {"cat": 3.0, "mot": 1.5, "src": 1.0, "lieu": 1.0, "prix": 0.5}
HORIZON = timedelta(days=60)
MAX_CANDIDATES = 2000
MIN_SIGNALS = 3  # en dessous, pas de section « Recommandé pour toi » sur l'accueil
STOPWORDS = set("""
    avec dans pour sous chez entre leur leurs notre nous vous votre cette ces des les une un aux par plus tout tous
    toute toutes soiree journee edition grand grande petit petite nouvelle nouveau the and for with from your this that
    live night event events tour london nice day edition special presents present feat featuring
""".split())


def words(title):
    return {w for w in normalize(title).split() if len(w) >= 4 and w not in STOPWORDS and not w.isdigit()}


def features(event):
    found = {f"cat:{c.slug}" for c in event.categories.all()}
    found |= {f"mot:{w}" for w in words(event.title)}
    found.add(f"src:{event.source_id or 'site'}")
    found.add(f"lieu:{event.venue.commune_id}")
    found.add(f"prix:{'free' if event.price_kind == Event.Price.FREE else 'paid'}")
    return found


def signals(user):
    """{événement: +1 ou -1} : les intérêts du membre, et ses « J'y vais » comptés comme des « Ça m'intéresse »."""
    from community.models import Attendance, EventInterest

    votes = dict(EventInterest.objects.filter(user=user).values_list("event_id", "value"))
    for event_id in Attendance.objects.filter(user=user).values_list("event_id", flat=True):
        votes.setdefault(event_id, 1)
    return votes


def taste(votes):
    """Goût du membre pour chaque caractéristique, d'après les événements qu'il a notés."""
    pros, cons = Counter(), Counter()
    rated = Event.objects.filter(pk__in=votes).select_related("venue").prefetch_related("categories")
    for event in rated:
        bucket = pros if votes[event.pk] > 0 else cons
        bucket.update(features(event))
    return {f: (pros[f] - cons[f]) / (pros[f] + cons[f] + 1) for f in set(pros) | set(cons)}


def score(event, likes, popularity=0, friends=0, now=None):
    by_family = defaultdict(list)
    for feature in features(event):
        by_family[feature.split(":", 1)[0]].append(likes.get(feature, 0.0))
    total = sum(WEIGHTS[family] * sum(values) / len(values) for family, values in by_family.items())
    days = max(0.0, (event.starts_at - (now or timezone.now())).total_seconds() / 86400)
    return total + 0.3 * math.log1p(popularity) + 0.5 * friends + 0.3 * max(0.0, 1 - days / 30)


def candidates(user, exclude=()):
    """Événements à venir (60 jours) que le membre n'a pas encore notés, avec leur popularité auprès des autres."""
    from community.models import friends_of

    now = timezone.now()
    friends = list(friends_of(user).values_list("pk", flat=True))
    return (Event.objects.published().upcoming().filter(starts_at__lte=now + HORIZON)
            .exclude(pk__in=list(exclude)).exclude(interests__user=user).exclude(attendances__user=user)
            .exclude(state=Event.State.CANCELLED)
            .select_related("venue__commune", "source").prefetch_related("categories")
            .annotate(fans=Count("interests", filter=Q(interests__value=1), distinct=True)
                      + Count("attendances", distinct=True),
                      friends_in=Count("attendances", filter=Q(attendances__user__in=friends), distinct=True))
            .order_by("starts_at")[:MAX_CANDIDATES])


def diverse(ranked, limit, per_category=2):
    """Les meilleurs, sans plus de `per_category` événements de la même catégorie principale (puis le reste)."""
    picked, seen, rest = [], Counter(), []
    for event in ranked:
        main = event.main_category.slug if event.main_category else ""
        if seen[main] < per_category:
            picked.append(event)
            seen[main] += 1
        else:
            rest.append(event)
        if len(picked) == limit:
            return picked
    return (picked + rest)[:limit]


def recommend(user, limit=6, exclude=(), explore=0.0, per_category=2, rng=None):
    """Les `limit` événements les plus susceptibles de plaire, variés ; `explore` ajoute du hasard (0 à 1)."""
    rng = rng or random.Random()
    likes = taste(signals(user))
    now = timezone.now()
    ranked = []
    for event in candidates(user, exclude):
        value = score(event, likes, event.fans, event.friends_in, now) + explore * rng.random() * 3
        ranked.append((value, event))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return diverse([event for _value, event in ranked], limit, per_category)


def for_home(user, limit=6):
    """Section « Recommandé pour toi » de l'accueil : seulement quand on connaît un peu les goûts du membre."""
    if not user.is_authenticated or len(signals(user)) < MIN_SIGNALS:
        return []
    return recommend(user, limit)
