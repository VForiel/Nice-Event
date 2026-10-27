from django.db import migrations


def move_ajc06(apps, schema_editor):
    """Le site de l'AJC06 est passé de beta.ajc06.com à ajc06.com."""
    Source = apps.get_model("aggregator", "Source")
    Source.objects.filter(slug="ajc06").update(url="https://ajc06.com/evenements/nice-event.json",
                                               website="https://ajc06.com")


class Migration(migrations.Migration):

    dependencies = [
        ('aggregator', '0009_ajc06_feed'),
    ]

    operations = [
        migrations.RunPython(move_ajc06, migrations.RunPython.noop),
    ]
