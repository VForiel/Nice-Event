from django.conf import settings

from siteconfig.models import SiteConfig

from .models import Announcement


def site(request):
    config = SiteConfig.get()
    return {
        "SITE_URL": settings.SITE_URL,
        "CONTACT_EMAIL": config.contact_email,
        "LEGAL_PUBLISHER": settings.LEGAL_PUBLISHER,
        "LEGAL_HOST": settings.LEGAL_HOST,
        "DONATION_URL": settings.DONATION_URL,
        "announcement": Announcement.current(),
    }
