"""Agendas externes scannés trois fois par jour (voir aggregator.jobs)."""

from django.db import models

from siteconfig.crypto import EncryptedTextField


class Source(models.Model):
    class Kind(models.TextChoices):
        ICAL = "ical", "Flux iCal (.ics)"
        JSONLD = "jsonld", "Pages avec données schema.org Event (JSON-LD)"
        RSS = "rss", "Flux RSS / Atom"
        OPENAGENDA = "openagenda", "API OpenAgenda"

    name = models.CharField("nom affiché", max_length=120, help_text="Apparaît sur les événements : « via … »")
    slug = models.SlugField(unique=True)
    kind = models.CharField("type", max_length=12, choices=Kind.choices)
    url = models.URLField("adresse", max_length=500,
                          help_text="Flux iCal/RSS, page listant les événements (JSON-LD), ou identifiant OpenAgenda "
                                    "(https://openagenda.com/agendas/<uid>).")
    website = models.URLField("site de la source", blank=True)
    api_key = EncryptedTextField("clé d'API", blank=True, help_text="OpenAgenda : clé publique du compte.")
    is_active = models.BooleanField("active", default=True)
    default_category = models.ForeignKey("events.Category", null=True, blank=True, on_delete=models.SET_NULL,
                                         verbose_name="catégorie par défaut")
    default_commune = models.ForeignKey("venues.Commune", null=True, blank=True, on_delete=models.SET_NULL,
                                        verbose_name="commune par défaut",
                                        help_text="Quand la source n'indique pas de lieu reconnaissable.")
    images_allowed = models.BooleanField("reprendre les images", default=False,
                                         help_text="Seulement si la licence de la source le permet (ex. OpenAgenda, DATAtourisme).")
    notes = models.TextField("notes", blank=True)

    last_run_at = models.DateTimeField("dernier scan", null=True, blank=True)
    last_ok = models.BooleanField("dernier scan réussi", default=True)
    last_message = models.TextField("compte rendu", blank=True)
    last_found = models.PositiveIntegerField("trouvés", default=0)
    last_created = models.PositiveIntegerField("nouveaux", default=0)
    last_updated = models.PositiveIntegerField("mis à jour", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "source"

    def __str__(self):
        return self.name
