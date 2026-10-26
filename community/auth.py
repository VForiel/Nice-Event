from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Connexion avec l'adresse électronique (les membres n'ont pas d'identifiant à retenir)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or "@" not in username:
            return None
        user = get_user_model().objects.filter(email__iexact=username.strip()).order_by("pk").first()
        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
