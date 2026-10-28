from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from django.utils.translation import gettext_lazy as _

from . import views
from .forms import LoginForm

app_name = "community"

urlpatterns = [
    path(_("compte/inscription/"), views.signup, name="signup"),
    path(_("compte/google/"), views.google_start, name="google_start"),
    path(_("compte/google/retour/"), views.google_callback, name="google_callback"),
    path(_("compte/confirmer/<uidb64>/<token>/"), views.confirm, name="confirm"),
    path(_("compte/confirmer/renvoyer/"), views.confirm_resend, name="confirm_resend"),
    path(_("compte/connexion/"), auth_views.LoginView.as_view(
        template_name="community/login.html", authentication_form=LoginForm, redirect_authenticated_user=True),
        name="login"),
    path(_("compte/deconnexion/"), auth_views.LogoutView.as_view(next_page=reverse_lazy("core:home")), name="logout"),
    path(_("compte/mot-de-passe/"), views.PasswordResetView.as_view(), name="password_reset"),
    path(_("compte/mot-de-passe/envoye/"), auth_views.PasswordResetDoneView.as_view(
        template_name="community/password_reset_done.html"), name="password_reset_done"),
    path(_("compte/mot-de-passe/<uidb64>/<token>/"), auth_views.PasswordResetConfirmView.as_view(
        template_name="community/password_reset_confirm.html", success_url=reverse_lazy("community:login")),
        name="password_reset_confirm"),
    path(_("compte/mot-de-passe/changer/"), auth_views.PasswordChangeView.as_view(
        template_name="community/password_change.html", success_url=reverse_lazy("community:settings")),
        name="password_change"),
    path(_("compte/"), views.me, name="me"),
    path(_("compte/reglages/"), views.settings_view, name="settings"),
    path(_("compte/supprimer/"), views.delete_account, name="delete_account"),
    path(_("membres/"), views.members, name="members"),
    path(_("membres/<slug:handle>/"), views.profile, name="profile"),
    path(_("membres/<slug:handle>/ami/<str:action>/"), views.friend_action, name="friend"),
    path(_("amis/"), views.friends, name="friends"),
    path("notifications/", views.notifications, name="notifications"),
    path(_("signaler/<str:kind>/<slug:key>/"), views.report, name="report"),
    path(_("evenements/<slug:slug>/commenter/"), views.comment_new, name="comment_new"),
    path(_("commentaires/<int:pk>/supprimer/"), views.comment_delete, name="comment_delete"),
    path(_("evenements/<slug:slug>/souvenirs/ajouter/"), views.media_new, name="media_new"),
    path(_("souvenirs/<int:pk>/supprimer/"), views.media_delete, name="media_delete"),
]
