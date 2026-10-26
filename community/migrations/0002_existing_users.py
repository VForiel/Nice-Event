"""Profil pour les comptes créés avant l'espace membres ; l'équipe (staff) est de confiance d'office."""

from django.db import migrations


def create(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Profile = apps.get_model("community", "Profile")
    for user in User.objects.filter(profile__isnull=True):
        name = (f"{user.first_name} {user.last_name}".strip() or user.username.split("@")[0])[:80]
        handle, n = name.lower().replace(" ", "-")[:50] or "membre", 2
        base = handle
        while Profile.objects.filter(handle=handle).exists():
            handle, n = f"{base}-{n}", n + 1
        Profile.objects.create(user=user, display_name=name, handle=handle, trusted=user.is_staff)


class Migration(migrations.Migration):
    dependencies = [("community", "0001_initial")]
    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
