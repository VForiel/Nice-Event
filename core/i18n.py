"""Contenu bilingue : chaque champ traduisible a une version anglaise facultative (`<champ>_en`)."""

from django.utils.translation import get_language


def is_english():
    return (get_language() or "fr").startswith("en")


class Translated:
    """Renvoie la version anglaise du champ si la langue active est l'anglais et qu'elle est remplie,
    sinon la version française. S'utilise comme attribut de classe : `title_tr = Translated("title")`."""

    def __init__(self, name):
        self.name = name

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        if is_english():
            value = getattr(obj, f"{self.name}_en", "")
            if value:
                return value
        return getattr(obj, self.name)
