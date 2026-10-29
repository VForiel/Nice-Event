import logging

from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET

from siteconfig.models import SiteConfig

from .forms import ContactForm
from .i18n import is_english
from .models import SUBJECTS
from .security import client_ip, throttled

log = logging.getLogger(__name__)
CONTACTS_PER_HOUR = 5

def localized(name):
    """Pages surtout rédactionnelles : une version par langue (core/en/<page>.html), repli sur le français."""
    folder, file = name.rsplit("/", 1)
    return [f"{folder}/en/{file}", name] if is_english() else [name]


def home(request):
    from django.db.models import Count, Q
    from django.utils import timezone

    from events.models import Category, Event
    from events.views import base_queryset, friends_going, window

    events = base_queryset()
    today_start, today_end = window("aujourdhui")
    we_start, we_end = window("weekend")
    today = list(events.between(today_start, today_end)[:6])
    weekend = list(events.between(we_start, we_end).exclude(pk__in=[e.pk for e in today])[:6])
    from events.recommend import for_home

    recommended = for_home(request.user)
    featured = list(events.filter(featured=True)[:3])
    latest = list(events.internal().order_by("-published_at")[:4])
    going = friends_going(request.user, today + weekend + featured + latest + recommended)
    for e in today + weekend + featured + latest + recommended:
        e.friends_going = going.get(e.pk, 0)
    now = timezone.now()
    categories = Category.objects.annotate(n=Count("events", filter=Q(events__status=Event.Status.PUBLISHED,
                                                                        events__ends_at__gte=now))).order_by("order")
    return render(request, "core/home.html", {
        "today": today, "weekend": weekend, "featured": featured, "recommended": recommended, "latest": latest, "categories": categories,
        "total": events.count(),
    })


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


def charter(request):
    return render(request, localized("core/charter.html"))


@require_GET
def robots(request):
    lines = ["User-agent: *", "Disallow: /gestion/", "Disallow: /admin/", f"Sitemap: {settings.SITE_URL}/sitemap.xml"]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def not_found(request, exception=None):
    return render(request, "404.html", status=404)
