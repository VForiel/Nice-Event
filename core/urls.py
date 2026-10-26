from django.urls import path
from django.utils.translation import gettext_lazy as _

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("contact/", views.contact, name="contact"),
    path(_("mentions-legales/"), views.legal, name="legal"),
    path(_("confidentialite/"), views.privacy, name="privacy"),
    path(_("conditions/"), views.charter, name="charter"),
]
