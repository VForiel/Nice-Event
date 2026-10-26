import uuid
from datetime import datetime, time, timedelta
from itertools import groupby

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
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
from core.text import normalize
from venues import geocode
from venues.models import Commune, Venue, Zone, zone_filter

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


def filtered(request, events):
    """Applique les filtres de l'URL ; renvoie (événements, filtres actifs)."""
    params = request.GET
    active = {}
    when = params.get("quand", "")
    start, end = window(when)
    if start:
        events = events.between(start, end)
        active["quand"] = when
    cats = [c for c in params.getlist("categorie") if c]
    if cats:
        events = events.filter(categories__slug__in=cats).distinct()
        active["categorie"] = cats
    zone = params.get("zone", "")
    if zone in Zone.values:
        events = events.filter(zone_filter(zone))
        active["zone"] = zone
    commune = params.get("commune", "")
    if commune:
        events = events.filter(venue__commune__slug=commune)
        active["commune"] = commune
    if params.get("gratuit"):
        events = events.filter(price_kind=Event.Price.FREE)
        active["gratuit"] = "1"
    if params.get("en"):
        events = events.filter(Q(language__in=[Event.Language.INTERNATIONAL, Event.Language.NONE]) | Q(spoken__contains="en"))
        active["en"] = "1"
    if params.get("famille"):
        events = events.filter(age_kind__in=[Event.Age.ALL, Event.Age.FAMILY])
        active["famille"] = "1"
    origin = params.get("source", "")
    if origin == "membres":
        events = events.internal()
        active["source"] = origin
    elif origin == "externes":
        events = events.external()
        active["source"] = origin
    q = params.get("q", "").strip()
    if q:
        for word in normalize(q).split()[:6]:
            events = events.filter(search__contains=word)
        active["q"] = q
    return events, active


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


def by_day(events):
    """[(jour, [événements])] ; un événement déjà commencé est rangé aujourd'hui."""
    today = timezone.localdate()
    return [(day, list(items)) for day, items in groupby(events, key=lambda e: max(e.local_start.date(), today))]


def event_list(request):
    events, active = filtered(request, base_queryset())
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
    return render(request, "events/list.html", {
        "days": by_day(items), "count": len(items), "more": more, "next_page": page + 1, "active": active,
        "categories": Category.objects.all(), "zones": Zone.choices, "when_choices": WHEN,
        "communes": Commune.objects.filter(venues__events__isnull=False).distinct().order_by("name"),
        "query": query.urlencode(), "map_query": query.urlencode(),
    })


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
        "share_text": share_text(event),
    }
    if request.user.is_authenticated:
        friends = list(friends_of(request.user))
        going_ids = {u.pk for u in attendees}
        context.update({
            "is_going": request.user.pk in going_ids,
            "friends_going": [f for f in friends if f.pk in going_ids],
            "invitable": [f for f in friends if f.pk not in going_ids],
        })
    return render(request, "events/detail.html", context)


def og_image_url(request, event):
    from django.templatetags.static import static

    return request.build_absolute_uri(event.photo.url if event.photo else static("img/og-default.png"))


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
            weeks = form.occurrences()
            if len(weeks) > 1:
                first.series = uuid.uuid4()
            first.save()
            form.save_m2m()
            Attendance.objects.get_or_create(event=first, user=request.user)
            for week in weeks[1:]:
                copy_occurrence(first, timedelta(weeks=week))
        if moderated:
            for staff in staff_users():
                notify(staff, request.user, Notification.Verb.TO_MODERATE, first)
        return redirect("events:published", slug=first.slug)
    return render(request, "events/form.html", {"form": form})


def staff_users():
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(is_staff=True, is_active=True)


def copy_occurrence(event, delta):
    cats = list(event.categories.all())
    copy = Event.objects.get(pk=event.pk)
    copy.pk = None
    copy.slug = ""
    copy.starts_at = event.starts_at + delta
    copy.end = event.end + delta if event.end else None
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
    return render(request, "events/map.html", {
        "categories": Category.objects.all(), "when_choices": WHEN, "zones": Zone.choices,
        "active": filtered(request, Event.objects.none())[1], "data_query": query.urlencode(),
    })


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
