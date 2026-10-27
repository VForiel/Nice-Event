"""Réglages de Nice-Event.

Seul ce qui touche à l'infrastructure passe par des variables d'environnement (voir .env.example) : clé secrète, clé de
chiffrement des réglages, chemins des données, noms de domaine. Le reste (serveur mail, réseaux sociaux, sources
d'événements…) se règle dans /gestion/reglages/ et vit en base (app siteconfig).
"""

import os
import sys
from pathlib import Path

from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"


def load_env_file(path):
    """Variables d'un fichier .env à côté de manage.py (développement) ; l'environnement réel reste prioritaire."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


if not TESTING:
    load_env_file(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-secret" if DEBUG else "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY doit être défini en production.")
# Chiffre les secrets saisis dans /gestion/reglages/ (mots de passe SMTP, jetons des réseaux). Clé Fernet :
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CONFIG_ENCRYPTION_KEY = os.environ.get("CONFIG_ENCRYPTION_KEY", "")
if not CONFIG_ENCRYPTION_KEY and not DEBUG:
    raise RuntimeError("CONFIG_ENCRYPTION_KEY doit être défini en production.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000").rstrip("/")
# Derrière un reverse proxy de confiance (Caddy) : l'adresse du visiteur est dans X-Forwarded-For.
TRUST_X_FORWARDED_FOR = env_bool("TRUST_X_FORWARDED_FOR", False)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django.forms",
    "core",
    "siteconfig",
    "venues",
    "events",
    "community",
    "aggregator",
    "social",
    "alerts",
    "gestion",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "core.security.BanMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csp",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site",
                "community.context_processors.member",
            ],
        },
    },
]

FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

WSGI_APPLICATION = "config.wsgi.application"

# SQLite partagée par le site et la tâche de fond (WAL : lectures pendant les écritures ; IMMEDIATE : pas
# d'erreur « database is locked » quand deux processus veulent écrire en même temps).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", BASE_DIR / "db.sqlite3"),
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", "Français"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", BASE_DIR / "backups"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG and not TESTING
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

# Cache partagé entre les processus gunicorn et la tâche de fond (limites d'envoi, compteurs anti-abus).
if os.environ.get("CACHE_DIR"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                          "LOCATION": os.environ["CACHE_DIR"]}}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "community:login"
LOGIN_REDIRECT_URL = "community:me"
LOGOUT_REDIRECT_URL = "core:home"
# Connexion par courriel (les membres n'ont pas d'identifiant à retenir) ; l'admin accepte aussi l'identifiant.
AUTHENTICATION_BACKENDS = ["community.auth.EmailBackend", "django.contrib.auth.backends.ModelBackend"]

# Courriel : les paramètres SMTP sont lus en base à chaque envoi (siteconfig.mail). Tant qu'aucun serveur n'est
# réglé, les messages s'affichent dans la console (journaux du conteneur).
EMAIL_BACKEND = "siteconfig.mail.ConfigEmailBackend"
DEFAULT_FROM_EMAIL = "Nice-Event <contact@nice-event.fr>"
EMAIL_TIMEOUT = 20

# Mentions légales
LEGAL_PUBLISHER = "Vincent Foriel"
LEGAL_HOST = os.environ.get("LEGAL_HOST", "OVH SAS, 2 rue Kellermann, 59100 Roubaix, France — +33 9 72 10 10 07.")

# Sécurité. CSP native de Django 6 : {{ csp_nonce }} dans les gabarits pour les rares scripts en ligne.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE],
    "style-src": [CSP.SELF],
    "img-src": [CSP.SELF, "data:", "blob:"],
    "font-src": [CSP.SELF],
    "connect-src": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "object-src": [CSP.NONE],
}
if not DEBUG:
    if TRUST_X_FORWARDED_FOR:  # derrière un reverse proxy (Caddy) qui termine le TLS
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

# Tests : hachage rapide des mots de passe (jamais utilisé hors de « manage.py test »).
if TESTING:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    CONFIG_ENCRYPTION_KEY = "dGVzdC1vbmx5LWtleS1kby1ub3QtdXNlLWluLXByb2Q="
