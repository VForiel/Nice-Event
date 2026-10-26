from django.db import migrations

from events.categories import CATEGORIES


def load(apps, schema_editor):
    Category = apps.get_model("events", "Category")
    for order, (slug, name, name_en, emoji, tone, icon) in enumerate(CATEGORIES):
        Category.objects.update_or_create(slug=slug, defaults={
            "name": name, "name_en": name_en, "emoji": emoji, "tone": tone, "icon": icon, "order": order})


class Migration(migrations.Migration):
    dependencies = [("events", "0001_initial")]
    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
