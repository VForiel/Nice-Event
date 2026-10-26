from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="community_ensure_profile")
def ensure_profile(sender, instance, created, **kwargs):
    """Tout compte a un profil (y compris ceux créés par createsuperuser ou dans l'admin)."""
    if created:
        Profile.objects.get_or_create(
            user=instance, defaults={"display_name": instance.get_full_name() or instance.username.split("@")[0]}
        )
