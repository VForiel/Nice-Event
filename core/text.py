import re
import unicodedata


def normalize(text):
    """Minuscules sans accents ni ponctuation : « Fête de la Musique ! » -> « fete de la musique »."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


# Caractères que Windows-1252 place sur les octets 0x80-0x9F (« Ã© » lu en cp1252 au lieu de « é » en UTF-8).
_CP1252 = {bytes([b]).decode("cp1252"): b for b in range(0x80, 0xA0) if b not in (0x81, 0x8D, 0x8F, 0x90, 0x9D)}
_CONT = "\u0080-\u00bf" + "".join(_CP1252)
MOJIBAKE = re.compile(f"(?:[\u00c2-\u00f4][{_CONT}]*)+ ?")
SUSPECT = re.compile(f"[\u00c2-\u00f4][{_CONT}]|[\u00c3\u00f0] ")


def _as_bytes(chars):
    return bytes(_CP1252.get(c, ord(c)) for c in chars)


def _plausible(char):
    """Caractère qu'on s'attend à trouver dans un agenda : latin, ponctuation, symboles, emojis (pas du lao…)."""
    n = ord(char)
    return n < 0x250 or 0x2000 <= n <= 0x2BFF or n >= 0x1F000 or n in (0xFE0F, 0x20E3)


def repair(text):
    """Répare l'UTF-8 lu comme du Latin-1 ou du Windows-1252 : « ApÃ©ro ðŸŽ¨ » -> « Apéro 🎨 ».

    Chaque suite suspecte n'est remplacée que si ses octets forment de l'UTF-8 valide : le texte correct
    (accents isolés, emojis déjà bons) n'est pas touché. Quand l'octet final était une espace insécable (A0) ou
    un saut de ligne (85) déjà ramené à une espace (« Ã raconter » pour « à raconter »), on le restitue.
    """
    if not text or not SUSPECT.search(text):
        return text

    def fix(match):
        chars = match.group(0)
        raw = _as_bytes(chars.rstrip(" "))
        candidates = [(raw + (b" " if chars.endswith(" ") else b""), "")]
        if chars.endswith(" "):
            # « Ã » + A0 = « à » ; pour un emoji (4 octets), 85 est plus courant (📅, 🎅, 🌅…).
            lost = [b"\xa0", b"\x85"] if raw[0] < 0xF0 else [b"\x85", b"\xa0"]
            candidates += [(raw + byte, " ") for byte in lost]
        for data, tail in candidates:
            try:
                fixed = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if all(_plausible(c) for c in fixed):
                return fixed + tail
        return chars

    return MOJIBAKE.sub(fix, text)


def decode(content, declared=None):
    """Octets d'une page ou d'un flux -> texte : UTF-8 s'il est valide (même si l'en-tête annonce autre chose,
    erreur fréquente), sinon l'encodage annoncé, sinon Windows-1252."""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return content.decode(declared or "cp1252", errors="replace")
    except LookupError:
        return content.decode("cp1252", errors="replace")


def without_emoji(text):
    """Retire les emojis (pour les visuels Pillow, dont les polices n'en ont pas : sinon des carrés vides)."""
    kept = "".join(c for c in text or "" if not (ord(c) >= 0x1F000 or 0x2600 <= ord(c) <= 0x27BF
                                                 or c in "️‍⃣"))
    return re.sub(r"\s{2,}", " ", kept).strip()
