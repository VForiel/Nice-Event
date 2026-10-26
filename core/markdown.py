"""Rendu Markdown -> HTML nettoyé (descriptions d'événements, profils, pages)."""

import re

import markdown as md
import nh3
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe

ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "em", "figure", "figcaption", "h2", "h3", "h4", "hr", "i",
    "img", "li", "ol", "p", "pre", "strong", "sub", "sup", "table", "tbody", "td", "th", "thead", "tr", "ul",
}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "loading"},
    "abbr": {"title"},
    "th": {"align"},
    "td": {"align"},
}

# Adresse web nue (pas déjà dans un lien Markdown ou HTML) : on la rend cliquable.
BARE_URL = re.compile(r"(?<![(\[<\"'=/])\b(https?://[^\s<>()\[\]]+[^\s<>()\[\].,;:!?'\"])")


def render(text):
    """Markdown en HTML sûr : seules les balises de mise en forme passent, les adresses nues deviennent des liens."""
    text = BARE_URL.sub(lambda m: f"<{m.group(1)}>", text or "")
    raw = md.markdown(text, extensions=["extra", "sane_lists", "smarty"], output_format="html")
    # Les titres de niveau 1 sont réservés au titre de la page.
    raw = re.sub(r"<(/?)h1>", r"<\1h2>", raw)
    clean = nh3.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto", "tel"},
        link_rel="noopener noreferrer",
        set_tag_attribute_values={"img": {"loading": "lazy"}},
    )
    return mark_safe(clean)


def plain(text, length=None):
    """Texte brut tiré du Markdown (résumés, balises meta)."""
    out = strip_tags(md.markdown(text or ""))
    out = re.sub(r"\s+", " ", out).strip()
    if length and len(out) > length:
        out = out[: length - 1].rsplit(" ", 1)[0].rstrip(",;:.") + "…"
    return out
