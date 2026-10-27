from core.jobs import every, job

from .send import run


@job("alertes", every(10))
def alerts():
    return run()
