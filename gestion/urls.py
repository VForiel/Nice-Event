from django.urls import path

from . import views

app_name = "gestion"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("moderation/", views.moderation, name="moderation"),
    path("moderation/<int:pk>/", views.moderate, name="moderate"),
    path("evenements/", views.events, name="events"),
    path("evenements/<int:pk>/", views.event_action, name="event_action"),
    path("signalements/", views.reports, name="reports"),
    path("signalements/<int:pk>/", views.report_toggle, name="report_toggle"),
    path("membres/", views.members, name="members"),
    path("membres/<int:pk>/", views.member_action, name="member_action"),
    path("reglages/", views.settings_view, name="settings"),
    path("reglages/test-courriel/", views.test_email, name="test_email"),
]
