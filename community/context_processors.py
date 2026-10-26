from .models import Friendship, Profile


def member(request):
    """Compteur affiché sur l'avatar de l'en-tête : notifications non lues (dont les demandes d'ami)."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    context = {
        "unread_count": user.notifications.filter(read=False).count(),
        "pending_friends": Friendship.objects.filter(to_user=user, accepted=False).count(),
        "my_profile": Profile.objects.get_or_create(user=user, defaults={"display_name": user.get_username().split("@")[0]})[0],
    }
    if user.is_staff:
        from events.models import Event

        context["pending_count"] = Event.objects.filter(status=Event.Status.PENDING).count()
    return context
