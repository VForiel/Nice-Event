import html

from django.db import migrations

from core.text import normalize, repair

ICONS = {"soiree": ("🍸", "party"), "networking": ("💼", "briefcase")}


def update(apps, schema_editor):
    Category = apps.get_model("events", "Category")
    for slug, (emoji, icon) in ICONS.items():
        Category.objects.filter(slug=slug).update(emoji=emoji, icon=icon)

    # Textes repris avant la correction du décodage (« ApÃ©ro » -> « Apéro », « &amp; » -> « & »).
    Venue = apps.get_model("venues", "Venue")
    for venue in Venue.objects.all():
        name, address = repair(venue.name), repair(venue.address)
        if (name, address) != (venue.name, venue.address):
            Venue.objects.filter(pk=venue.pk).update(name=name, address=address)
    Event = apps.get_model("events", "Event")
    for event in Event.objects.filter(source__isnull=False).select_related("venue__commune"):
        fields = {f: repair(getattr(event, f)) for f in ("title", "summary", "description", "organizer_name")}
        fields["summary"] = html.unescape(fields["summary"])  # « &amp; » laissé par l'extrait
        if any(fields[f] != getattr(event, f) for f in fields):
            venue = Venue.objects.select_related("commune").get(pk=event.venue_id)
            fields["search"] = normalize(" ".join(filter(None, [
                fields["title"], event.title_en, fields["summary"], event.summary_en, fields["organizer_name"],
                venue.name, venue.commune.name])))
            Event.objects.filter(pk=event.pk).update(**fields)


class Migration(migrations.Migration):
    dependencies = [("events", "0003_alter_event_price_kind"), ("venues", "0002_load_communes")]
    operations = [migrations.RunPython(update, migrations.RunPython.noop)]
