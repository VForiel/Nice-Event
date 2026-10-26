"""Visuels des événements, générés par le serveur (Pillow) : réseaux sociaux, aperçus de liens, stories.

Avec photo : la photo recadrée sur son point focal, un bandeau bleu nuit avec catégorie, titre, date, lieu, prix.
Sans photo : un visuel dessiné aux couleurs de la catégorie, avec le résumé de l'événement en grand.
Toujours : le logo (la chaise bleue) et « nice-event.fr ».

Les images sont mises en cache dans MEDIA_ROOT/visuels/ ; leur nom change dès que l'événement est modifié.
"""

import hashlib
import math
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.utils import translation
from PIL import Image, ImageDraw, ImageFont, ImageOps

from core.text import without_emoji

FONTS = Path(__file__).resolve().parent / "fonts"
VERSION = 4  # à incrémenter quand le dessin change : tous les visuels sont régénérés

FORMATS = {
    "portrait": (1080, 1350),  # Instagram, Facebook
    "paysage": (1200, 675),  # X, Bluesky
    "og": (1200, 630),  # aperçus de liens (WhatsApp, Messenger, Slack…)
    "story": (1080, 1920),  # stories Instagram / Facebook
}

INK, PAPER, MUTED = "#12233f", "#fbf6ec", "#c3cbd8"
CHAISE, CORAIL, SOLEIL = "#1f6fd1", "#e4573d", "#ffc83d"
TONES = {"chaise": CHAISE, "corail": CORAIL, "ocre": "#e09a2c", "soleil": SOLEIL, "pin": "#2c7a55",
         "lavande": "#7559d4", "nuit": INK}
LIGHT_TONES = {"soleil", "ocre"}  # texte foncé sur ces couleurs


@lru_cache(maxsize=64)
def font(name, size):
    files = {"title": "BricolageGrotesque-ExtraBold.ttf", "cond": "BricolageGrotesque-CondensedBold.ttf",
             "text": "AtkinsonHyperlegibleNext-Regular.ttf", "bold": "AtkinsonHyperlegibleNext-Bold.ttf"}
    return ImageFont.truetype(str(FONTS / files[name]), size)


def rgb(color, alpha=255):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


# Texte ------------------------------------------------------------------------------------------------------------


def text_width(draw, text, f):
    return draw.textlength(text, font=f)


def wrap(draw, text, f, width, max_lines):
    """Lignes d'au plus `width` px ; la dernière se termine par « … » si le texte ne tient pas."""
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if text_width(draw, candidate, f) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        while text_width(draw, current, f) > width and len(current) > 1:  # mot plus long que la ligne
            cut = len(current)
            while cut > 1 and text_width(draw, current[:cut] + "-", f) > width:
                cut -= 1
            lines.append(current[:cut] + "-")
            current = current[cut:]
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and text_width(draw, last + "…", f) > width:
            last = last[:-1].rstrip()
        lines[-1] = last.rstrip(",;:.") + "…"
    return lines


def fit(draw, text, name, sizes, width, max_lines, max_height=None, leading=1.04):
    """Plus grande taille de `sizes` pour laquelle le texte tient en max_lines lignes (et max_height px)."""
    for size in sizes:
        f = font(name, size)
        lines = wrap(draw, text, f, width, max_lines + 1)
        height = len(lines) * size * leading
        if len(lines) <= max_lines and (max_height is None or height <= max_height):
            return f, lines
    f = font(name, sizes[-1])
    return f, wrap(draw, text, f, width, max_lines)


def draw_lines(draw, xy, lines, f, fill, leading=1.04):
    x, y = xy
    size = f.size
    for line in lines:
        draw.text((x, y), line, font=f, fill=fill)
        y += size * leading
    return y


def pill(draw, xy, text, f, fill, color, pad=(22, 10)):
    """Étiquette arrondie ; renvoie sa boîte."""
    x, y = xy
    w = text_width(draw, text, f)
    box = (x, y, x + w + 2 * pad[0], y + f.size + 2 * pad[1])
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=fill)
    draw.text((x + pad[0], y + pad[1] - f.size * 0.08), text, font=f, fill=color)
    return box


# Logo -------------------------------------------------------------------------------------------------------------


def logo(draw, x, y, height, dark_background):
    """La chaise bleue sous le soleil (repère 64 × 64 de static/img/logo-mark.svg) suivie de « nice-event.fr »."""
    k = height / 64

    def p(px, py):
        return (x + px * k, y + py * k)

    draw.ellipse([p(36, 6), p(54, 24)], fill=SOLEIL)
    w = max(2, round(5.5 * k))
    arm = [(18.5, 26)] + [(18.5 + (46 - 18.5) * t, 26 - 3.4 * math.sin(math.pi * t) * 0.9 + (25 - 26) * t)
                          for t in (0.25, 0.5, 0.75, 1)] + [(46, 34)]
    for path in ([(14, 9), (21, 37), (16, 56)], [(21, 37), (46, 34), (50, 56)], arm):
        pts = [p(*pt) for pt in path]
        draw.line(pts, fill=CHAISE if not dark_background else "#4a8fe6", width=w, joint="curve")
        for pt in (pts[0], pts[-1]):
            draw.ellipse([pt[0] - w / 2, pt[1] - w / 2, pt[0] + w / 2, pt[1] + w / 2], fill=CHAISE if not dark_background else "#4a8fe6")
    wave = [p(4 + i * 0.5, 60.5 - 1.6 * math.sin(i * 0.5 / 10 * 2 * math.pi)) for i in range(0, 121)]
    draw.line(wave, fill=CORAIL, width=max(1, round(3 * k)), joint="curve")
    f = font("title", round(height * 0.62))
    tx, ty = x + height + height * 0.18, y + height * 0.2
    name_color = PAPER if dark_background else INK
    draw.text((tx, ty), "nice-event", font=f, fill=name_color)
    draw.text((tx + text_width(draw, "nice-event", f), ty), ".fr", font=f, fill=SOLEIL if dark_background else CORAIL)
    return tx + text_width(draw, "nice-event.fr", f)


# Contenu ------------------------------------------------------------------------------------------------------------


def labels(event):
    """(catégorie, date, lieu, prix, mentions) en français : les visuels sont publiés par le compte francophone."""
    from core.templatetags.ne import clock, day_short

    with translation.override("fr"):
        cat = event.main_category
        start = event.local_start
        if event.all_day:
            when = day_short(start) + (" – " + day_short(event.local_end) if event.multi_day else " · toute la journée")
        else:
            when = f"{day_short(start)} · {clock(start)}"
        place = without_emoji(f"{event.venue.name}, {event.venue.commune.name}")
        extras = []
        if event.english_friendly:
            extras.append("EN friendly")
        if event.age_kind not in (event.Age.ALL,):
            extras.append(str(event.age_label))
        state = {"cancelled": "ANNULÉ", "postponed": "REPORTÉ", "full": "COMPLET"}.get(event.state, "")
        return (cat.name if cat else "Événement"), when.upper(), place, str(event.price_label), extras, state


def cover(photo_path, size, focal):
    """Recadre la photo pour remplir `size` en gardant le point focal visible."""
    img = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB")
    w, h = size
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.LANCZOS)
    fx, fy = focal
    left = min(max(0, round(img.width * fx - w / 2)), img.width - w)
    top = min(max(0, round(img.height * fy - h / 2)), img.height - h)
    return img.crop((left, top, left + w, top + h))


def decor(img, tone, scale):
    """Motif des visuels sans photo : grand disque clair, soleil, rayures de store, vague."""
    W, H = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    r = W * 0.42
    d.ellipse([W - r * 1.25, -r * 0.75, W + r * 0.75, r * 1.25], fill=(255, 255, 255, 38))
    sun = SOLEIL if tone not in ("soleil", "ocre") else PAPER
    s = 46 * scale
    d.ellipse([W - 150 * scale - s, 90 * scale - s, W - 150 * scale + s, 90 * scale + s], fill=rgb(sun))
    band_top = H - 150 * scale
    step = 44 * scale
    x = 0
    while x < W:
        d.rectangle([x, band_top, x + step / 2, band_top + 26 * scale], fill=(255, 255, 255, 46))
        x += step
    img.alpha_composite(overlay)


def render(event, fmt="portrait"):
    W, H = FORMATS[fmt]
    img = Image.new("RGBA", (W, H), rgb(INK))
    draw = ImageDraw.Draw(img)
    category, when, place, price, extras, state = labels(event)
    cat = event.main_category
    tone = cat.tone if cat else "nuit"
    tone_color = TONES.get(tone, INK)
    vertical = H > W
    scale = W / 1080 if vertical else H / 675
    margin = round(72 * scale) if vertical else round(56 * scale)
    photo = event.photo and Path(event.photo.path).exists()

    if photo:
        if vertical:
            split = round(H * (0.6 if fmt == "portrait" else 0.56))
            img.paste(cover(event.photo.path, (W, split), (event.focal_x, event.focal_y)), (0, 0))
            panel = (0, split, W, H)
        else:
            split = round(W * 0.47)
            img.paste(cover(event.photo.path, (W - split, H), (event.focal_x, event.focal_y)), (split, 0))
            panel = (0, 0, split, H)
        draw.rectangle(panel, fill=INK)
        text_color, sub_color, dark = PAPER, MUTED, True
        x0, top, x1 = panel[0] + margin, panel[1], panel[2] - margin
        pf = font("cond", round(34 * scale))
        pill_bg = SOLEIL if tone == "nuit" else tone_color
        pill_fg = INK if tone in LIGHT_TONES or tone == "nuit" else "#ffffff"
        if vertical:
            pill(draw, (x0, top - pf.size // 2 - round(10 * scale)), category.upper(), pf, pill_bg, pill_fg,
                 pad=(round(22 * scale), round(10 * scale)))
            y = top + round(70 * scale)
        else:
            y = top + margin
            box = pill(draw, (x0, y), category.upper(), pf, pill_bg, pill_fg, pad=(round(18 * scale), round(8 * scale)))
            y = box[3] + round(26 * scale)
        if state:
            pill(draw, (panel[2] - margin - 300 * scale, panel[1] + (margin if not vertical else 24 * scale)), state,
                 font("cond", round(30 * scale)), CORAIL, "#ffffff")
        footer = round(110 * scale)
        room = panel[3] - footer - y - round((140 if vertical else 120) * scale)
        sizes = [round(s * scale) for s in ((92, 84, 76, 68, 60, 54) if vertical else (64, 58, 52, 46, 42, 38))]
        tf, lines = fit(draw, without_emoji(event.title_tr), "title", sizes, x1 - x0, 3, room)
        y = draw_lines(draw, (x0, y), lines, tf, text_color) + round(18 * scale)
        draw.text((x0, y), when, font=font("bold", round(36 * scale)), fill=SOLEIL)
        y += round(50 * scale)
        place_lines = wrap(draw, place, font("text", round(34 * scale)), x1 - x0, 2)
        y = draw_lines(draw, (x0, y), place_lines, font("text", round(34 * scale)), sub_color, 1.2)
        if not vertical:
            pill(draw, (x0, y + round(14 * scale)), price, font("title", round(32 * scale)), SOLEIL, INK,
                 pad=(round(16 * scale), round(8 * scale)))
    else:
        img.paste(Image.new("RGBA", (W, H), rgb(tone_color)), (0, 0))
        decor(img, tone, scale)
        draw = ImageDraw.Draw(img)
        dark = tone not in LIGHT_TONES
        text_color = "#ffffff" if dark else INK
        x0, x1 = margin, W - margin
        y = round((120 if vertical else 56) * scale)
        pf = font("cond", round(34 * scale))
        box = pill(draw, (x0, y), category.upper(), pf, INK if tone != "nuit" else SOLEIL, PAPER if tone != "nuit" else INK,
                   pad=(round(22 * scale), round(10 * scale)))
        if state:
            pill(draw, (box[2] + 16 * scale, y), state, pf, CORAIL if tone != "corail" else INK, "#ffffff",
                 pad=(round(22 * scale), round(10 * scale)))
        y = box[3] + round(36 * scale)
        width = (x1 - x0) if vertical else (x1 - x0) * 0.78
        sizes = [round(s * scale) for s in ((168, 150, 134, 118, 104, 92, 82, 72) if vertical else (84, 76, 68, 60, 54, 48))]
        tf, lines = fit(draw, without_emoji(event.title_tr), "title", sizes, width, 4 if fmt == "story" else 3)
        y = draw_lines(draw, (x0, y), lines, tf, text_color, 1.0) + round(28 * scale)
        # Encadré date et lieu au-dessus du pied (et de la mention « infos » en story) ; le résumé occupe l'espace restant.
        bf, lf = font("title", round(40 * scale)), font("text", round(30 * scale))
        place_line = wrap(draw, place, lf, (x1 - x0) * 0.8, 1)[0]
        bw = max(text_width(draw, when, bf), text_width(draw, place_line, lf)) + 56 * scale
        bh = bf.size + lf.size + 52 * scale
        by = H - round((330 if fmt == "story" else 170 if vertical else 140) * scale) - bh
        sf = font("text", round((52 if fmt == "story" else 46 if vertical else 30) * scale))
        line_h = sf.size * 1.32
        room = int((by - y - 24 * scale) // line_h)
        if room > 0:
            summary_lines = wrap(draw, without_emoji(event.summary_tr), sf, width * 0.92, min(room, 7))
            draw_lines(draw, (x0, y), summary_lines, sf, text_color, 1.32)
        draw.rounded_rectangle([x0, by, x0 + bw, by + bh], radius=round(14 * scale), fill=PAPER)
        draw.text((x0 + 28 * scale, by + 18 * scale), when, font=bf, fill=INK)
        draw.text((x0 + 28 * scale, by + 26 * scale + bf.size), place_line, font=lf, fill="#4f5b6e")
        sub_color = text_color

    # Pied : logo, prix, mentions
    footer_h = round(64 * scale)
    fy = H - round((92 if vertical else 76) * scale)
    end_logo = logo(draw, x0, fy, footer_h, dark)
    price_font = font("title", round(34 * scale))
    right = (panel[2] if photo else W) - margin
    chips = ([] if photo and not vertical else [price]) + ([extras[0]] if extras and vertical else [])
    for text in reversed(chips):
        w = text_width(draw, text, price_font) + 36 * scale
        left = right - w
        if left < end_logo + 20 * scale:
            break
        is_price = text == price
        on_yellow = not photo and tone in LIGHT_TONES
        bg = (INK if on_yellow else SOLEIL) if is_price else (PAPER if dark else INK)
        draw.rounded_rectangle([left, fy + 6 * scale, right, fy + footer_h - 4 * scale], radius=round(12 * scale), fill=bg)
        draw.text((left + 18 * scale, fy + 12 * scale), text, font=price_font, fill=PAPER if bg == INK else INK)
        right = left - 12 * scale
    if fmt == "story":
        info = "Toutes les infos sur nice-event.fr"
        sf = font("bold", round(34 * scale))
        draw.text((x0, H - 250 * scale), info, font=sf, fill=sub_color)
    return img.convert("RGB")


# Cache ------------------------------------------------------------------------------------------------------------


def cache_key(event, fmt):
    photo = event.photo.name if event.photo else ""
    raw = f"{VERSION}|{fmt}|{event.pk}|{event.updated_at.isoformat()}|{photo}|{event.focal_x}|{event.focal_y}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def visual_path(event, fmt):
    """Chemin du visuel (généré au besoin), en JPEG : seul format accepté par l'API Instagram."""
    folder = Path(settings.MEDIA_ROOT) / "visuels" / str(event.pk)
    target = folder / f"{fmt}-{cache_key(event, fmt)}.jpg"
    if not target.exists():
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob(f"{fmt}-*.jpg"):
            old.unlink(missing_ok=True)
        tmp = target.with_suffix(".tmp")
        render(event, fmt).save(tmp, "JPEG", quality=88, optimize=True, progressive=True)
        tmp.replace(target)
    return target


def visual_url(event, fmt):
    path = visual_path(event, fmt)
    return f"{settings.MEDIA_URL}{path.relative_to(settings.MEDIA_ROOT).as_posix()}"
