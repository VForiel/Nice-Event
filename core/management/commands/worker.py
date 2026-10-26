"""Tâche de fond : lance les tâches planifiées de core.jobs (et des modules jobs.py des autres apps).

    python manage.py worker            # boucle sans fin (conteneur worker)
    python manage.py worker --once     # un seul passage (tests, cron de secours)
    python manage.py worker --run sauvegarde   # lance une tâche tout de suite
"""

import importlib
import logging
import signal
import time
import traceback

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from core import jobs
from core.models import JobRun

log = logging.getLogger("worker")
TICK = 30


def load_jobs():
    for app in apps.get_app_configs():
        if app.name != "core":
            try:
                importlib.import_module(f"{app.name}.jobs")
            except ModuleNotFoundError as exc:
                if exc.name != f"{app.name}.jobs":
                    raise


def run_job(item):
    record, _ = JobRun.objects.get_or_create(name=item.name)
    record.last_started = timezone.now()
    record.save(update_fields=["last_started"])
    try:
        message = item.run() or ""
        record.last_ok = True
    except Exception:
        log.exception("Tâche %s en échec", item.name)
        message = traceback.format_exc(limit=5)
        record.last_ok = False
    record.last_finished = timezone.now()
    record.last_message = str(message)[:5000]
    record.save(update_fields=["last_finished", "last_ok", "last_message"])
    log.info("Tâche %s : %s", item.name, "ok" if record.last_ok else "échec")


def tick():
    close_old_connections()
    last = dict(JobRun.objects.values_list("name", "last_started"))
    now = timezone.now()
    for item in jobs.JOBS.values():
        if item.due(now, last.get(item.name)):
            run_job(item)


class Command(BaseCommand):
    help = "Exécute les tâches planifiées (boucle sans fin)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Un seul passage")
        parser.add_argument("--run", metavar="TÂCHE", help="Lance cette tâche tout de suite")

    def handle(self, *args, **options):
        load_jobs()
        if options["run"]:
            if options["run"] not in jobs.JOBS:
                raise CommandError(f"Tâche inconnue. Tâches : {', '.join(jobs.JOBS)}")
            run_job(jobs.JOBS[options["run"]])
            return
        if options["once"]:
            tick()
            return

        stopping = []
        signal.signal(signal.SIGTERM, lambda *a: stopping.append(True))
        log.info("Tâche de fond démarrée : %s", ", ".join(jobs.JOBS))
        while not stopping:
            try:
                tick()
            except Exception:
                log.exception("Passage du planificateur en échec")
            for _ in range(TICK):
                if stopping:
                    break
                time.sleep(1)
        log.info("Tâche de fond arrêtée")
