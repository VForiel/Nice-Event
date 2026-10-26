import logging

from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_GET

from siteconfig.models import SiteConfig

from .forms import ContactForm
from .i18n import is_english
from .models import SUBJECTS
from .security import client_ip, throttled

log = logging.getLogger(__name__)
CONTACTS_PER_HOUR = 5

# Catégories mises en avant sur l'accueil d'attente (la liste complète arrive avec les événements, phase 2).
TEASER_CATEGORIES = [
    ("music", "chaise", gettext_lazy("Concert & musique")),
    ("party", "lavande", gettext_lazy("Soirée & fête")),
    ("sea", "chaise", gettext_lazy("Mer & plage")),
    ("hike", "pin", gettext_lazy("Plein air & rando")),
    ("food", "corail", gettext_lazy("Gastronomie")),
    ("lang", "chaise", gettext_lazy("Échanges linguistiques")),
    ("meet", "corail", gettext_lazy("Rencontres en groupe")),
    ("market", "ocre", gettext_lazy("Marché & brocante")),
    ("show", "corail", gettext_lazy("Spectacle & théâtre")),
    ("kids", "ocre", gettext_lazy("Famille & enfants")),
]


def localized(name):
    """Pages surtout rédactionnelles : une version par langue (core/en/<page>.html), repli sur le français."""
    folder, file = name.rsplit("/", 1)
    return [f"{folder}/en/{file}", name] if is_english() else [name]


def home(request):
    return render(request, "core/home.html", {"categories": TEASER_CATEGORIES})


def contact(request):
    subject = request.GET.get("sujet")
    form = ContactForm(request.POST or None, initial={"subject": subject} if subject in dict(SUBJECTS) else None)
    if request.method == "POST" and form.is_valid():
        if throttled(f"contact:{client_ip(request)}", CONTACTS_PER_HOUR, 3600):
            messages.error(request, _("Trop de messages envoyés depuis cette connexion, réessaie dans une heure."))
            return redirect("core:contact")
        if not form.is_spam():
            msg = form.save()
            try:
                send_mail(
                    f"[Nice-Event] {msg.get_subject_display()} — {msg.name}",
                    f"{msg.message}\n\n— {msg.name} <{msg.email}>",
                    None,
                    [SiteConfig.get().contact_email],
                    fail_silently=False,
                )
            except Exception:  # le message reste lisible dans l'admin
                log.exception("Envoi du courriel de contact impossible")
        messages.success(request, _("Message envoyé. On te répond dès que possible."))
        return redirect("core:contact")
    return render(request, "core/contact.html", {"form": form})


def legal(request):
    return render(request, localized("core/legal.html"))


def privacy(request):
    return render(request, localized("core/privacy.html"))


@require_GET
def robots(request):
    lines = ["User-agent: *", "Disallow: /gestion/", "Disallow: /admin/", f"Sitemap: {settings.SITE_URL}/sitemap.xml"]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def not_found(request, exception=None):
    return render(request, "404.html", status=404)
