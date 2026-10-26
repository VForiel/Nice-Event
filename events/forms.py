import calendar
from datetime import datetime, time, timedelta

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from venues import geocode
from venues.models import Commune, Venue

from .models import Category, Event

MAX_CATEGORIES = 3
MAX_OCCURRENCES = 60
MAX_SPAN_DAYS = 366  # répétition : un an au plus (cinq ans pour une répétition annuelle)
MAX_SPAN_YEARS = 5
# Emprise des Alpes-Maritimes et de Monaco : une position hors de ce cadre est ignorée (on géocode à nouveau).
BBOX = (43.40, 6.60, 44.40, 7.75)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, **kwargs):
        super().__init__(format="%H:%M", **kwargs)


class CommuneChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name


def add_months(day, months):
    """Même jour, n mois plus tard ; le 31 devient le dernier jour des mois plus courts (et le 29 février, le 28)."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def repetition(first, until, unit, every=1):
    """Dates d'un événement répété, de first à until compris : unit = day, week, month ou year."""
    dates, n = [], 0
    while len(dates) <= MAX_OCCURRENCES:
        step = n * every
        if unit == "day":
            day = first + timedelta(days=step)
        elif unit == "week":
            day = first + timedelta(weeks=step)
        elif unit == "month":
            day = add_months(first, step)
        else:
            day = add_months(first, 12 * step)
        if day > until:
            break
        dates.append(day)
        n += 1
    return dates


def communes():
    # Nice et les grandes villes en tête, puis l'ordre alphabétique.
    return Commune.objects.order_by("-population")


class EventForm(forms.ModelForm):
    """Formulaire de publication : un seul écran découpé en étapes (Essentiel, Quand, Où, Prix, Pour qui)."""

    date = forms.DateField(label=_("Date"), widget=DateInput())
    start_time = forms.TimeField(label=_("Heure de début"), required=False, widget=TimeInput())
    end_date = forms.DateField(label=_("Date de fin"), required=False, widget=DateInput(),
                               help_text=_("Seulement si l'événement dure plusieurs jours."))
    end_time = forms.TimeField(label=_("Heure de fin"), required=False, widget=TimeInput())
    REPEAT = [("none", _("Non")), ("day", _("Tous les jours")), ("week", _("Toutes les semaines")),
              ("month", _("Tous les mois")), ("year", _("Tous les ans")), ("custom", _("Personnalisée"))]
    UNITS = [("day", _("jours")), ("week", _("semaines")), ("month", _("mois"))]
    repeat = forms.ChoiceField(label=_("Répétition"), choices=REPEAT, required=False, widget=forms.RadioSelect,
                               initial="none")
    repeat_every = forms.IntegerField(label=_("Tous les"), min_value=1, max_value=99, required=False, initial=2,
                                      widget=forms.NumberInput(attrs={"min": "1", "max": "99"}))
    repeat_unit = forms.ChoiceField(label=_("Unité"), choices=UNITS, required=False, initial="week")
    repeat_until = forms.DateField(label=_("Jusqu'au"), required=False, widget=DateInput(),
                                   help_text=_("Une date est créée pour chaque répétition, modifiable ensuite une à une."))

    venue_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    venue_name = forms.CharField(label=_("Nom du lieu"), max_length=120,
                                 help_text=_("Ex. Théâtre de Verdure, Plage du Castel, Bar Le Comptoir…"),
                                 widget=forms.TextInput(attrs={"autocomplete": "off", "data-venue-search": ""}))
    address = forms.CharField(label=_("Adresse"), max_length=200, required=False,
                              widget=forms.TextInput(attrs={"autocomplete": "off", "data-address-search": ""}),
                              help_text=_("Commence à taper : des adresses te sont proposées."))
    commune = CommuneChoiceField(label=_("Commune"), queryset=Commune.objects.none(), empty_label=_("Choisir…"))
    lat = forms.FloatField(required=False, widget=forms.HiddenInput)
    lon = forms.FloatField(required=False, widget=forms.HiddenInput)

    spoken_list = forms.MultipleChoiceField(label=_("Langues parlées sur place"), choices=Event.SPOKEN, required=False,
                                            widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = Event
        fields = [
            "title", "categories", "summary", "description", "photo",
            "all_day", "access_notes", "accessible",
            "price_kind", "price_min", "price_max", "booking_required", "ticket_url", "capacity",
            "age_kind", "age_min", "age_max", "language",
            "organizer_name", "organizer_url",
            "title_en", "summary_en", "description_en",
            "state",
        ]
        widgets = {
            "categories": forms.CheckboxSelectMultiple,
            "summary": forms.Textarea(attrs={"rows": 2, "maxlength": 200}),
            "summary_en": forms.Textarea(attrs={"rows": 2, "maxlength": 200}),
            "description": forms.Textarea(attrs={"rows": 8}),
            "description_en": forms.Textarea(attrs={"rows": 6}),
            "photo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "price_kind": forms.RadioSelect,
            "age_kind": forms.RadioSelect,
            "language": forms.RadioSelect,
            "accessible": forms.RadioSelect,
            "price_min": forms.NumberInput(attrs={"step": "0.5", "min": "0"}),
            "price_max": forms.NumberInput(attrs={"step": "0.5", "min": "0"}),
            "age_min": forms.NumberInput(attrs={"min": "0", "max": "120"}),
            "age_max": forms.NumberInput(attrs={"min": "0", "max": "120"}),
        }
        labels = {"categories": _("Catégories")}
        help_texts = {
            "categories": _("Une à trois."),
            "description": _("Programme, déroulé, infos pratiques… Mise en forme Markdown possible."),
            "photo": _("Facultative mais recommandée : sans photo, un visuel aux couleurs de la catégorie est utilisé."),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["categories"].queryset = Category.objects.all()
        self.fields["price_kind"].choices = [c for c in Event.Price.choices if c[0] != Event.Price.UNKNOWN]
        self.fields["commune"].queryset = communes()
        for name in ("ticket_url", "organizer_url"):
            self.fields[name].assume_scheme = "https"
        if self.instance.pk:
            start = self.instance.local_start
            end = self.instance.local_end
            self.initial.update({
                "date": start.date(),
                "start_time": None if self.instance.all_day else start.time(),
                "end_date": end.date() if end and end.date() != start.date() else None,
                "end_time": end.time() if end and not self.instance.all_day else None,
                "venue_id": self.instance.venue_id, "venue_name": self.instance.venue.name,
                "address": self.instance.venue.address, "commune": self.instance.venue.commune_id,
                "lat": self.instance.venue.lat, "lon": self.instance.venue.lon,
                "spoken_list": self.instance.spoken_codes,
            })
            for name in ("repeat", "repeat_every", "repeat_unit", "repeat_until"):
                del self.fields[name]
        else:
            del self.fields["state"]
            self.initial.setdefault("commune", Commune.objects.filter(insee="06088").values_list("pk", flat=True).first())

    # Validation ------------------------------------------------------------------------------------------------

    def clean_categories(self):
        cats = self.cleaned_data["categories"]
        if len(cats) > MAX_CATEGORIES:
            raise forms.ValidationError(_("Trois catégories au plus."))
        return cats

    def clean(self):
        data = super().clean()
        date, start_time, all_day = data.get("date"), data.get("start_time"), data.get("all_day")
        if date and not all_day and not start_time:
            self.add_error("start_time", _("Indique l'heure de début, ou coche « toute la journée »."))
        if date and (all_day or start_time):
            start = self.combine(date, None if all_day else start_time)
            end_date = data.get("end_date") or (date if data.get("end_time") else None)
            end = None
            if end_date:
                end = self.combine(end_date, time(23, 59) if all_day or not data.get("end_time") else data["end_time"])
                if end <= start:
                    if data.get("end_time") and not data.get("end_date") and data["end_time"] < (start_time or time()):
                        end += timedelta(days=1)  # « 22 h – 2 h » : la fin est le lendemain
                    else:
                        self.add_error("end_time" if data.get("end_time") else "end_date",
                                       _("La fin doit être après le début."))
            if not self.instance.pk and (end or start) < timezone.now():
                self.add_error("date", _("Cet événement est déjà passé."))
            data["_start"], data["_end"] = start, end
        if data.get("repeat") == "none":
            data["repeat"] = ""
        if data.get("repeat"):
            until = data.get("repeat_until")
            unit, every = self.repeat_rule()
            if data["repeat"] == "custom" and not data.get("repeat_every"):
                self.add_error("repeat_every", _("Indique tous les combien l'événement se répète."))
            elif not until or not date or until <= date:
                self.add_error("repeat_until", _("Indique jusqu'à quand l'événement se répète."))
            elif unit == "year" and until > add_months(date, 12 * MAX_SPAN_YEARS):
                self.add_error("repeat_until", _("Cinq ans au plus."))
            elif unit != "year" and (until - date).days > MAX_SPAN_DAYS:
                self.add_error("repeat_until", _("Un an au plus : republie ensuite si besoin."))
            elif len(repetition(date, until, unit, every)) > MAX_OCCURRENCES:
                self.add_error("repeat_until", _("Soixante dates au plus : espace les répétitions ou avance la date de fin."))
        kind = data.get("price_kind")
        low, high = data.get("price_min"), data.get("price_max")
        if kind == Event.Price.PAID and low is None:
            self.add_error("price_min", _("Indique le prix (ou le prix le plus bas)."))
        if low is not None and high is not None and high < low:
            self.add_error("price_max", _("Le prix maximum doit être supérieur au minimum."))
        age = data.get("age_kind")
        if age == Event.Age.FROM and not data.get("age_min"):
            self.add_error("age_min", _("Indique l'âge minimum."))
        if age == Event.Age.RANGE:
            if not data.get("age_min") or not data.get("age_max"):
                self.add_error("age_max", _("Indique les deux âges."))
            elif data["age_max"] < data["age_min"]:
                self.add_error("age_max", _("L'âge maximum doit être supérieur au minimum."))
        return data

    @staticmethod
    def combine(day, at):
        return timezone.make_aware(datetime.combine(day, at or time(0, 0)))

    # Enregistrement -------------------------------------------------------------------------------------------

    def resolve_venue(self):
        data = self.cleaned_data
        name, address, commune = data["venue_name"].strip(), data.get("address", "").strip(), data["commune"]
        if data.get("venue_id"):
            venue = Venue.objects.filter(pk=data["venue_id"], name__iexact=name, commune=commune).first()
            if venue and (not address or address.lower() == venue.address.lower()):
                return venue
        venue = Venue.objects.filter(name__iexact=name, address__iexact=address, commune=commune).first()
        if venue:
            return venue
        lat, lon = data.get("lat"), data.get("lon")
        if lat is not None and lon is not None and BBOX[0] <= lat <= BBOX[2] and BBOX[1] <= lon <= BBOX[3]:
            precise = True
        else:
            lat, lon, precise = geocode.locate(address, commune)
        return Venue.objects.create(name=name, address=address, commune=commune, lat=lat, lon=lon, precise=precise,
                                    created_by=self.user)

    def apply(self, event):
        """Recopie dates, lieu et langues sur l'événement (sans l'enregistrer)."""
        data = self.cleaned_data
        event.starts_at, event.end = data["_start"], data["_end"]
        event.venue = self.resolve_venue()
        event.spoken = ",".join(data.get("spoken_list") or [])
        if event.price_kind != Event.Price.PAID and event.price_kind != Event.Price.PWYW:
            event.price_min = event.price_max = None
        if event.age_kind not in (Event.Age.FROM, Event.Age.RANGE):
            event.age_min = event.age_max = None
        return event

    def repeat_rule(self):
        """(unité, intervalle) de la répétition choisie."""
        data = self.cleaned_data
        if data.get("repeat") == "custom":
            return data.get("repeat_unit") or "week", data.get("repeat_every") or 1
        return data.get("repeat") or "week", 1

    def occurrences(self):
        """Dates (jours) des occurrences à créer, la première comprise : une seule sans répétition."""
        data = self.cleaned_data
        if not data.get("repeat"):
            return [data["date"]]
        return repetition(data["date"], data["repeat_until"], *self.repeat_rule())
