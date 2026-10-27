from django.urls import path
from django.utils.translation import gettext_lazy as _

from . import views

app_name = "alerts"

urlpatterns = [
    path(_("filtres/"), views.filters_page, name="filters"),
    path(_("filtres/utiliser/"), views.use, name="use"),
    path(_("filtres/retirer/"), views.clear, name="clear"),
    path(_("filtres/canaux/"), views.channels, name="channels"),
    path("api/filtres/apercu/", views.preview, name="preview"),
    path("api/filtres/", views.save, name="save"),
    path("api/filtres/<int:pk>/alerte/", views.alert, name="alert"),
    path("api/filtres/<int:pk>/supprimer/", views.delete, name="delete"),
    path("api/push/abonnement/", views.push_subscribe, name="push_subscribe"),
]
