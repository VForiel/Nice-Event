import re
import unicodedata


def normalize(text):
    """Minuscules sans accents ni ponctuation : « Fête de la Musique ! » -> « fete de la musique »."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()
