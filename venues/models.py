"""Communes (Alpes-Maritimes + Monaco) et lieux des événements."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

# Communes du littoral, de Théoule à Menton (zone « Côte »).
COASTAL = {
    "06138",  # Théoule-sur-Mer
    "06079",  # Mandelieu-la-Napoule
    "06029",  # Cannes
    "06155",  # Vallauris (Golfe-Juan)
    "06004",  # Antibes
    "06161",  # Villeneuve-Loubet
    "06027",  # Cagnes-sur-Mer
    "06123",  # Saint-Laurent-du-Var
    "06088",  # Nice
    "06159",  # Villefranche-sur-Mer
    "06121",  # Saint-Jean-Cap-Ferrat
    "06011",  # Beaulieu-sur-Mer
    "06059",  # Èze
    "06032",  # Cap-d'Ail
    "06104",  # Roquebrune-Cap-Martin
    "06083",  # Menton
    "99138",  # Monaco
}
METROPOLE_EPCI = "200030195"
NICE = "06088"
MONACO = "99138"


class Zone(models.TextChoices):
    NICE = "nice", _("Nice")
    METROPOLE = "metropole", _("Métropole Nice Côte d'Azur")
    COTE = "cote", _("Côte (Cannes → Menton)")
    ARRIERE = "arriere-pays", _("Arrière-pays")
    MONACO = "monaco", _("Monaco")


def zone_filter(zone, prefix="venue__commune__"):
    """Q() des communes d'une zone (les zones se recouvrent : Nice est aussi dans la Métropole et sur la Côte)."""
    p = prefix
    return {
        Zone.NICE: Q(**{f"{p}insee": NICE}),
        Zone.METROPOLE: Q(**{f"{p}metropole": True}),
        Zone.COTE: Q(**{f"{p}coastal": True}),
        Zone.ARRIERE: Q(**{f"{p}coastal": False}) & ~Q(**{f"{p}insee": MONACO}),
        Zone.MONACO: Q(**{f"{p}insee": MONACO}),
    }.get(zone, Q())


class Commune(models.Model):
    insee = models.CharField("code INSEE", max_length=5, unique=True)
    name = models.CharField("nom", max_length=80)
    slug = models.SlugField(unique=True, max_length=80)
    postcodes = models.CharField("codes postaux", max_length=80, blank=True)
    lat = models.FloatField()
    lon = models.FloatField()
    population = models.PositiveIntegerField(default=0)
    metropole = models.BooleanField("Métropole Nice Côte d'Azur", default=False)
    coastal = models.BooleanField("littoral", default=False)

    class Meta:
        ordering = ["name"]
        verbose_name = "commune"

    def __str__(self):
        return self.name


class Venue(models.Model):
    """Lieu réutilisable : proposé aux organisateurs suivants (« Théâtre de Verdure », « Place Masséna »…)."""

    name = models.CharField(_("nom du lieu"), max_length=120)
    slug = models.SlugField(unique=True, max_length=140)
    address = models.CharField(_("adresse"), max_length=200, blank=True)
    commune = models.ForeignKey(Commune, on_delete=models.PROTECT, related_name="venues", verbose_name=_("commune"))
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    # Faux quand les coordonnées sont celles du centre de la commune (adresse introuvable).
    precise = models.BooleanField("position précise", default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "lieu"
        constraints = [models.UniqueConstraint(fields=["name", "address", "commune"], name="unique_venue")]

    def __str__(self):
        return f"{self.name}, {self.commune}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.name}-{self.commune.name}")[:120] or "lieu"
            slug, n = base, 2
            while Venue.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        if self.lat is None or self.lon is None:
            self.lat, self.lon, self.precise = self.commune.lat, self.commune.lon, False
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("events:venue", args=[self.slug])

    @property
    def full_address(self):
        parts = [self.name]
        if self.address:
            parts.append(self.address)
        if self.commune.name.lower() not in (self.address or "").lower():
            parts.append(self.commune.name)
        return ", ".join(parts)

    @property
    def directions_url(self):
        return f"https://www.openstreetmap.org/directions?to={self.lat:.5f}%2C{self.lon:.5f}"

    @property
    def google_maps_url(self):
        return f"https://www.google.com/maps/search/?api=1&query={self.lat:.5f}%2C{self.lon:.5f}"
