"""Chiffrement des secrets stockés en base (mots de passe SMTP, jetons des réseaux sociaux).

Clé Fernet dans CONFIG_ENCRYPTION_KEY ; en développement, à défaut, une clé dérivée de SECRET_KEY. Perdre la clé
rend les secrets illisibles (il suffit alors de les ressaisir dans /gestion/reglages/), pas le reste du site.
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models

log = logging.getLogger(__name__)


def _fernet():
    key = settings.CONFIG_ENCRYPTION_KEY
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(f"siteconfig:{settings.SECRET_KEY}".encode()).digest())
    return Fernet(key)


def encrypt(value):
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token):
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        log.warning("Secret illisible (clé de chiffrement changée ?) : à ressaisir dans /gestion/reglages/")
        return ""


class EncryptedTextField(models.TextField):
    """Texte chiffré en base, en clair dans le code : `config.smtp_password` se lit et s'écrit normalement."""

    def from_db_value(self, value, expression, connection):
        return decrypt(value)

    def get_prep_value(self, value):
        return encrypt(super().get_prep_value(value))
