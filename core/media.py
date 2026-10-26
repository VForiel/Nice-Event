"""Fichiers téléversés, servis par Django avec un cache navigateur d'une semaine (les noms changent à chaque nouveau
téléversement). Le reverse proxy partagé de VPS1 n'a pas accès au volume des données, d'où ce passage par Django."""

from django.conf import settings
from django.views.static import serve

CACHE = "public, max-age=604800"


def media(request, path):
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    response["Cache-Control"] = CACHE
    return response


def dev_tiles(request, path):
    """Fond de carte en développement seulement (en production : conteneur « tiles », voir compose.yaml), avec les
    requêtes par plages d'octets dont a besoin la lecture PMTiles."""
    import re
    from pathlib import Path

    from django.http import Http404, HttpResponse

    file = (Path(settings.BASE_DIR) / "tiles" / path).resolve()
    if file.parent != (Path(settings.BASE_DIR) / "tiles").resolve() or not file.is_file():
        raise Http404
    size = file.stat().st_size
    match = re.match(r"bytes=(\d+)-(\d*)", request.headers.get("Range", ""))
    if not match:
        response = HttpResponse(file.read_bytes(), content_type="application/octet-stream")
        response["Accept-Ranges"] = "bytes"
        return response
    start = int(match[1])
    end = min(int(match[2]) if match[2] else size - 1, size - 1)
    with open(file, "rb") as f:
        f.seek(start)
        data = f.read(end - start + 1)
    response = HttpResponse(data, status=206, content_type="application/octet-stream")
    response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response["Accept-Ranges"] = "bytes"
    return response
