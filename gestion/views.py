"""Espace de gestion de l'équipe (/gestion/), en français uniquement.

Phase 1 : tableau de bord et réglages du site. Modération, diffusion sur les réseaux et sources externes s'y ajoutent
dans les phases suivantes.
"""

import logging
import smtplib
import socket

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import user_passes_test
from django.core.mail import EmailMessage
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.jobs import JOBS
from core.models import ContactMessage, JobRun
from siteconfig.forms import SiteConfigForm, TestEmailForm, snapshot
from siteconfig.mail import backend_for
from siteconfig.models import ConfigChange, SiteConfig

log = logging.getLogger(__name__)

superuser_required = user_passes_test(lambda u: u.is_active and u.is_superuser, login_url="admin:login")


@staff_member_required
def dashboard(request):
    from core.management.commands.worker import load_jobs

    load_jobs()
    runs = {r.name: r for r in JobRun.objects.all()}
    return render(request, "gestion/dashboard.html", {
        "config": SiteConfig.get(),
        "unread": ContactMessage.objects.filter(handled=False).count(),
        "jobs": [(name, runs.get(name)) for name in JOBS],
    })


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
    return render(request, "gestion/settings.html", {
        "form": form,
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
        messages.error(request, f"Échec de l'envoi : {exc.__class__.__name__} — {exc}")
    else:
        if config.smtp_ready:
            messages.success(request, f"Courriel de test envoyé à {form.cleaned_data['to']}. Vérifie aussi les indésirables.")
    return redirect("gestion:settings")
