"""Événements : publiés par les membres, ou récupérés sur des agendas externes (app aggregator)."""

import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core import markdown
from core.i18n import Translated
from core.images import normalize_field, validate_image
from core.text import normalize


def euros(value):
    """18 -> « 18 », 7.5 -> « 7,50 »."""
    value = Decimal(str(value))
    return f"{value:.0f}" if value == value.to_integral_value() else f"{value:.2f}".replace(".", ",")


class Category(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField("nom", max_length=80)
    name_en = models.CharField("nom (anglais)", max_length=80)
    emoji = models.CharField("emoji (carte)", max_length=8)
    tone = models.CharField("couleur", max_length=10)
    icon = models.CharField("pictogramme", max_length=20)
    order = models.PositiveSmallIntegerField("ordre", default=0)

    name_tr = Translated("name")

    class Meta:
        ordering = ["order"]
        verbose_name = "catégorie"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("events:list") + f"?categorie={self.slug}"


class EventQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Event.Status.PUBLISHED)

    def upcoming(self):
        return self.filter(ends_at__gte=timezone.now()).order_by("starts_at")

    def past(self):
        return self.filter(ends_at__lt=timezone.now()).order_by("-starts_at")

    def internal(self):
        return self.filter(source__isnull=True)

    def external(self):
        return self.filter(source__isnull=False)

    def between(self, start, end):
        """Événements qui ont lieu (au moins en partie) entre start et end."""
        return self.filter(starts_at__lt=end, ends_at__gte=start)


class Event(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("En attente de modération")
        PUBLISHED = "published", _("Publié")
        HIDDEN = "hidden", _("Masqué")

    class State(models.TextChoices):
        SCHEDULED = "scheduled", _("Prévu")
        FULL = "full", _("Complet")
        POSTPONED = "postponed", _("Reporté")
        CANCELLED = "cancelled", _("Annulé")

    class Price(models.TextChoices):
        FREE = "free", _("Gratuit")
        PAID = "paid", _("Payant")
        PWYW = "pwyw", _("Prix libre")
        UNKNOWN = "unknown", _("Prix : voir le site")  # événements externes sans prix connu

    class Age(models.TextChoices):
        ALL = "all", _("Tout public")
        FAMILY = "family", _("Famille et enfants")
        FROM = "from", _("À partir d'un âge")
        RANGE = "range", _("Tranche d'âge")
        ADULTS = "adults", _("18 ans et plus")

    class Language(models.TextChoices):
        FR = "fr", _("En français")
        INTERNATIONAL = "international", _("International : accessible sans parler français")
        NONE = "none", _("Sans barrière de langue (musique, sport…)")

    class Access(models.TextChoices):
        UNKNOWN = "", _("Je ne sais pas")
        YES = "yes", _("Oui")
        NO = "no", _("Non")

    SPOKEN = [("fr", _("Français")), ("en", _("Anglais")), ("it", _("Italien")), ("es", _("Espagnol")),
              ("de", _("Allemand")), ("other", _("Autre"))]

    # Essentiel
    title = models.CharField(_("titre"), max_length=140)
    title_en = models.CharField(_("titre (anglais)"), max_length=140, blank=True)
    slug = models.SlugField(unique=True, max_length=170)
    categories = models.ManyToManyField(Category, related_name="events", verbose_name=_("catégories"))
    photo = models.ImageField(_("photo ou affiche"), upload_to="evenements/%Y/", blank=True, validators=[validate_image])
    # Point à garder visible quand la photo est recadrée (visuels, vignettes) : 0 = gauche/haut, 1 = droite/bas.
    focal_x = models.FloatField(default=0.5)
    focal_y = models.FloatField(default=0.5)
    summary = models.CharField(_("résumé"), max_length=200,
                               help_text=_("Une ou deux phrases : elles apparaissent dans les listes, sur la carte et sur les visuels."))
    summary_en = models.CharField(_("résumé (anglais)"), max_length=200, blank=True)
    description = models.TextField(_("description"), blank=True)
    description_en = models.TextField(_("description (anglais)"), blank=True)

    # Quand
    starts_at = models.DateTimeField(_("début"), db_index=True)
    end = models.DateTimeField(_("fin"), null=True, blank=True)
    all_day = models.BooleanField(_("toute la journée"), default=False)
    # Fin effective (fin saisie, sinon fin de journée ou début + 3 h) : sert aux requêtes « à venir ».
    ends_at = models.DateTimeField(db_index=True, editable=False)
    series = models.UUIDField(null=True, blank=True, db_index=True, editable=False,
                              help_text="Occurrences d'un même événement répété")

    # Où
    venue = models.ForeignKey("venues.Venue", on_delete=models.PROTECT, related_name="events", verbose_name=_("lieu"))
    access_notes = models.CharField(_("précisions d'accès"), max_length=200, blank=True,
                                    help_text=_("Étage, entrée, parking, arrêt de tram…"))
    accessible = models.CharField(_("accessible en fauteuil roulant"), max_length=3, choices=Access.choices, blank=True)

    # Prix
    price_kind = models.CharField(_("prix"), max_length=7, choices=Price.choices, default=Price.FREE)
    price_min = models.DecimalField(_("prix (à partir de)"), max_digits=7, decimal_places=2, null=True, blank=True)
    price_max = models.DecimalField(_("prix maximum"), max_digits=7, decimal_places=2, null=True, blank=True)
    booking_required = models.BooleanField(_("réservation obligatoire"), default=False)
    ticket_url = models.URLField(_("lien de billetterie ou d'inscription"), blank=True, max_length=500)
    capacity = models.PositiveIntegerField(_("nombre de places"), null=True, blank=True,
                                           help_text=_("Facultatif : affiche « complet » quand autant de membres ont cliqué « J'y vais »."))

    # Pour qui
    age_kind = models.CharField(_("public"), max_length=6, choices=Age.choices, default=Age.ALL)
    age_min = models.PositiveSmallIntegerField(_("âge minimum"), null=True, blank=True)
    age_max = models.PositiveSmallIntegerField(_("âge maximum"), null=True, blank=True)
    language = models.CharField(_("langue"), max_length=13, choices=Language.choices, default=Language.FR)
    spoken = models.CharField(_("langues parlées sur place"), max_length=60, blank=True, help_text="Codes séparés par des virgules")

    # Qui
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="organized_events", verbose_name=_("publié par"))
    organizer_name = models.CharField(_("organisé par"), max_length=120, blank=True,
                                      help_text=_("Nom de l'asso, du bar, de la salle… Vide : ton nom."))
    organizer_url = models.URLField(_("site, Instagram ou Facebook de l'organisateur"), blank=True, max_length=300)

    # État
    status = models.CharField("statut", max_length=10, choices=Status.choices, default=Status.PUBLISHED, db_index=True)
    state = models.CharField(_("état"), max_length=10, choices=State.choices, default=State.SCHEDULED)
    featured = models.BooleanField("sélection de l'équipe", default=False)
    moderation_note = models.CharField("note de modération", max_length=300, blank=True)

    # Événement externe (récupéré par l'agrégateur)
    source = models.ForeignKey("aggregator.Source", null=True, blank=True, on_delete=models.CASCADE, related_name="events")
    external_id = models.CharField(max_length=300, blank=True, db_index=True)
    external_url = models.URLField("page d'origine", blank=True, max_length=500)
    missing_since = models.DateTimeField("absent de la source depuis", null=True, blank=True)

    search = models.TextField(blank=True, editable=False)  # titre, résumé, lieu, organisateur sans accents
    views = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    objects = EventQuerySet.as_manager()

    title_tr = Translated("title")
    summary_tr = Translated("summary")
    description_tr = Translated("description")

    class Meta:
        ordering = ["starts_at"]
        verbose_name = "événement"
        constraints = [models.UniqueConstraint(fields=["source", "external_id"], condition=Q(source__isnull=False),
                                               name="unique_external_event")]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            local = timezone.localtime(self.starts_at)
            base = f"{slugify(self.title)[:120] or 'evenement'}-{local:%Y-%m-%d}"
            slug, n = base, 2
            while Event.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        self.ends_at = self.compute_ends_at()
        if self.status == self.Status.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        normalize_field(self, "photo")
        self.search = normalize(" ".join(filter(None, [
            self.title, self.title_en, self.summary, self.summary_en, self.organizer_name,
            self.venue.name if self.venue_id else "", self.venue.commune.name if self.venue_id else "",
        ])))
        super().save(*args, **kwargs)

    def compute_ends_at(self):
        if self.end:
            return self.end
        if self.all_day:
            day = timezone.localtime(self.starts_at).date()
            return timezone.make_aware(datetime.combine(day, time(23, 59)))
        return self.starts_at + timedelta(hours=3)

    def get_absolute_url(self):
        return reverse("events:detail", args=[self.slug])

    # Présentation ----------------------------------------------------------------------------------------------

    @property
    def is_external(self):
        return self.source_id is not None

    @property
    def link(self):
        """Lien des cartes de liste : page du site (les externes y ont aussi une fiche courte, avec le lien sortant)."""
        return self.get_absolute_url()

    @property
    def main_category(self):
        cats = getattr(self, "_prefetched_objects_cache", {}).get("categories")
        if cats is not None:
            return cats[0] if cats else None
        return self.categories.first()

    @property
    def description_html(self):
        return markdown.render(self.description_tr)

    @property
    def local_start(self):
        return timezone.localtime(self.starts_at)

    @property
    def local_end(self):
        return timezone.localtime(self.end) if self.end else None

    @property
    def multi_day(self):
        return bool(self.end) and timezone.localtime(self.end).date() != self.local_start.date()

    @property
    def is_upcoming(self):
        return self.ends_at >= timezone.now()

    @property
    def is_free(self):
        return self.price_kind == self.Price.FREE

    @property
    def price_label(self):
        if self.price_kind == self.Price.FREE:
            return _("Gratuit")
        if self.price_kind == self.Price.PWYW:
            return _("Prix libre")
        if self.price_kind == self.Price.UNKNOWN:
            return _("Prix : voir le site")
        if self.price_min is None:
            return _("Payant")
        if self.price_max and self.price_max > self.price_min:
            return f"{euros(self.price_min)}–{euros(self.price_max)} €"
        return f"{euros(self.price_min)} €"

    @property
    def age_label(self):
        if self.age_kind == self.Age.FROM and self.age_min:
            return _("Dès %(n)s ans") % {"n": self.age_min}
        if self.age_kind == self.Age.RANGE and self.age_min and self.age_max:
            return _("%(a)s–%(b)s ans") % {"a": self.age_min, "b": self.age_max}
        return self.get_age_kind_display()

    @property
    def english_friendly(self):
        return self.language in (self.Language.INTERNATIONAL, self.Language.NONE) or "en" in self.spoken_codes

    @property
    def spoken_codes(self):
        return [c for c in self.spoken.split(",") if c]

    @property
    def spoken_labels(self):
        names = dict(self.SPOKEN)
        return [str(names[c]) for c in self.spoken_codes if c in names]

    @property
    def is_cancelled(self):
        return self.state == self.State.CANCELLED

    @property
    def display_organizer(self):
        if self.organizer_name:
            return self.organizer_name
        if self.organizer_id and hasattr(self.organizer, "profile"):
            return self.organizer.profile.display_name
        return self.source.name if self.source_id else ""

    @property
    def going_count(self):
        return self.attendances.count()

    @property
    def is_full(self):
        return self.state == self.State.FULL or bool(self.capacity and self.going_count >= self.capacity)
