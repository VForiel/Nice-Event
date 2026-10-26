from django.urls import path

from . import views

app_name = "gestion"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("reglages/", views.settings_view, name="settings"),
    path("reglages/test-courriel/", views.test_email, name="test_email"),
]
