"""Communes des Alpes-Maritimes (geo.api.gouv.fr, venues/data/communes-06.json) et Monaco."""

import json
from pathlib import Path

from django.db import migrations
from django.utils.text import slugify

DATA = Path(__file__).resolve().parent.parent / "data" / "communes-06.json"
COASTAL = {"06138", "06079", "06029", "06155", "06004", "06161", "06027", "06123", "06088", "06159", "06121", "06011",
           "06059", "06032", "06104", "06083", "99138"}


def load(apps, schema_editor):
    Commune = apps.get_model("venues", "Commune")
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    rows.append({"nom": "Monaco", "code": "99138", "codesPostaux": ["98000"],
                 "centre": {"coordinates": [7.4246, 43.7384]}, "codeEpci": "", "population": 38350})
    for row in rows:
        lon, lat = row["centre"]["coordinates"]
        Commune.objects.update_or_create(insee=row["code"], defaults={
            "name": row["nom"], "slug": slugify(row["nom"]), "postcodes": ",".join(row.get("codesPostaux", [])),
            "lat": lat, "lon": lon, "population": row.get("population") or 0,
            "metropole": row.get("codeEpci") == "200030195", "coastal": row["code"] in COASTAL,
        })


class Migration(migrations.Migration):
    dependencies = [("venues", "0001_initial")]
    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
