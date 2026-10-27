"""Page « Filtres & alertes » : composer un filtre, l'utiliser pour la session dans l'agenda et la carte, l'enregistrer
(membres) et recevoir une alerte quand un nouvel événement y correspond."""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from core.security import client_ip, throttled
from events import rules
from events.models import Category, Event, SavedFilter
from events.views import SESSION_FILTER, WHEN, base_queryset
from siteconfig.models import SiteConfig
from venues.models import Commune, Zone

from . import send
from .models import Channel, PushSubscription

MAX_SAVED = 30
MAX_RULE = 8000


def spec(request):
    """Description des conditions pour l'éditeur (JS) : listes de valeurs et libellés."""
    groups = rules.source_groups()
    return {
        "fields": [[k, str(label), str(hint)] for k, label, hint in rules.FIELDS],
        "categorie": [[c.slug, str(c.name_tr)] for c in Category.objects.all()],
        "zone": [[k, str(v)] for k, v in Zone.choices],
        "commune": list(Commune.objects.order_by("name").values_list("slug", "name")),
        "source": [[rules.NICE_EVENT, "Nice-Event"]] + [list(g) for g in groups],
        "prix": [[k, str(v)] for k, v in Event.Price.choices],
        "public": [[k, str(v)] for k, v in rules.PUBLICS],
        "langue": [[k, str(v)] for k, v in rules.LANGUAGES],
        "quand": [[k, str(v)] for k, v in WHEN],
        "jour": [[str(k), str(v)] for k, v in rules.WEEKDAYS],
        "urls": {"preview": reverse("alerts:preview"), "geocode": reverse("events:api_geocode"),
                 "save": reverse("alerts:save")},
        "today": timezone.localdate().isoformat(),
        "labels": {
            "and": _("Toutes ces conditions (ET)"), "or": _("Au moins une de ces conditions (OU)"),
            "not": _("Sauf"), "notTitle": _("Inverser : garder ce qui ne correspond pas"),
            "addRule": _("Condition"), "addGroup": _("Groupe"), "remove": _("Retirer"),
            "pick": _("Quel critère ?"), "pickFilter": _("Filtrer : âge, prix, type=adresse…"),
            "noField": _("Aucun critère ne correspond."), "close": _("Fermer"),
            "empty": _("Aucune condition pour l'instant : ajoute-en une avec « + Condition »."),
            "search": _("Chercher…"), "from": _("de"), "to": _("à"), "hourFrom": _("entre"), "hourTo": _("h et"),
            "hour": _("h"), "km": _("km au plus de"), "here": _("Ma position"), "address": _("Adresse, lieu, commune…"),
            "euros": _("€ au plus"), "years": _("ans"), "ageFrom": _("de"), "words": _("mots à chercher"),
            "dateFrom": _("du"), "dateTo": _("au"), "accessible": _("Lieu accessible en fauteuil roulant"),
            "regexHelp": _("Recherché dans le titre, le résumé, la description et le lieu, sans tenir compte des majuscules. Exemples :"),
            "regexBad": _("Motif invalide"), "count0": _("Aucun événement à venir ne correspond."),
            "count1": _("1 événement à venir correspond."), "countN": _("%(n)s événements à venir correspondent."),
            "incomplete": _("Complète au moins une condition pour voir l'aperçu."),
            "nameMissing": _("Donne un nom à ton filtre."), "saved": _("Filtre enregistré."),
            "update": _("Mettre à jour ce filtre"), "saveNew": _("Enregistrer ce filtre"),
            "editing": _("Modification de « %(name)s »"), "deleteConfirm": _("Supprimer ce filtre ?"),
            "error": _("Enregistrement impossible, réessaie."), "pushDenied": _("Notifications refusées par le navigateur."),
            "pushOn": _("Cet appareil recevra les alertes."),
            "noAlert": _("Sans alerte"),
        },
    }


def filters_page(request):
    current = request.session.get(SESSION_FILTER) or {}
    context = {"spec": spec(request), "current": current}
    if request.user.is_authenticated:
        channels = {c.kind: c for c in Channel.objects.filter(user=request.user)}
        config = SiteConfig.get()
        context.update({
            "saved": SavedFilter.objects.filter(user=request.user),
            "frequencies": SavedFilter.Frequency.choices,
            "channels": channels,
            "email_on": channels[Channel.Kind.EMAIL].is_active if Channel.Kind.EMAIL in channels else True,
            "telegram_ready": bool(config.telegram_bot_token), "telegram_bot": config.telegram_bot_name,
            "vapid_key": send.vapid_keys()["public"],
            "push_count": PushSubscription.objects.filter(user=request.user).count(),
        })
    return render(request, "alerts/filters.html", context)


def checked_rule(raw):
    if not raw or len(raw) > MAX_RULE:
        return None
    rule = rules.parse(raw)
    if not rule or rules.Compiler().node(rule) is None:
        return None
    return rule


@require_POST
def use(request):
    """Garde le filtre pour la session et ouvre l'agenda ou la carte."""
    saved = None
    if request.POST.get("saved") and request.user.is_authenticated:
        saved = SavedFilter.objects.filter(user=request.user, pk=request.POST["saved"]).first()
    rule = saved.rule if saved else checked_rule(request.POST.get("rule"))
    if not rule:
        messages.error(request, _("Ce filtre est vide : ajoute au moins une condition complète."))
        return redirect("alerts:filters")
    name = saved.name if saved else (request.POST.get("name", "").strip()[:80] or _("Mon filtre"))
    request.session[SESSION_FILTER] = {"name": name, "rule": rule, "id": saved.pk if saved else None}
    return redirect("events:map" if request.POST.get("to") == "carte" else "events:list")


@require_POST
def clear(request):
    request.session.pop(SESSION_FILTER, None)
    target = request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = reverse("events:list")
    return redirect(target)


@require_GET
def preview(request):
    """Nombre d'événements à venir qui correspondent, et les premiers, pour l'aperçu en direct de l'éditeur."""
    if throttled(f"filter-preview:{client_ip(request)}", 600, 3600):
        return JsonResponse({"error": _("Trop de requêtes, patiente un peu.")}, status=429)
    raw = request.GET.get("regle", "")
    rule = rules.parse(raw) if len(raw) <= MAX_RULE else None
    errors = [rules.regex_error(str(leaf.get("value", ""))) for leaf in leaves(rule) if leaf.get("field") == "regex"]
    errors = [e for e in errors if e]
    if not rule or errors:
        return JsonResponse({"count": None, "errors": errors})
    events = rules.matches(rule, base_queryset())
    from core.templatetags.ne import day_short

    return JsonResponse({"count": events.count(), "errors": [], "events": [
        {"title": e.title_tr, "url": e.get_absolute_url(), "when": day_short(e.local_start),
         "place": e.venue.commune.name} for e in events[:5]]})


def leaves(rule):
    if not isinstance(rule, dict):
        return []
    if "rules" in rule:
        return [leaf for child in rule.get("rules") or [] for leaf in leaves(child)]
    return [rule]


@login_required
@require_POST
def save(request):
    """Enregistre le filtre (nouveau, ou mise à jour de celui en cours de modification)."""
    name = request.POST.get("name", "").strip()[:80]
    rule = checked_rule(request.POST.get("rule"))
    if not name or not rule:
        return JsonResponse({"error": _("Donne un nom au filtre et au moins une condition complète.")}, status=400)
    mine = SavedFilter.objects.filter(user=request.user)
    saved = mine.filter(pk=request.POST.get("id") or 0).first() or mine.filter(name=name).first()
    if saved is None and mine.count() >= MAX_SAVED:
        return JsonResponse({"error": _("Trente filtres au plus : supprimes-en un.")}, status=400)
    if saved is None:
        saved = SavedFilter(user=request.user)
    if mine.filter(name=name).exclude(pk=saved.pk).exists():
        return JsonResponse({"error": _("Tu as déjà un filtre de ce nom.")}, status=400)
    saved.name, saved.rule = name, rule
    if "alert" in request.POST:
        set_alert(saved, request.POST.get("alert") == "1", request.POST.get("frequency"))
    saved.save()
    return JsonResponse({"id": saved.pk, "name": saved.name, "alert": saved.alert})


def set_alert(saved, on, frequency=None):
    if on and not saved.alert:
        saved.alert_since = timezone.now()  # pas d'avalanche : seuls les événements publiés à partir de maintenant
    saved.alert = on
    if frequency in SavedFilter.Frequency.values:
        saved.frequency = frequency


@login_required
@require_POST
def alert(request, pk):
    saved = get_object_or_404(SavedFilter, user=request.user, pk=pk)
    set_alert(saved, request.POST.get("alert") == "1", request.POST.get("frequency"))
    saved.save(update_fields=["alert", "alert_since", "frequency"])
    return JsonResponse({"id": saved.pk, "alert": saved.alert, "frequency": saved.frequency})


@login_required
@require_POST
def delete(request, pk):
    SavedFilter.objects.filter(user=request.user, pk=pk).delete()
    current = request.session.get(SESSION_FILTER) or {}
    if current.get("id") == pk:
        request.session.pop(SESSION_FILTER, None)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def channels(request):
    """Canaux de réception des alertes (formulaire classique, on revient sur la section)."""
    post, user = request.POST, request.user
    webhook = post.get("discord_webhook", "").strip()
    chat = post.get("telegram_chat", "").strip()
    errors = []
    if webhook and not send.DISCORD_WEBHOOK.match(webhook):
        errors.append(_("L'adresse du webhook Discord doit commencer par https://discord.com/api/webhooks/…"))
    if chat and not send.TELEGRAM_CHAT.match(chat):
        errors.append(_("L'identifiant Telegram est un nombre (ou @nom_de_canal)."))
    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect(reverse("alerts:filters") + "#canaux")
    values = {
        Channel.Kind.EMAIL: (bool(post.get("email")), {}),
        Channel.Kind.DISCORD: (bool(post.get("discord")) and bool(webhook), {"webhook": webhook}),
        Channel.Kind.TELEGRAM: (bool(post.get("telegram")) and bool(chat), {"chat_id": chat}),
        Channel.Kind.PUSH: (bool(post.get("push")), {}),
    }
    for kind, (active, config) in values.items():
        Channel.objects.update_or_create(user=user, kind=kind, defaults={"is_active": active, "config": config})
    if post.get("test"):
        report = send.test(user)
        for name, result in report.items():
            (messages.success if result == "ok" else messages.error)(
                request, _("Essai %(canal)s : %(r)s") % {"canal": name, "r": _("envoyé") if result == "ok" else result})
    else:
        messages.success(request, _("Canaux d'alerte enregistrés."))
    return redirect(reverse("alerts:filters") + "#canaux")


@login_required
@require_POST
def push_subscribe(request):
    try:
        data = json.loads(request.body)
        endpoint, keys = data["endpoint"], data["keys"]
        PushSubscription.objects.update_or_create(endpoint=endpoint[:1000], defaults={
            "user": request.user, "p256dh": keys["p256dh"][:200], "auth": keys["auth"][:100]})
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "abonnement illisible"}, status=400)
    Channel.objects.update_or_create(user=request.user, kind=Channel.Kind.PUSH, defaults={"is_active": True})
    return JsonResponse({"ok": True})


@require_GET
def service_worker(request):
    """Service worker des notifications du navigateur, servi à la racine pour couvrir tout le site."""
    body = """self.addEventListener("push", function (event) {
  var data = {};
  try { data = event.data.json(); } catch (e) { data = { title: "Nice-Event", body: event.data ? event.data.text() : "" }; }
  event.waitUntil(self.registration.showNotification(data.title || "Nice-Event", {
    body: data.body || "", tag: data.tag, icon: "/static/img/apple-touch-icon.png", badge: "/static/img/apple-touch-icon.png",
    data: { url: data.url || "/" }
  }));
});
self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url));
});
"""
    response = HttpResponse(body, content_type="application/javascript")
    response["Cache-Control"] = "no-cache"
    return response
