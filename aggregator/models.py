"""Agendas externes scannés trois fois par jour (voir aggregator.jobs)."""

from django.db import models

from siteconfig.crypto import EncryptedTextField


class Source(models.Model):
    class Kind(models.TextChoices):
        ICAL = "ical", "Flux iCal (.ics)"
        JSONLD = "jsonld", "Pages avec données schema.org Event (JSON-LD)"
        OPENAGENDA = "openagenda", "API OpenAgenda"
        WPNICE = "wpnice", "API WordPress de la Ville de Nice (nice.fr, Opéra de Nice)"
        TRIBE = "tribe", "API The Events Calendar (sites WordPress de nombreuses communes)"

    name = models.CharField("nom affiché", max_length=120, help_text="Apparaît sur les événements : « via … »")
    slug = models.SlugField(unique=True)
    kind = models.CharField("type", max_length=12, choices=Kind.choices)
    url = models.URLField("adresse", max_length=500,
                          help_text="Flux iCal ; page listant les événements (JSON-LD) ou liste de l'API WordPress ; adresse de l'agenda "
                                    "OpenAgenda ; API de la Ville de Nice (https://www.nice.fr/wp-json/wp/v2/events) ; "
                                    "The Events Calendar : adresse du site (https://www.commune.fr/).")
    website = models.URLField("site de la source", blank=True)
    api_key = EncryptedTextField("clé d'API", blank=True, help_text="OpenAgenda : clé publique du compte.")
    is_active = models.BooleanField("active", default=True)
    default_category = models.ForeignKey("events.Category", null=True, blank=True, on_delete=models.SET_NULL,
                                         verbose_name="catégorie par défaut")
    default_commune = models.ForeignKey("venues.Commune", null=True, blank=True, on_delete=models.SET_NULL,
                                        verbose_name="commune par défaut",
                                        help_text="Quand la source n'indique pas de lieu reconnaissable.")
    max_pages = models.PositiveSmallIntegerField("pages de liste à suivre", default=3,
                                                 help_text="JSON-LD : nombre de pages de la liste parcourues (lien « suivant »).")
    link_pattern = models.CharField(
        "motif des liens d'événements", max_length=200, blank=True,
        help_text="JSON-LD, quand la page de liste n'a pas de liste structurée : expression régulière des adresses de pages "
                  "d'événements à ouvrir, ex. ^https://unidivers\\.fr/event/[^/]+/?$")
    title_pattern = models.CharField(
        "ne garder que les titres", max_length=200, blank=True,
        help_text="Expression régulière : seuls les événements dont le titre correspond sont repris "
                  "(ex. ^OGC Nice - pour les seuls matchs à domicile).")
    default_place = models.CharField("lieu par défaut", max_length=120, blank=True,
                                     help_text="Quand la source n'indique pas de lieu (calendrier de matchs, Meetup…).")
    images_allowed = models.BooleanField("reprendre les images", default=True,
                                         help_text="Image de l'événement (flux, ou page de l'événement à défaut). "
                                                   "À décocher si la source s'y oppose.")
    notes = models.TextField("notes", blank=True)
    scan_requested = models.BooleanField("scan demandé", default=False, help_text="Traité par la tâche de fond dans la minute.")

    last_run_at = models.DateTimeField("dernier scan", null=True, blank=True)
    last_ok = models.BooleanField("dernier scan réussi", default=True)
    last_message = models.TextField("compte rendu", blank=True)
    last_found = models.PositiveIntegerField("trouvés", default=0)
    last_created = models.PositiveIntegerField("nouveaux", default=0)
    last_updated = models.PositiveIntegerField("mis à jour", default=0)
    last_empty_runs = models.PositiveSmallIntegerField("scans vides d'affilée", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "source"

    def __str__(self):
        return self.name
