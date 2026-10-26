"""Sauvegarde du site : base SQLite (copie cohérente, même en cours d'utilisation) et fichiers téléversés.

    python manage.py backup_site            # base tous les jours, médias le dimanche (ou si aucune archive)
    python manage.py backup_site --media    # force l'archive des médias

Les archives vont dans BACKUP_DIR (par défaut <projet>/backups) ; les plus anciennes sont supprimées
(30 jours pour la base, 8 archives de médias).
"""

import gzip
import shutil
import sqlite3
import tarfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

KEEP_DB_DAYS = 30
KEEP_MEDIA = 8


def skip_thumbs(info):
    """Les miniatures (media/thumbs/) se recréent d'elles-mêmes : inutile de les archiver."""
    return None if info.name.startswith("media/thumbs") else info

class Command(BaseCommand):
    help = "Sauvegarde la base et les fichiers téléversés dans BACKUP_DIR."

    def add_arguments(self, parser):
        parser.add_argument("--media", action="store_true", help="Archiver aussi les médias aujourd'hui")

    def handle(self, *args, **options):
        target = Path(settings.BACKUP_DIR)
        target.mkdir(parents=True, exist_ok=True)
        stamp = timezone.localtime().strftime("%Y%m%d-%H%M")

        if connection.vendor != "sqlite":
            self.stderr.write("Seule la base SQLite est prise en charge par cette commande.")
        else:
            raw = target / f"db-{stamp}.sqlite3"
            connection.ensure_connection()
            copy = sqlite3.connect(raw)
            with copy:
                connection.connection.backup(copy)  # API de sauvegarde de SQLite : copie cohérente à chaud
            copy.close()
            with open(raw, "rb") as f_in, gzip.open(f"{raw}.gz", "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            raw.unlink()
            self.stdout.write(f"Base : {raw.name}.gz")

        archives = sorted(target.glob("media-*.tar.gz"))
        if options["media"] or timezone.localdate().weekday() == 6 or not archives:
            media = Path(settings.MEDIA_ROOT)
            name = target / f"media-{stamp}.tar.gz"
            with tarfile.open(name, "w:gz") as tar:
                if media.exists():
                    tar.add(media, arcname="media", filter=skip_thumbs)
            self.stdout.write(f"Médias : {name.name}")
            archives = sorted(target.glob("media-*.tar.gz"))

        limit = timezone.now() - timedelta(days=KEEP_DB_DAYS)
        for old in target.glob("db-*.sqlite3.gz"):
            if timezone.datetime.fromtimestamp(old.stat().st_mtime, tz=timezone.get_current_timezone()) < limit:
                old.unlink()
        for old in archives[:-KEEP_MEDIA]:
            old.unlink()
