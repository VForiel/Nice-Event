from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.contrib.sitemaps import Sitemap
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path, reverse

from core import media as core_media
from core import views as core_views


class StaticSitemap(Sitemap):
    i18n = True
    alternates = True

    def items(self):
        return ["core:home", "core:contact"]

    def location(self, item):
        return reverse(item)


sitemaps = {"pages": StaticSitemap}

admin.site.site_header = "Nice-Event — administration"
admin.site.site_title = "Nice-Event"

# Pages publiques : en français à la racine, en anglais sous /en/.
urlpatterns = i18n_patterns(
    path("", include("core.urls")),
    prefix_default_language=False,
)

# Gestion et administration : en français uniquement.
urlpatterns += [
    path("gestion/", include("gestion.urls")),
    path("admin/", admin.site.urls),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path("robots.txt", core_views.robots),
    path("media/<path:path>", core_media.media),
]

handler404 = "core.views.not_found"
