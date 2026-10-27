"""Normalisation des images téléversées : orientation, taille maximale, WebP."""

import io
import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1600
MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 40_000_000  # ~ 8000 × 5000 : au-delà, la conversion mobiliserait trop de mémoire
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def validate_image(uploaded):
    """Refuse avant enregistrement les fichiers trop lourds ou aux dimensions démesurées (bombe de décompression)."""
    if uploaded.size > MAX_BYTES:
        raise ValidationError(_("Image trop lourde (12 Mo maximum)."))
    try:
        uploaded.seek(0)
        width, height = Image.open(uploaded).size  # ne lit que l'en-tête
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise ValidationError(_("Image illisible ou trop grande. Essaie en JPEG ou PNG."))
    finally:
        uploaded.seek(0)
    if width * height > MAX_PIXELS:
        raise ValidationError(_("Image trop grande (40 mégapixels maximum)."))


def to_webp(uploaded, max_side=MAX_SIDE):
    """Renvoie un ContentFile WebP à partir d'un fichier image téléversé."""
    img = Image.open(uploaded)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=82, method=6)
    name = Path(getattr(uploaded, "name", "image")).stem[:60] + ".webp"
    return ContentFile(buf.getvalue(), name=name)


def normalize_field(instance, field_name, max_side=MAX_SIDE):
    """Convertit le fichier d'un ImageField s'il vient d'être téléversé (pas encore enregistré)."""
    field = getattr(instance, field_name)
    if field and not field._committed:
        field.file.seek(0)
        webp = to_webp(field.file, max_side)
        field.save(webp.name, webp, save=False)


def thumbnail_url(field, size):
    """URL d'une copie réduite (plus petit côté = size px, WebP), créée au premier affichage dans media/thumbs/.

    Les listes affichent les photos en vignettes : sans cela, chaque vignette de 96 px coûte une image de 1600 px.
    En cas d'erreur (fichier absent, illisible), renvoie l'image d'origine.
    """
    if not field:
        return ""
    name = field.name
    root = Path(settings.MEDIA_ROOT)
    source = root / name
    rel = f"thumbs/{size}/{Path(name).with_suffix('.webp').as_posix()}"
    target = root / rel
    try:
        mtime = source.stat().st_mtime
        if not target.exists() or target.stat().st_mtime < mtime:
            img = Image.open(source)
            img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
            scale = size / min(img.size)
            if scale < 1:
                img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
            img.save(tmp, "WEBP", quality=80, method=4)
            os.replace(tmp, target)  # écriture atomique : plusieurs processus gunicorn peuvent servir la page
    except (OSError, Image.DecompressionBombError):
        return field.url
    return f"{settings.MEDIA_URL}{rel}?v={int(mtime)}"


VIDEO_MAX_BYTES = 50 * 1024 * 1024
VIDEO_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}


def validate_video(uploaded):
    """Vidéos MP4, MOV ou WebM d'au plus 50 Mo, vérifiées sur leur signature (pas seulement l'extension)."""
    suffix = Path(uploaded.name).suffix.lower()
    if suffix not in VIDEO_TYPES:
        raise ValidationError(_("Format de vidéo non pris en charge (MP4, MOV ou WebM). Partage-la plutôt par un lien "
                                "(YouTube, Google Photos…)."))
    if uploaded.size > VIDEO_MAX_BYTES:
        raise ValidationError(_("Vidéo trop lourde (50 Mo maximum) : mets-la sur YouTube, Vimeo ou Google Photos et "
                                "colle le lien."))
    uploaded.seek(0)
    head = uploaded.read(12)
    uploaded.seek(0)
    if not (head[4:8] == b"ftyp" or head[:4] == b"\x1a\x45\xdf\xa3"):
        raise ValidationError(_("Ce fichier n'est pas une vidéo lisible."))


def is_video_name(name):
    return Path(name).suffix.lower() in VIDEO_TYPES
