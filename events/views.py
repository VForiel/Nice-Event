import uuid
from datetime import datetime, time, timedelta
from itertools import groupby

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, DateTimeField, F, Q, Value
from django.db.models.functions import Greatest
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET, require_POST

from community import confirmation
from community.models import Attendance, Notification, friend_ids, friends_of
from community.notify import notify
from core.images import thumbnail_url
from core.security import throttled
from venues import geocode
from venues.models import Commune, Venue, Zone

from . import rules
from .forms import EventForm
from .ical import calendar
from .models import Category, Event
from .seo import event_jsonld

EVENTS_PER_DAY = 5
PAGE = 60

WHEN = [
    ("aujourdhui", gettext_lazy("Aujourd'hui")),
    ("demain", gettext_lazy("Demain")),
    ("weekend", gettext_lazy("Ce week-end")),
    ("semaine", gettext_lazy("7 prochains jours")),
    ("mois", gettext_lazy("30 prochains jours")),
]


def window(when, now=None):
    """(début, fin) de la période demandée, en heure de Paris ; (None, None) pour « tout ce qui vient »."""
    now = timezone.localtime(now or timezone.now())
    today = now.date()

    def at(day, hour=0, minute=0):
        return timezone.make_aware(datetime.combine(day, time(hour, minute)))

    if when == "aujourdhui":
        return now, at(today + timedelta(days=1), 5)  # les soirées qui finissent après minuit comptent pour ce soir
    if when == "demain":
        return at(today + timedelta(days=1), 5), at(today + timedelta(days=2), 5)
    if when == "weekend":
        weekday = today.weekday()  # lundi = 0
        friday = today + timedelta(days=(4 - weekday) % 7) if weekday <= 4 else today - timedelta(days=weekday - 4)
        start = max(now, at(friday, 18))
        return start, at(friday + timedelta(days=3), 5)
    if when == "semaine":
        return now, at(today + timedelta(days=7), 5)
    if when == "mois":
        return now, at(today + timedelta(days=30), 5)
    try:
        day = datetime.strptime(when, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None, None
    return max(now, at(day, 5)), at(day + timedelta(days=1), 5)


SESSION_FILTER = "filtre_perso"


def custom_filter(request):
    """Filtre personnalisé composé sur la page « Filtres & alertes » et gardé pour la session : {name, rule, id}."""
    data = request.session.get(SESSION_FILTER)
    return data if isinstance(data, dict) and rules.parse(data.get("rule")) else None


def filtered(request, events):
    """Applique les menus de l'adresse puis le filtre personnalisé de la session ; renvoie (événements, état)."""
    groups = rules.source_groups()
    state = rules.bar_state(request.GET, groups)
    events, applied = rules.apply(events, rules.bar_rule(state))
    custom = custom_filter(request)
    if custom:
        events, _custom_applied = rules.apply(events, custom["rule"])
    state.update({"groups": groups, "custom": custom, "any": applied or bool(custom)})
    return events, state


def base_queryset():
    return (Event.objects.published().upcoming().select_related("venue__commune", "source", "organizer__profile")
            .prefetch_related("categories"))


def friends_going(user, events):
    """{id d'événement: nombre d'amis qui y vont}."""
    if not user.is_authenticated:
        return {}
    ids = friend_ids(user)
    if not ids:
        return {}
    rows = (Attendance.objects.filter(user_id__in=ids, event__in=[e.pk for e in events]).values("event")
            .annotate(n=Count("id")))
    return {r["event"]: r["n"] for r in rows}


def by_day(events, start=None):
    """[(jour, [événements])] ; un événement déjà commencé au début de la période (ou aujourd'hui) y est rangé."""
    first = timezone.localtime(start).date() if start else timezone.localdate()
    return [(day, list(items)) for day, items in groupby(events, key=lambda e: max(e.local_start.date(), first))]


def period_start(state):
    """Début de la période choisie dans le menu « Dates » (jamais avant maintenant)."""
    now = timezone.now()
    if state["quand"] == "dates":
        first = rules.day(state["du"])
        start = timezone.make_aware(datetime.combine(first, time(5, 0))) if first else None
    else:
        start = window(state["quand"])[0] if state["quand"] else None
    return max(start, now) if start else now


def event_list(request):
    events, state = filtered(request, base_queryset())
    # Les expositions et festivals déjà commencés s'affichent au premier jour de la période, pas à leur début
    start = period_start(state)
    events = events.annotate(shown_at=Greatest("starts_at", Value(start, output_field=DateTimeField()))).order_by(
        "shown_at", "starts_at")
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    items = list(events[: PAGE * page + 1])
    more = len(items) > PAGE * page
    items = items[: PAGE * page]
    going = friends_going(request.user, items)
    for e in items:
        e.friends_going = going.get(e.pk, 0)
    query = request.GET.copy()
    query.pop("page", None)
    query.pop("partiel", None)
    context = {"days": by_day(items, start), "count": len(items), "more": more, "next_page": page + 1, "state": state,
               "query": query.urlencode()}
    if request.GET.get("partiel"):
        return render(request, "events/_results.html", context)
    return render(request, "events/list.html", {**context, **filter_context(request, state)})


def filter_context(request, state):
    """Ce qu'il faut à la barre de menus déroulants (agenda et carte)."""
    categories = list(Category.objects.all())
    keys = [rules.NICE_EVENT] + [k for k, _n in state["groups"]]
    return {
        "categories": categories, "zones": Zone.choices, "when_choices": WHEN, "languages": rules.LANGUAGES,
        "publics": rules.PUBLICS, "prices": [c for c in Event.Price.choices],
        "sources": [(rules.NICE_EVENT, "Nice-Event")] + list(state["groups"]),
        "checked_cats": state["categorie"] or [c.slug for c in categories],
        "checked_src": state["src"] or keys,
        "checked_prix": state["prix"] or [k for k, _l in Event.Price.choices],
        "today": timezone.localdate().isoformat(),
    }


def from_source(request, source, external_id):
    """Lien stable vers un événement repris d'une source partenaire (ex. bouton « Voir sur Nice-Event » de l'AJC06)."""
    event = Event.objects.published().filter(source__slug=source, external_id=external_id).first()
    if event is None:
        messages.info(request, _("Cet événement arrive bientôt sur Nice-Event (les agendas partenaires sont relus plusieurs fois par jour)."))
        return redirect("events:list")
    return redirect(event)


def visible_or_404(request, event):
    if event.status == Event.Status.PUBLISHED:
        return
    user = request.user
    if user.is_authenticated and (user.is_staff or event.organizer_id == user.pk):
        return
    raise Http404


def event_detail(request, slug):
    event = get_object_or_404(Event.objects.select_related("venue__commune", "source", "organizer__profile"), slug=slug)
    visible_or_404(request, event)
    if event.status == Event.Status.PUBLISHED:
        Event.objects.filter(pk=event.pk).update(views=F("views") + 1)
    attendees = [a.user for a in Attendance.objects.filter(event=event, user__is_active=True).select_related("user__profile")]
    cats = list(event.categories.all())
    related = base_queryset().exclude(pk=event.pk)
    if cats:
        related = related.filter(categories__in=cats).distinct()
    context = {
        "event": event, "categories": cats, "attendees": attendees, "attendee_count": len(attendees),
        "related": related[:3], "share_url": request.build_absolute_uri(event.get_absolute_url()),
        "series": Event.objects.published().upcoming().filter(series=event.series).exclude(pk=event.pk)[:6]
        if event.series else [],
        "can_edit": request.user.is_authenticated and not event.is_external
        and (event.organizer_id == request.user.pk or request.user.is_staff),
        "jsonld": event_jsonld(event, request.build_absolute_uri(event.photo.url) if event.photo else ""),
        "og_image": og_image_url(request, event),
        "story_url": reverse("events:visual", args=[event.slug, "story"]) + "?telecharger=1",
        "share_text": share_text(event),
    }
    context.update(memories(request, event))
    if request.user.is_authenticated:
        friends = list(friends_of(request.user))
        going_ids = {u.pk for u in attendees}
        context.update({
            "is_going": request.user.pk in going_ids,
            "just_joined": request.session.pop("just_attending", None) == event.pk,
            "friends_going": [f for f in friends if f.pk in going_ids],
            "invitable": [f for f in friends if f.pk not in going_ids],
        })
    return render(request, "events/detail.html", context)


def memories(request, event):
    """Commentaires, notes, photos et vidéos des membres sur la fiche d'un événement."""
    from community.forms import CommentForm
    from community.models import Comment, Media
    from community.views import can_rate

    comments = list(Comment.objects.filter(event=event, is_hidden=False, author__is_active=True)
                    .select_related("author__profile"))
    ratings = [c.rating for c in comments if c.rating]
    rate = can_rate(event)
    return {
        "comments": [c for c in comments if c.body],
        "rating_count": len(ratings),
        "rating_average": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "rating_stars": round(sum(ratings) / len(ratings)) if ratings else 0,
        "my_rating": next((c.rating for c in reversed(comments) if c.rating and c.author_id == request.user.pk), None),
        "can_rate": rate,
        "comment_form": CommentForm(can_rate=rate),
        "media": Media.objects.filter(event=event, is_hidden=False).select_related("uploader__profile"),
    }


def og_image_url(request, event):
    return request.build_absolute_uri(reverse("events:visual", args=[event.slug, "og"]))


VISUALS = {"og", "portrait", "paysage", "story"}


def event_visual(request, slug, fmt):
    """Visuel généré de l'événement (aperçus de liens, story à télécharger, réseaux)."""
    from django.http import FileResponse

    from social.visuals import visual_path

    if fmt not in VISUALS:
        raise Http404
    event = get_object_or_404(Event.objects.select_related("venue__commune"), slug=slug)
    visible_or_404(request, event)
    response = FileResponse(open(visual_path(event, fmt), "rb"), content_type="image/jpeg")
    response["Cache-Control"] = "public, max-age=3600"
    if request.GET.get("telecharger"):
        response["Content-Disposition"] = f'attachment; filename="nice-event-{event.slug}-{fmt}.jpg"'
    return response


def share_text(event):
    """Texte des liens de partage : « Apéro jazz face à la mer — ven. 30 oct., Nice »."""
    from core.templatetags.ne import day_short

    return f"{event.title_tr} — {day_short(event.local_start)}, {event.venue.commune.name}"


# Publication ------------------------------------------------------------------------------------------------------


def needs_moderation(user):
    """Premier événement d'un compte : validé par l'équipe avant publication (membre de confiance ensuite)."""
    return not (user.is_staff or user.profile.trusted)


@login_required
def event_new(request):
    if not confirmation.can_publish(request.user):
        return render(request, "events/confirm_first.html", status=403)
    form = EventForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        if throttled(f"events:{request.user.pk}", EVENTS_PER_DAY, 86400):
            messages.error(request, _("Tu as déjà publié beaucoup d'événements aujourd'hui, réessaie demain."))
            return redirect("events:list")
        moderated = needs_moderation(request.user)
        with transaction.atomic():
            first = form.save(commit=False)
            first.organizer = request.user
            first.status = Event.Status.PENDING if moderated else Event.Status.PUBLISHED
            form.apply(first)
            days = form.occurrences()
            if len(days) > 1:
                first.series = uuid.uuid4()
            first.save()
            form.save_m2m()
            Attendance.objects.get_or_create(event=first, user=request.user)
            for day in days[1:]:
                copy_occurrence(first, day)
        if moderated:
            for staff in staff_users():
                notify(staff, request.user, Notification.Verb.TO_MODERATE, first)
        return redirect("events:published", slug=first.slug)
    return render(request, "events/form.html", {"form": form})


def staff_users():
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(is_staff=True, is_active=True)


def copy_occurrence(event, day):
    """Copie de l'événement le jour donné, à la même heure locale (même après un changement d'heure)."""
    cats = list(event.categories.all())
    copy = Event.objects.get(pk=event.pk)
    copy.pk = None
    copy.slug = ""
    copy.starts_at = timezone.make_aware(datetime.combine(day, event.local_start.time()))
    copy.end = copy.starts_at + (event.end - event.starts_at) if event.end else None
    copy.views = 0
    copy.published_at = None
    copy.save()
    copy.categories.set(cats)
    return copy


@login_required
def event_published(request, slug):
    """« C'est en ligne ! » : la page qui pousse l'organisateur à partager tout de suite."""
    event = get_object_or_404(Event, slug=slug, organizer=request.user)
    return render(request, "events/published.html", {
        "event": event, "share_url": request.build_absolute_uri(event.get_absolute_url()), "share_text": share_text(event),
        "story_url": reverse("events:visual", args=[event.slug, "story"]) + "?telecharger=1",
        "occurrences": Event.objects.filter(series=event.series).count() if event.series else 1,
    })


def own_event(request, slug):
    event = get_object_or_404(Event.objects.select_related("venue__commune"), slug=slug, source__isnull=True)
    if event.organizer_id != request.user.pk and not request.user.is_staff:
        raise PermissionDenied
    return event


@login_required
def event_edit(request, slug):
    event = own_event(request, slug)
    before = (event.starts_at, event.venue_id, event.state)
    form = EventForm(request.POST or None, request.FILES or None, instance=event, user=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            event = form.save(commit=False)
            form.apply(event)
            event.save()
            form.save_m2m()
        if (event.starts_at, event.venue_id, event.state) != before and event.status == Event.Status.PUBLISHED:
            what = {Event.State.CANCELLED: "annulé", Event.State.POSTPONED: "reporté"}.get(event.state, "modifié")
            for attendance in Attendance.objects.filter(event=event).exclude(user=request.user).select_related("user"):
                notify(attendance.user, request.user, Notification.Verb.CHANGED, event, message=what)
        messages.success(request, _("Événement mis à jour."))
        return redirect(event.get_absolute_url())
    return render(request, "events/form.html", {"form": form, "event": event})


@login_required
def event_delete(request, slug):
    event = own_event(request, slug)
    others = Event.objects.filter(series=event.series, starts_at__gt=event.starts_at) if event.series else Event.objects.none()
    if request.method == "POST":
        if request.POST.get("following") and others.exists():
            others.delete()
        event.delete()
        messages.success(request, _("Événement supprimé."))
        return redirect("events:list")
    return render(request, "events/delete.html", {"event": event, "following": others.count()})


@login_required
@require_POST
def attend(request, slug):
    event = get_object_or_404(Event.objects.published().internal(), slug=slug)
    attendance = Attendance.objects.filter(event=event, user=request.user).first()
    if attendance:
        attendance.delete()
    elif not event.is_upcoming:
        messages.error(request, _("Cet événement est passé."))
    elif event.is_full:
        messages.error(request, _("Désolé, c'est complet."))
    elif event.is_cancelled:
        messages.error(request, _("Cet événement est annulé."))
    else:
        Attendance.objects.create(event=event, user=request.user)
        request.session["just_attending"] = event.pk  # la page de l'événement propose une fois de soutenir le site
        if event.organizer_id:
            notify(event.organizer, request.user, Notification.Verb.ATTENDING, event)
    return redirect(event.get_absolute_url() + "#participants")


@login_required
@require_POST
def invite(request, slug):
    event = get_object_or_404(Event.objects.published(), slug=slug)
    allowed = {u.pk: u for u in friends_of(request.user)}
    count = 0
    for pk in request.POST.getlist("friends"):
        friend = allowed.get(int(pk)) if pk.isdigit() else None
        if friend and not Notification.objects.filter(recipient=friend, actor=request.user, verb="invite", event=event).exists():
            notify(friend, request.user, Notification.Verb.INVITE, event)
            count += 1
    messages.success(request, _("Invitation envoyée.") if count == 1 else _("%(n)s invitations envoyées.") % {"n": count})
    return redirect(event.get_absolute_url() + "#participants")


# Lieux, carte, agenda -----------------------------------------------------------------------------------------------


def venue_detail(request, slug):
    venue = get_object_or_404(Venue.objects.select_related("commune"), slug=slug)
    events = base_queryset().filter(venue=venue)
    return render(request, "events/venue.html", {"venue": venue, "days": by_day(events[:PAGE])})


def map_page(request):
    query = request.GET.copy()
    state = filtered(request, Event.objects.none())[1]
    return render(request, "events/map.html", {"state": state, "data_query": query.urlencode(),
                                               **filter_context(request, state)})


def map_point(event, request):
    cat = event.main_category
    start = event.local_start
    return {
        "id": event.pk,
        "title": event.title_tr,
        "url": event.get_absolute_url(),
        "lat": round(event.venue.lat, 5), "lon": round(event.venue.lon, 5),
        "emoji": cat.emoji if cat else "📍", "tone": cat.tone if cat else "nuit",
        "category": cat.name_tr if cat else "",
        "when": f"{_date_short(start)} · {_('Toute la journée') if event.all_day else start.strftime('%H:%M')}",
        "place": f"{event.venue.name}, {event.venue.commune.name}",
        "price": str(event.price_label), "free": event.is_free, "en": event.english_friendly,
        "external": event.source.name if event.source_id else "",
        "cancelled": event.is_cancelled,
        "photo": thumbnail_url(event.photo, 240) if event.photo else "",
    }


def _date_short(dt):
    from core.templatetags.ne import day_short

    return day_short(dt)


@require_GET
def map_data(request):
    events, _active = filtered(request, base_queryset())
    if "quand" not in request.GET:
        events = events.filter(starts_at__lt=timezone.now() + timedelta(days=60))
    points = [map_point(e, request) for e in events[:800]]
    return JsonResponse({"events": points})


def _ics_response(body, filename):
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def event_ics(request, slug):
    event = get_object_or_404(Event.objects.published().select_related("venue__commune"), slug=slug)
    return _ics_response(calendar([event], name=event.title_tr), f"{event.slug}.ics")


@cache_control(max_age=1800)
def agenda_ics(request):
    events, _active = filtered(request, base_queryset())
    return _ics_response(calendar(events[:1000]), "nice-event.ics")


# Aide à la saisie (appelées par le formulaire de publication) ---------------------------------------------------------


@login_required
@require_GET
def api_addresses(request):
    if throttled(f"geocode:{request.user.pk}", 300, 3600):
        return JsonResponse({"results": []})
    commune = Commune.objects.filter(pk=request.GET.get("commune") or 0).first()
    results = geocode.search(request.GET.get("q", ""), citycode=commune.insee if commune and commune.insee.startswith("06") else "")
    communes = dict(Commune.objects.filter(insee__in={r["citycode"] for r in results}).values_list("insee", "pk"))
    for r in results:
        r["commune"] = communes.get(r["citycode"])
    return JsonResponse({"results": results})


@require_GET
def api_geocode(request):
    """Adresses des Alpes-Maritimes pour « près d'une adresse » (filtres) : ouvert à tous, limité par adresse IP."""
    from core.security import client_ip

    if throttled(f"geocode-public:{client_ip(request)}", 120, 3600):
        return JsonResponse({"results": []})
    results = geocode.search(request.GET.get("q", ""))
    return JsonResponse({"results": [{"label": r["label"], "lat": r["lat"], "lon": r["lon"]} for r in results]})


@login_required
@require_GET
def api_venues(request):
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})
    venues = (Venue.objects.filter(Q(name__icontains=q) | Q(address__icontains=q)).select_related("commune")
              .annotate(n=Count("events")).order_by("-n", "name")[:8])
    return JsonResponse({"results": [
        {"id": v.pk, "name": v.name, "address": v.address, "commune": v.commune_id, "commune_name": v.commune.name,
         "lat": v.lat, "lon": v.lon} for v in venues]})


# Ça m'intéresse / Pas pour moi, et page Découvrir ------------------------------------------------------------------

@login_required
@require_POST
def interest(request, slug):
    """Bascule « Ça m'intéresse » (value=yes) ou « Pas pour moi » (value=no) ; recliquer annule."""
    from community.models import EventInterest

    event = get_object_or_404(Event.objects.published(), slug=slug)
    wanted = {"yes": EventInterest.Value.YES, "no": EventInterest.Value.NO}.get(request.POST.get("value"))
    current = EventInterest.objects.filter(event=event, user=request.user).first()
    if wanted is None or (current and current.value == wanted and request.POST.get("keep") != "1"):
        if current:
            current.delete()
        value = 0
    else:
        EventInterest.objects.update_or_create(event=event, user=request.user, defaults={"value": wanted})
        value = int(wanted)
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"value": value})
    back = request.POST.get("next", "")
    if back.startswith("/") and not back.startswith("//"):
        return redirect(back)
    return redirect(event.get_absolute_url())


def discover_card(event):
    """Ce que la page Découvrir affiche d'un événement (rempli côté navigateur, sans rechargement)."""
    from core.templatetags.ne import hours, when

    cat = event.main_category
    return {
        "id": event.pk, "url": event.get_absolute_url(), "title": event.title_tr, "summary": event.summary_tr,
        "when": str(when(event))[:1].upper() + str(when(event))[1:], "hours": str(hours(event)),
        "place": f"{event.venue.name} · {event.venue.commune.name}", "price": str(event.price_label),
        "free": event.is_free, "category": cat.name_tr if cat else "", "tone": cat.tone if cat else "nuit",
        "photo": thumbnail_url(event.photo, 720) if event.photo else "",
        "source": event.source.name if event.source_id else "",
        "interest": reverse("events:interest", args=[event.slug]),
    }


@login_required
def discover(request):
    return render(request, "events/discover.html")


@login_required
@require_GET
def discover_next(request):
    """Les prochains événements à proposer : les plus susceptibles de plaire, avec une part de découverte."""
    from .recommend import recommend

    seen = [int(pk) for pk in request.GET.get("vus", "").split(",") if pk.isdigit()][:500]
    events = recommend(request.user, limit=6, exclude=seen, explore=0.4, per_category=2)
    return JsonResponse({"events": [discover_card(e) for e in events]})
