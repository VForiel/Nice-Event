"""Fichiers téléversés, servis par Django avec un cache navigateur d'une semaine (les noms changent à chaque nouveau
téléversement). Le reverse proxy partagé de VPS1 n'a pas accès au volume des données, d'où ce passage par Django."""

import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.http import Http404, StreamingHttpResponse
from django.utils._os import safe_join
from django.views.static import serve

CACHE = "public, max-age=604800"
RANGE = re.compile(r"bytes=(\d*)-(\d*)$")
CHUNK = 256 * 1024


def media(request, path):
    # Vidéos : lecture par plages d'octets (indispensable à Safari, et pour avancer dans la vidéo)
    if request.headers.get("Range") and Path(path).suffix.lower() in (".mp4", ".webm", ".mov", ".m4v"):
        response = ranged(request, path)
    else:
        response = serve(request, path, document_root=settings.MEDIA_ROOT)
    response["Cache-Control"] = CACHE
    return response


def ranged(request, path):
    try:
        file = Path(safe_join(settings.MEDIA_ROOT, path))
    except ValueError:
        raise Http404
    if not file.is_file():
        raise Http404
    size = file.stat().st_size
    match = RANGE.match(request.headers["Range"].strip())
    if not match or not (match[1] or match[2]):
        return serve(request, path, document_root=settings.MEDIA_ROOT)
    if match[1]:
        start, end = int(match[1]), min(int(match[2]) if match[2] else size - 1, size - 1)
    else:  # « bytes=-500 » : les 500 derniers octets
        start, end = max(0, size - int(match[2])), size - 1
    if start > end or start >= size:
        response = StreamingHttpResponse([], status=416)
        response["Content-Range"] = f"bytes */{size}"
        return response

    def chunks():
        with open(file, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                data = f.read(min(CHUNK, left))
                if not data:
                    break
                left -= len(data)
                yield data

    response = StreamingHttpResponse(chunks(), status=206,
                                     content_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream")
    response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response["Content-Length"] = str(end - start + 1)
    response["Accept-Ranges"] = "bytes"
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
