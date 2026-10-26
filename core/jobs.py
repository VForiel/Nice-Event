"""Tâches planifiées, exécutées par `python manage.py worker` (conteneur « worker »).

Pas de Celery ni de Redis : une boucle qui regarde toutes les 30 secondes quelles tâches sont dues, les lance l'une
après l'autre et note leur passage dans JobRun. Une tâche manquée (worker arrêté) est rattrapée une fois au
redémarrage, pas autant de fois qu'elle a été manquée.

Les autres applications ajoutent leurs tâches avec le décorateur `job` dans leur module `jobs.py`
(publications programmées, scans des sources externes…).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Callable

from django.core.management import call_command
from django.utils import timezone

log = logging.getLogger(__name__)


@dataclass
class Job:
    name: str
    due: Callable  # due(now, last_started) -> bool
    run: Callable  # run() -> str (compte rendu)


JOBS: dict[str, Job] = {}


def job(name, due):
    def register(func):
        JOBS[name] = Job(name, due, func)
        return func
    return register


def every(minutes):
    def due(now, last):
        return last is None or now - last >= timedelta(minutes=minutes)
    return due


def daily_at(*times):
    """Due à chacune des heures données (heure de Paris), ex. daily_at("10:00", "16:00") ; `times` peut aussi être
    une fonction qui renvoie la liste (horaires réglables dans l'interface)."""

    def due(now, last):
        local = timezone.localtime(now)
        wanted = times[0]() if len(times) == 1 and callable(times[0]) else times
        for value in wanted:
            hour, minute = (int(x) for x in value.split(":"))
            slot = timezone.make_aware(datetime.combine(local.date(), time(hour, minute)))
            if slot > now:
                slot -= timedelta(days=1)  # créneau d'hier, s'il a été manqué
            if last is None or last < slot:
                return True
        return False
    return due


@job("sauvegarde", daily_at("03:30"))
def backup():
    call_command("backup_site")
    return "Base sauvegardée"
