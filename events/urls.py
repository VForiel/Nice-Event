from django.urls import path
from django.utils.translation import gettext_lazy as _

from . import views

app_name = "events"

urlpatterns = [
    path(_("evenements/"), views.event_list, name="list"),
    path(_("evenements/publier/"), views.event_new, name="new"),
    path(_("evenements/agenda.ics"), views.agenda_ics, name="agenda"),
    path(_("evenements/<slug:slug>/"), views.event_detail, name="detail"),
    path(_("evenements/<slug:slug>/en-ligne/"), views.event_published, name="published"),
    path(_("evenements/<slug:slug>/modifier/"), views.event_edit, name="edit"),
    path(_("evenements/<slug:slug>/supprimer/"), views.event_delete, name="delete"),
    path(_("evenements/<slug:slug>/participer/"), views.attend, name="attend"),
    path(_("evenements/<slug:slug>/inviter/"), views.invite, name="invite"),
    path(_("evenements/<slug:slug>.ics"), views.event_ics, name="ics"),
    path(_("lieux/<slug:slug>/"), views.venue_detail, name="venue"),
    path(_("carte/"), views.map_page, name="map"),
    path(_("carte/evenements.json"), views.map_data, name="map_data"),
    path("api/adresses/", views.api_addresses, name="api_addresses"),
    path("api/lieux/", views.api_venues, name="api_venues"),
]
