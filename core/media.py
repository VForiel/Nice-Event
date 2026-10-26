"""Fichiers téléversés, servis par Django avec un cache navigateur d'une semaine (les noms changent à chaque nouveau
téléversement). Le reverse proxy partagé de VPS1 n'a pas accès au volume des données, d'où ce passage par Django."""

from django.conf import settings
from django.views.static import serve

CACHE = "public, max-age=604800"


def media(request, path):
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    response["Cache-Control"] = CACHE
    return response
