from django.urls import path

from . import views

app_name = "gestion"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("moderation/", views.moderation, name="moderation"),
    path("moderation/<int:pk>/", views.moderate, name="moderate"),
    path("evenements/", views.events, name="events"),
    path("evenements/<int:pk>/", views.event_action, name="event_action"),
    path("evenements/<int:pk>/diffuser/", views.diffuse, name="diffuse"),
    path("diffusions/", views.posts, name="posts"),
    path("diffusions/<int:pk>/", views.post_action, name="post_action"),
    path("sources/", views.sources, name="sources"),
    path("sources/nouvelle/", views.source_edit, name="source_new"),
    path("sources/<int:pk>/", views.source_edit, name="source_edit"),
    path("sources/<int:pk>/scanner/", views.source_scan, name="source_scan"),
    path("signalements/", views.reports, name="reports"),
    path("signalements/<int:pk>/", views.report_toggle, name="report_toggle"),
    path("membres/", views.members, name="members"),
    path("membres/<int:pk>/", views.member_action, name="member_action"),
    path("reglages/", views.settings_view, name="settings"),
    path("reglages/test-courriel/", views.test_email, name="test_email"),
    path("reglages/test-reseau/<str:network>/", views.test_network, name="test_network"),
]
