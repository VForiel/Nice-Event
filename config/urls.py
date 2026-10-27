from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.contrib.sitemaps import GenericSitemap, Sitemap
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path, reverse

from core import media as core_media
from alerts import views as alert_views
from core import views as core_views
from events.models import Event


class StaticSitemap(Sitemap):
    i18n = True
    alternates = True

    def items(self):
        return ["core:home", "events:list", "events:map", "core:contact"]

    def location(self, item):
        return reverse(item)


class EventSitemap(GenericSitemap):
    i18n = True
    alternates = True


sitemaps = {
    "pages": StaticSitemap,
    "evenements": EventSitemap({"queryset": Event.objects.published().internal(), "date_field": "updated_at"}),
}

admin.site.site_header = "Nice-Event — administration"
admin.site.site_title = "Nice-Event"

# Pages publiques : en français à la racine, en anglais sous /en/.
urlpatterns = i18n_patterns(
    path("", include("core.urls")),
    path("", include("events.urls")),
    path("", include("community.urls")),
    path("", include("alerts.urls")),
    prefix_default_language=False,
)

# Gestion et administration : en français uniquement.
urlpatterns += [
    path("gestion/", include("gestion.urls")),
    path("admin/", admin.site.urls),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path("robots.txt", core_views.robots),
    path("sw.js", alert_views.service_worker, name="service_worker"),
    path("media/<path:path>", core_media.media),
]

if settings.DEBUG:
    urlpatterns += [path("tiles/<str:path>", core_media.dev_tiles)]

handler404 = "core.views.not_found"
