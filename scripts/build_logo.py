"""Génère les fichiers du logo Nice-Event (piste A, « la chaise bleue ») dans static/img/.

Le mot « nice-event.fr » est converti en tracés depuis Bricolage Grotesque (graisse 800) : les SVG ne dépendent
d'aucune police installée. Dépendances de développement uniquement : fonttools, brotli, uharfbuzz.

    python scripts/build_logo.py
"""

import io
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "static/fonts/bricolage-grotesque-latin-standard-normal.woff2"
OUT = ROOT / "static/img"

INK, PAPER = "#12233f", "#fbf6ec"
CHAISE, CORAIL, SOLEIL = "#1f6fd1", "#e4573d", "#ffc83d"

# Symbole 64 × 64 : la chaise de la Promenade de profil, sous le soleil, au-dessus d'une vague.
MARK = f"""<circle cx="45" cy="15" r="9" fill="{SOLEIL}"/>
<g fill="none" stroke="{CHAISE}" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round">
<path d="M14 9 L21 37 L16 56"/><path d="M21 37 L46 34 L50 56"/><path d="M18.5 26 C27 23 37 23 46 25 L46 34"/>
</g>
<path d="M4 60.5 q5 -3.2 10 0 t10 0 t10 0 t10 0 t10 0 t10 0" fill="none" stroke="{CORAIL}" stroke-width="3" stroke-linecap="round"/>"""

# Version petite taille (favicon) : traits plus épais, sans la vague, cadrage serré.
FAVICON = f"""<circle cx="46" cy="14" r="11" fill="{SOLEIL}"/>
<g fill="none" stroke="{CHAISE}" stroke-width="7.5" stroke-linecap="round" stroke-linejoin="round">
<path d="M12 6 L20 37 L14 59"/><path d="M20 37 L47 34 L52 59"/><path d="M17 24 C27 21 38 21 47 23.5 L47 34"/>
</g>"""


def static_font():
    font = TTFont(FONT)
    instantiateVariableFont(font, {"wght": 800, "wdth": 100, "opsz": 48}, inplace=True)
    buf = io.BytesIO()
    font.flavor = None
    font.save(buf)
    return font, buf.getvalue()


def text_paths(text, size, tracking=-0.035):
    """Tracés SVG du texte (crénage et ligatures via HarfBuzz) ; renvoie (path, largeur), ligne de base en y = 0."""
    font, data = static_font()
    upem = font["head"].unitsPerEm
    hb_font = hb.Font(hb.Face(data))
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hb_font, buf, {"kern": True, "liga": True})
    glyphs = font.getGlyphSet()
    order = font.getGlyphOrder()
    scale = size / upem
    x = 0.0
    parts = []
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        pen = SVGPathPen(glyphs)
        glyphs[order[info.codepoint]].draw(TransformPen(pen, (scale, 0, 0, -scale, x + pos.x_offset * scale, -pos.y_offset * scale)))
        parts.append(pen.getCommands())
        x += pos.x_advance * scale + tracking * size
    return " ".join(p for p in parts if p), x - tracking * size


def svg(width, height, body, title="Nice-Event"):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.1f} {height:.1f}" role="img" aria-label="{title}">'
            f"<title>{title}</title>\n{body}\n</svg>\n")


def lockup(word_color, fr_color):
    size = 46
    name, w_name = text_paths("nice-event", size)
    fr, w_fr = text_paths(".fr", size)
    gap, mark = 14, 64
    baseline = 47  # aligne la hauteur d'x du texte sur le corps de la chaise
    x0 = mark + gap
    body = (f'<g>{MARK}</g>\n'
            f'<path transform="translate({x0} {baseline})" fill="{word_color}" d="{name}"/>\n'
            f'<path transform="translate({x0 + w_name - 0.035 * size:.2f} {baseline})" fill="{fr_color}" d="{fr}"/>')
    return svg(x0 + w_name + w_fr - 0.035 * size + 2, 64, body, "nice-event.fr")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "logo-mark.svg").write_text(svg(64, 64, MARK), encoding="utf-8")
    (OUT / "favicon.svg").write_text(svg(64, 64, FAVICON), encoding="utf-8")
    (OUT / "logo.svg").write_text(lockup(INK, CORAIL), encoding="utf-8")
    (OUT / "logo-dark.svg").write_text(lockup(PAPER, SOLEIL), encoding="utf-8")
    # Avatar des réseaux sociaux : symbole centré sur un disque papier (recadré en rond par les réseaux).
    avatar = f'<rect width="64" height="64" fill="{PAPER}"/><g transform="translate(10 9) scale(.69)">{MARK}</g>'
    (OUT / "avatar.svg").write_text(svg(64, 64, avatar), encoding="utf-8")
    print("ok :", ", ".join(sorted(p.name for p in OUT.glob("*.svg"))))


if __name__ == "__main__":
    main()
