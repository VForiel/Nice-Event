import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.security import client_ip, throttled
from events.models import Event

from . import confirmation
from .forms import DeleteAccountForm, EmailForm, ProfileForm, ReportForm, SignupForm
from .models import Friendship, Notification, Profile, Report, friends_of, relation
from .notify import notify

SIGNUPS_PER_HOUR = 5
User = get_user_model()
log = logging.getLogger(__name__)


def profile_of(user):
    """Profil du membre, créé à la volée pour les comptes qui n'en auraient pas (admin)."""
    profile = getattr(user, "profile", None)
    if profile is None:
        profile = Profile.objects.create(user=user, display_name=user.get_full_name() or user.username.split("@")[0])
    return profile


def safe_next(request, default):
    target = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return default


# Compte -----------------------------------------------------------------------------------------------------------


def signup(request):
    if request.user.is_authenticated:
        return redirect("community:me")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if form.is_spam() or throttled(f"signup:{client_ip(request)}", SIGNUPS_PER_HOUR, 3600):
            messages.error(request, _("Trop d'inscriptions depuis cette connexion, réessaie plus tard."))
            return redirect("community:signup")
        needs_confirmation = confirmation.required()
        user = form.save(confirmed=not needs_confirmation)
        login(request, user, backend="community.auth.EmailBackend")
        if needs_confirmation:
            confirmation.send(user)
            messages.success(request, _("Bienvenue ! Un lien de confirmation vient de partir à %(email)s : ouvre-le pour "
                                        "pouvoir publier des événements.") % {"email": user.email})
        else:
            messages.success(request, _("Bienvenue ! Complète ton profil pour que tes amis te trouvent."))
        return redirect(safe_next(request, reverse_lazy("community:settings")))
    return render(request, "community/signup.html", {"form": form, "next": request.GET.get("next", "")})


def confirm(request, uidb64, token):
    try:
        user = User.objects.select_related("profile").get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (ValueError, TypeError, OverflowError, User.DoesNotExist):
        user = None
    if user is None or user.profile.email_confirmed or not confirmation.tokens.check_token(user, token):
        messages.error(request, _("Ce lien de confirmation n'est plus valable. Connecte-toi pour en demander un nouveau."))
        return redirect("community:login")
    user.profile.email_confirmed = True
    user.profile.save(update_fields=["email_confirmed"])
    if not request.user.is_authenticated:
        login(request, user, backend="community.auth.EmailBackend")
    messages.success(request, _("Adresse confirmée : tu peux publier tes événements !"))
    return redirect("events:new")


@login_required
@require_POST
def confirm_resend(request):
    if profile_of(request.user).email_confirmed:
        return redirect("community:settings")
    if throttled(f"confirm:{request.user.pk}", 5, 3600):
        messages.error(request, _("Beaucoup de demandes : réessaie dans une heure."))
    elif confirmation.send(request.user):
        messages.success(request, _("Nouveau lien envoyé à %(email)s.") % {"email": request.user.email})
    else:
        messages.error(request, _("Le courriel n'a pas pu partir. Réessaie plus tard ou écris-nous."))
    return redirect(safe_next(request, reverse_lazy("community:settings")))


class PasswordResetView(auth_views.PasswordResetView):
    """Mot de passe oublié, limité pour qu'on ne puisse pas inonder une boîte mail de liens."""

    template_name = "community/password_reset.html"
    email_template_name = "community/password_reset_email.txt"
    subject_template_name = "community/password_reset_subject.txt"
    success_url = reverse_lazy("community:password_reset_done")

    def form_valid(self, form):
        email = form.cleaned_data["email"].strip().lower()
        if throttled(f"reset:{client_ip(self.request)}", 5, 3600) or throttled(f"reset-mail:{email}", 3, 3600):
            return redirect(self.success_url)  # même page de confirmation : rien n'est révélé
        return super().form_valid(form)


@login_required
def me(request):
    return redirect(profile_of(request.user).get_absolute_url())


@login_required
def settings_view(request):
    profile = profile_of(request.user)
    form = ProfileForm(request.POST or None, request.FILES or None, instance=profile, prefix="p")
    email_form = EmailForm(request.user, initial={"email": request.user.email}, prefix="e")
    if request.method == "POST" and "save_profile" in request.POST and form.is_valid():
        form.save()  # toujours valide : les champs refusés sont écartés (PartialSaveMixin)
        if form.skipped:
            messages.warning(request, _("Profil enregistré, sauf ces champs, laissés tels quels : %(fields)s.")
                             % {"fields": form.skipped_summary()})
        else:
            messages.success(request, _("Profil enregistré."))
        return redirect("community:settings")
    if request.method == "POST" and "save_email" in request.POST:
        email_form = EmailForm(request.user, request.POST, prefix="e")
        if email_form.is_valid():
            request.user.email = email_form.cleaned_data["email"]
            if "@" in request.user.username:
                request.user.username = request.user.email
            request.user.save(update_fields=["email", "username"])
            profile.email_confirmed = False
            profile.save(update_fields=["email_confirmed"])
            confirmation.send(request.user)
            messages.success(request, _("Adresse mise à jour : confirme-la avec le lien qui vient de partir."))
            return redirect("community:settings")
    return render(request, "community/settings.html", {"form": form, "email_form": email_form, "profile": profile})


@login_required
def delete_account(request):
    form = DeleteAccountForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        logout(request)
        user.delete()  # profil, amitiés, participations ; ses événements restent, sans organisateur
        messages.success(request, _("Ton compte et tes données ont été supprimés."))
        return redirect("core:home")
    return render(request, "community/delete_account.html", {"form": form})


# Membres ----------------------------------------------------------------------------------------------------------


@login_required
def members(request):
    q = request.GET.get("q", "").strip()
    people = Profile.objects.select_related("user").filter(user__is_active=True)
    if q:
        people = people.filter(Q(display_name__icontains=q) | Q(headline__icontains=q) | Q(interests__name__icontains=q)).distinct()
    me_profile = profile_of(request.user)
    suggestions = []
    if not q:
        known = {u.pk for u in friends_of(request.user)} | {request.user.pk}
        likes = me_profile.interests.all()
        if likes:
            suggestions = (Profile.objects.filter(interests__in=likes, user__is_active=True).exclude(user__pk__in=known)
                           .distinct()[:6])
    return render(request, "community/members.html", {"people": people[:120], "q": q, "suggestions": suggestions})


def profile(request, handle):
    person = get_object_or_404(Profile.objects.select_related("user", "commune"), handle=handle, user__is_active=True)
    if not person.visible_to(request.user):
        return render(request, "community/profile_private.html", {"person": person}, status=403)
    rel = relation(request.user, person.user)
    going = []
    events = Event.objects.published().upcoming().select_related("venue__commune").prefetch_related("categories")
    if person.show_events or rel == "self":
        going = events.filter(attendances__user=person.user).exclude(organizer=person.user)[:6]
    organized = events.filter(organizer=person.user)[:6]
    return render(request, "community/profile.html", {
        "person": person, "rel": rel, "friends": friends_of(person.user)[:12],
        "friend_count": friends_of(person.user).count(), "going": going, "organized": organized,
        "interests": person.interests.all(),
        "show_contacts": person.has_contacts and person.contacts_visible_to(request.user, rel),
    })


# Amis -------------------------------------------------------------------------------------------------------------


@login_required
def friends(request):
    received = Friendship.objects.filter(to_user=request.user, accepted=False).select_related("from_user__profile")
    sent = Friendship.objects.filter(from_user=request.user, accepted=False).select_related("to_user__profile")
    return render(request, "community/friends.html", {"friends": friends_of(request.user), "received": received, "sent": sent})


@login_required
@require_POST
def friend_action(request, handle, action):
    other = get_object_or_404(Profile, handle=handle).user
    if other.pk == request.user.pk:
        raise Http404
    link = Friendship.objects.between(request.user, other).first()
    if action == "add" and not link:
        Friendship.objects.create(from_user=request.user, to_user=other)
        notify(other, request.user, Notification.Verb.FRIEND_REQUEST)
        messages.success(request, _("Demande envoyée."))
    elif action == "accept" and link and not link.accepted and link.to_user_id == request.user.pk:
        link.accepted = True
        link.save(update_fields=["accepted"])
        notify(other, request.user, Notification.Verb.FRIEND_ACCEPTED)
        messages.success(request, _("Vous êtes maintenant amis."))
    elif action in ("decline", "cancel", "remove") and link:
        link.delete()
    return redirect(safe_next(request, other.profile.get_absolute_url()))


# Notifications ----------------------------------------------------------------------------------------------------


@login_required
def notifications(request):
    items = list(request.user.notifications.select_related("actor__profile", "event")[:60])
    request.user.notifications.filter(read=False).update(read=True)
    return render(request, "community/notifications.html", {"items": items})


# Signalements -----------------------------------------------------------------------------------------------------

AUTO_HIDE_REPORTS = 3


@login_required
def report(request, kind, key):
    if kind == "evenement":
        target = get_object_or_404(Event, slug=key)
    else:
        target = get_object_or_404(Profile, handle=key)
    form = ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if throttled(f"reports:{request.user.pk}", 10, 86400):
            messages.error(request, _("Beaucoup de signalements aujourd'hui : réessaie demain ou écris-nous."))
            return redirect(target.get_absolute_url())
        Report.objects.create(reporter=request.user, reason=form.cleaned_data["reason"],
                              event=target if kind == "evenement" else None,
                              profile=target if kind != "evenement" else None)
        # Plusieurs signalements de membres différents : l'événement est masqué en attendant l'équipe.
        if kind == "evenement" and target.status == Event.Status.PUBLISHED:
            reporters = Report.objects.filter(event=target, handled=False).values("reporter").distinct().count()
            if reporters >= AUTO_HIDE_REPORTS and not (target.organizer and target.organizer.is_staff):
                target.status = Event.Status.HIDDEN
                target.moderation_note = "Masqué automatiquement après plusieurs signalements."
                target.save(update_fields=["status", "moderation_note"])
        messages.success(request, _("Merci, l'équipe va regarder ça."))
        return redirect(target.get_absolute_url() if kind != "evenement" or target.status == Event.Status.PUBLISHED
                        else "events:list")
    return render(request, "community/report.html", {"form": form, "target": target})
