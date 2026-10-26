"""Espace de gestion de l'équipe (/gestion/), en français uniquement : modération, événements, signalements,
membres et réglages du site."""

import logging
import smtplib
import socket
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.core.mail import EmailMessage
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from community.models import Notification, Profile, Report
from community.notify import notify
from core.jobs import JOBS
from core.models import ContactMessage, JobRun
from core.text import normalize
from events.models import Event
from siteconfig.forms import SiteConfigForm, TestEmailForm, snapshot
from siteconfig.mail import backend_for
from siteconfig.models import ConfigChange, SiteConfig

log = logging.getLogger(__name__)
User = get_user_model()


def smtp_error_message(exc):
    """Message compréhensible pour les erreurs d'envoi les plus courantes."""
    if isinstance(exc, (smtplib.SMTPAuthenticationError, smtplib.SMTPServerDisconnected)):
        return ("Le serveur a refusé l'identifiant ou le mot de passe (Gmail coupe la connexion dans ce cas). "
                "Avec Google : identifiant = vrai compte (pas un alias), validation en deux étapes activée et "
                "mot de passe d'application de 16 lettres.")
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionRefusedError)):
        return "Serveur injoignable : vérifie le nom du serveur, le port et la sécurité (465 = SSL, 587 = STARTTLS)."
    return f"{exc.__class__.__name__} — {exc}"


staff_required = user_passes_test(lambda u: u.is_active and u.is_staff, login_url="community:login")
superuser_required = user_passes_test(lambda u: u.is_active and u.is_superuser, login_url="community:login")


def back(request, default):
    target = request.POST.get("next", "")
    return redirect(target if target.startswith("/gestion/") else default)


@staff_required
def dashboard(request):
    from core.management.commands.worker import load_jobs

    load_jobs()
    runs = {r.name: r for r in JobRun.objects.all()}
    now = timezone.now()
    return render(request, "gestion/dashboard.html", {
        "config": SiteConfig.get(),
        "pending": Event.objects.filter(status=Event.Status.PENDING).count(),
        "reports": Report.objects.filter(handled=False).count(),
        "unread": ContactMessage.objects.filter(handled=False).count(),
        "counts": {
            "upcoming": Event.objects.published().filter(ends_at__gte=now).count(),
            "internal": Event.objects.published().internal().filter(ends_at__gte=now).count(),
            "members": Profile.objects.filter(user__is_active=True).count(),
            "week": Event.objects.filter(created_at__gte=now - timedelta(days=7)).internal().count(),
        },
        "jobs": [(name, runs.get(name)) for name in JOBS],
    })


# Modération -------------------------------------------------------------------------------------------------------


@staff_required
def moderation(request):
    items = (Event.objects.filter(status=Event.Status.PENDING).select_related("venue__commune", "organizer__profile")
             .prefetch_related("categories").order_by("created_at"))
    return render(request, "gestion/moderation.html", {"items": items})


@staff_required
@require_POST
def moderate(request, pk):
    event = get_object_or_404(Event, pk=pk)
    decision = request.POST.get("decision")
    series = Event.objects.filter(series=event.series) if event.series else Event.objects.filter(pk=event.pk)
    if decision == "approve":
        with transaction.atomic():
            series.filter(status=Event.Status.PENDING).update(status=Event.Status.PUBLISHED, published_at=timezone.now())
            if event.organizer_id:
                Profile.objects.filter(user_id=event.organizer_id).update(trusted=True)
        if event.organizer:
            notify(event.organizer, request.user, Notification.Verb.APPROVED, event)
        messages.success(request, f"« {event.title} » est en ligne ; {event.display_organizer or 'son auteur'} publie désormais directement.")
    elif decision == "reject":
        note = request.POST.get("note", "").strip()[:300]
        series.update(status=Event.Status.HIDDEN, moderation_note=note)
        if event.organizer:
            notify(event.organizer, request.user, Notification.Verb.REJECTED, event, message=note)
        messages.success(request, f"« {event.title} » est refusé.")
    return back(request, "gestion:moderation")


# Événements ---------------------------------------------------------------------------------------------------------


@staff_required
def events(request):
    q = request.GET.get("q", "").strip()
    kind = request.GET.get("type", "")
    items = Event.objects.select_related("venue__commune", "organizer__profile", "source").order_by("-created_at")
    if kind == "a-venir":
        items = items.filter(ends_at__gte=timezone.now()).order_by("starts_at")
    elif kind == "masques":
        items = items.filter(status=Event.Status.HIDDEN)
    elif kind == "selection":
        items = items.filter(featured=True)
    elif kind == "externes":
        items = items.external()
    for word in normalize(q).split()[:5]:
        items = items.filter(search__contains=word)
    page = Paginator(items, 50).get_page(request.GET.get("page"))
    return render(request, "gestion/events.html", {"page": page, "q": q, "type": kind})


@staff_required
@require_POST
def event_action(request, pk):
    event = get_object_or_404(Event, pk=pk)
    action = request.POST.get("action")
    if action == "feature":
        event.featured = not event.featured
        event.save(update_fields=["featured"])
    elif action == "hide":
        event.status = Event.Status.HIDDEN
        event.moderation_note = request.POST.get("note", "")[:300] or event.moderation_note
        event.save(update_fields=["status", "moderation_note"])
    elif action == "show":
        event.status = Event.Status.PUBLISHED
        event.save(update_fields=["status", "published_at"])
    return back(request, "gestion:events")


# Diffusion sur les réseaux ----------------------------------------------------------------------------------------


@staff_required
def diffuse(request, pk):
    from social.forms import DiffusionForm
    from social.models import Post
    from social.service import claim, send
    from social.visuals import visual_url

    event = get_object_or_404(Event.objects.select_related("venue__commune"), pk=pk)
    config = SiteConfig.get()
    form = DiffusionForm(request.POST or None, event=event, config=config)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        at = data["scheduled_at"] if data["when"] == "later" else timezone.now()
        posts = [Post.objects.create(event=event, network=n, text=data[f"text_{n}"].strip(), scheduled_at=at,
                                     created_by=request.user) for n in data["chosen"]]
        if data["when"] == "now":
            for post in posts:
                if claim(post.pk):
                    send(post)
            done = [p for p in posts if Post.objects.get(pk=p.pk).status == Post.Status.PUBLISHED]
            if len(done) == len(posts):
                messages.success(request, f"Publié sur {', '.join(p.get_network_display() for p in posts)}.")
            else:
                messages.warning(request, "Certaines publications ont échoué : détail ci-dessous.")
        else:
            messages.success(request, f"Programmé le {timezone.localtime(at):%d/%m à %H:%M} ({len(posts)} réseau(x)).")
        return redirect("gestion:diffuse", pk=event.pk)
    return render(request, "gestion/diffuse.html", {
        "event": event, "form": form, "config": config,
        "previews": [(fmt, visual_url(event, fmt)) for fmt in ("portrait", "paysage", "story")],
        "posts": event.posts.select_related("created_by__profile")[:30],
    })


@staff_required
def posts(request):
    from social.models import Post

    items = Post.objects.select_related("event", "created_by__profile").order_by("-scheduled_at")
    page = Paginator(items, 50).get_page(request.GET.get("page"))
    return render(request, "gestion/posts.html", {"page": page})


@staff_required
@require_POST
def post_action(request, pk):
    from social.models import Post

    post = get_object_or_404(Post, pk=pk)
    action = request.POST.get("action")
    if action == "cancel" and post.status == Post.Status.SCHEDULED:
        post.status = Post.Status.CANCELLED
        post.save(update_fields=["status"])
    elif action == "retry" and post.status in (Post.Status.FAILED, Post.Status.CANCELLED):
        post.status, post.attempts, post.scheduled_at = Post.Status.SCHEDULED, 0, timezone.now()
        post.save(update_fields=["status", "attempts", "scheduled_at"])
        messages.success(request, "Relancée : la tâche de fond s'en occupe dans la minute.")
    return back(request, "gestion:posts")


@superuser_required
@require_POST
def test_network(request, network):
    from social.networks import check

    config = SiteConfig.get()
    if not config.network_ready(network):
        messages.warning(request, "Active le réseau et enregistre ses identifiants avant de le tester.")
    else:
        ok, message = check(network, config)
        (messages.success if ok else messages.error)(request, f"{network.capitalize()} : {message}")
    return redirect("gestion:settings")


# Sources d'événements externes ----------------------------------------------------------------------------------------


@staff_required
def sources(request):
    from aggregator.models import Source

    return render(request, "gestion/sources.html", {
        "items": Source.objects.annotate(n=Count("events", filter=Q(events__ends_at__gte=timezone.now()))),
        "hours": SiteConfig.get().scan_hours(),
    })


@superuser_required
def source_edit(request, pk=None):
    from aggregator.forms import SourceForm
    from aggregator.models import Source

    source = get_object_or_404(Source, pk=pk) if pk else None
    form = SourceForm(request.POST or None, instance=source)
    if request.method == "POST":
        if request.POST.get("delete") and source:
            source.delete()
            messages.success(request, "Source supprimée, avec ses événements.")
            return redirect("gestion:sources")
        if form.is_valid():
            source = form.save(commit=False)
            source.scan_requested = True
            source.save()
            messages.success(request, "Source enregistrée : premier scan dans la minute.")
            return redirect("gestion:sources")
    return render(request, "gestion/source_form.html", {"form": form, "source": source})


@staff_required
@require_POST
def source_scan(request, pk):
    from aggregator.models import Source

    Source.objects.filter(pk=pk).update(scan_requested=True)
    messages.success(request, "Scan demandé : la tâche de fond s'en charge dans la minute.")
    return redirect("gestion:sources")


# Signalements -----------------------------------------------------------------------------------------------------


@staff_required
def reports(request):
    items = Report.objects.select_related("reporter__profile", "event", "profile").order_by("handled", "-created_at")[:200]
    return render(request, "gestion/reports.html", {"items": items})


@staff_required
@require_POST
def report_toggle(request, pk):
    item = get_object_or_404(Report, pk=pk)
    item.handled = not item.handled
    item.save(update_fields=["handled"])
    return back(request, "gestion:reports")


# Membres ----------------------------------------------------------------------------------------------------------


@staff_required
def members(request):
    q = request.GET.get("q", "").strip()
    people = (Profile.objects.select_related("user").annotate(n_events=Count("user__organized_events"))
              .order_by("-created_at"))
    if q:
        people = people.filter(Q(display_name__icontains=q) | Q(user__email__icontains=q))
    page = Paginator(people, 50).get_page(request.GET.get("page"))
    return render(request, "gestion/members.html", {"page": page, "q": q})


@staff_required
@require_POST
def member_action(request, pk):
    profile = get_object_or_404(Profile.objects.select_related("user"), pk=pk)
    action = request.POST.get("action")
    if profile.user.is_superuser and action == "deactivate":
        messages.error(request, "Un superutilisateur ne se désactive que dans l'admin Django.")
    elif action == "trust":
        profile.trusted = not profile.trusted
        profile.save(update_fields=["trusted"])
    elif action == "confirm":
        profile.email_confirmed = True
        profile.save(update_fields=["email_confirmed"])
    elif action == "deactivate":
        profile.user.is_active = not profile.user.is_active
        profile.user.save(update_fields=["is_active"])
        if not profile.user.is_active:
            Event.objects.filter(organizer=profile.user, status=Event.Status.PUBLISHED).update(
                status=Event.Status.HIDDEN, moderation_note="Compte désactivé")
    return back(request, "gestion:members")


# Réglages ---------------------------------------------------------------------------------------------------------


@superuser_required
def settings_view(request):
    config = SiteConfig.get()
    before = snapshot(config)
    form = SiteConfigForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            changed = form.changed_labels(before)
            if changed:
                ConfigChange.objects.create(user=request.user, fields=", ".join(changed))
        messages.success(request, "Réglages enregistrés." if changed else "Aucun changement.")
        return redirect("gestion:settings")
    from social.models import Network

    return render(request, "gestion/settings.html", {
        "form": form, "config": config, "networks": Network.choices,
        "test_form": TestEmailForm(initial={"to": request.user.email}),
        "changes": ConfigChange.objects.select_related("user")[:10],
    })


@superuser_required
@require_POST
def test_email(request):
    form = TestEmailForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Adresse de test invalide.")
        return redirect("gestion:settings")
    config = SiteConfig.get()
    if not config.smtp_ready:
        messages.warning(request, "Aucun serveur SMTP réglé : le courriel n'est parti que dans les journaux du site.")
    message = EmailMessage(
        "Nice-Event : courriel de test",
        "Ce message confirme que le site sait envoyer des courriels avec les réglages actuels.\n\n— nice-event.fr",
        config.from_email,
        [form.cleaned_data["to"]],
        connection=backend_for(config),
    )
    try:
        message.send()
    except (smtplib.SMTPException, OSError, socket.timeout) as exc:
        log.warning("Courriel de test en échec : %s", exc)
        messages.error(request, f"Échec de l'envoi : {smtp_error_message(exc)}")
    else:
        if config.smtp_ready:
            messages.success(request, f"Courriel de test envoyé à {form.cleaned_data['to']}. Vérifie aussi les indésirables.")
    return redirect("gestion:settings")
