from core.jobs import daily_at, every, job

from .service import check_accounts, send_due


@job("publications", every(1))
def publications():
    return send_due()


@job("verification-reseaux", daily_at("08:00"))
def verify():
    return check_accounts()
