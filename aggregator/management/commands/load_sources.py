"""Sources d'événements retenues après la recherche du 26/10/2026 (voir docs/SOURCES.md), créées ou mises à jour.

    python manage.py load_sources            # ajoute les sources manquantes et met à jour leurs réglages
    python manage.py load_sources --scan     # et demande un premier scan (traité par la tâche de fond)

Ne touche ni à l'état actif/inactif choisi dans /gestion/sources/, ni aux sources ajoutées à la main.
"""

from django.core.management.base import BaseCommand

from aggregator.models import Source
from events.models import Category
from venues.models import Commune, Venue

NICE, MONACO = "06088", "99138"

# (slug, nom, type, adresse, site, commune par défaut (INSEE), catégorie par défaut, options)
SOURCES = [
    # Données ouvertes et grandes institutions
    ("ville-de-nice", "Ville de Nice", "wpnice", "https://www.nice.fr/wp-json/wp/v2/events", "https://www.nice.fr/agenda/",
     NICE, None, {"max_pages": 6, "images_allowed": True,
                  "notes": "Données ouvertes, Licence Ouverte : jeu « [VDN] Agenda de la Ville de Nice » sur data.gouv.fr."}),
    ("opera-de-nice", "Opéra de Nice", "wpnice", "https://www.opera-nice.org/wp-json/wp/v2/events", "https://www.opera-nice.org/",
     NICE, None, {}),
    ("office-tourisme-nice", "Office de tourisme Nice Côte d’Azur", "jsonld", "https://www.explorenicecotedazur.com/agenda/",
     "https://www.explorenicecotedazur.com", None, None, {"max_pages": 15}),
    ("valberg", "Valberg", "jsonld", "https://www.valberg.com/agenda/tout-lagenda/", "https://www.valberg.com",
     "06094", None, {"max_pages": 4}),
    ("unidivers-06", "Unidivers", "jsonld", "https://unidivers.fr/events/categorie/alpes-maritimes/", "https://unidivers.fr",
     None, None, {"max_pages": 8, "link_pattern": r"^https://unidivers\.fr/event/[^/]+/?$",
                  "notes": "Magazine culturel ; événements issus en partie d'OpenAgenda."}),
    ("ajc06", "AJC06", "ajc06", "https://beta.ajc06.com/evenements/nice-event.json", "https://beta.ajc06.com", NICE, None,
     {"notes": "Seulement les sorties de membres cochées « publier sur Nice-Event » sur le site de l'AJC06, avec tout leur détail."}),
    # Communes équipées de The Events Calendar (API publique)
    ("saint-paul-de-vence", "Ville de Saint-Paul-de-Vence", "tribe", "https://saintpauldevence.org/", None, "06128", None, {}),
    ("saint-vallier-de-thiey", "Ville de Saint-Vallier-de-Thiey", "tribe", "https://saintvallierdethiey.com/", None, "06130", None, {}),
    ("mouans-sartoux", "Ville de Mouans-Sartoux", "tribe", "https://www.mouans-sartoux.net/", None, "06084", None, {}),
    ("theoule-sur-mer", "Ville de Théoule-sur-Mer", "tribe", "https://theoule-sur-mer.fr/", None, "06138", None, {}),
    ("tourrettes-sur-loup", "Ville de Tourrettes-sur-Loup", "tribe", "https://www.tourrettessurloup.com/", None, "06148", None, {}),
    ("le-bar-sur-loup", "Ville du Bar-sur-Loup", "tribe", "https://www.lebarsurloup.fr/", None, "06010", None, {}),
    ("andon", "Ville d'Andon", "tribe", "https://ville-andon.com/", None, "06003", None, {}),
    ("drap", "Ville de Drap", "tribe", "https://www.ville-drap.fr/", None, "06054", None, {}),
    ("touet-de-l-escarene", "Ville de Touët-de-l'Escarène", "tribe", "https://www.touetdelescarene.fr/", None, "06142", None, {}),
    ("bonson", "Ville de Bonson", "tribe", "https://www.bonson.org/", None, "06021", None, {}),
    ("falicon", "Ville de Falicon", "tribe", "https://www.falicon.fr/", None, "06060", None, {}),
    ("saint-martin-du-var", "Ville de Saint-Martin-du-Var", "tribe", "https://www.saintmartinduvar.fr/", None, "06126", None, {}),
    ("le-cannet", "Ville du Cannet", "ical", "https://lecannet.fr/agenda-du-cannet/?ical=1", "https://lecannet.fr/agenda-du-cannet/",
     "06030", None, {}),
    # Matchs à domicile (calendriers publics fixtur.es)
    ("ogc-nice", "OGC Nice (calendrier)", "ical", "https://ics.fixtur.es/v2/ogc-nice.ics", "https://fixtur.es/", NICE, "match",
     {"title_pattern": r"^OGC Nice - ", "default_place": "Allianz Riviera"}),
    ("as-monaco", "AS Monaco (calendrier)", "ical", "https://ics.fixtur.es/v2/as-monaco.ics", "https://fixtur.es/", MONACO, "match",
     {"title_pattern": r"^AS Monaco - ", "default_place": "Stade Louis-II"}),
]

# Groupes Meetup locaux (flux iCal publics ; sans lieu : commune du groupe) : (groupe, commune, catégorie par défaut)
MEETUP = [
    ("international-apero-nice", NICE, "langues"), ("franglish-french-english-language-in-nice", NICE, "langues"),
    ("polyglotclub-multilingual-mingle-in-antibes", "06004", "langues"), ("nice-nomads", NICE, "rencontres"),
    ("nicenice", NICE, "rencontres"), ("les-cercles-de-connexion-nice", NICE, "rencontres"),
    ("working-women-in-nice", NICE, "networking"), ("event-nice", NICE, None), ("one-bite-at-a-time", NICE, None),
    ("faut-pas-emmerder-cendrillon", NICE, None), ("salon-des-femmes", NICE, None), ("nice-yogis", NICE, "bien-etre"),
    ("les-yogis-du-gang-du-soleil", NICE, "bien-etre"), ("groupe-meetup-nice-data", NICE, "networking"),
    ("l-apero-de-l-ia", NICE, "networking"), ("lapero-du-code", NICE, "networking"),
    ("evenements-la-fourmiliere-antibes", "06004", "networking"),
]

VENUES = [
    ("Allianz Riviera", NICE, "Boulevard des Jardiniers", 43.7050, 7.1926),
    ("Stade Louis-II", MONACO, "7 avenue des Castelans", 43.7277, 7.4156),
]


class Command(BaseCommand):
    help = "Crée ou met à jour les sources d'événements retenues."

    def add_arguments(self, parser):
        parser.add_argument("--scan", action="store_true", help="Demander un scan de chaque source")

    def handle(self, *args, **options):
        for name, insee, address, lat, lon in VENUES:
            Venue.objects.get_or_create(name=name, commune=Commune.objects.get(insee=insee), address=address,
                                        defaults={"lat": lat, "lon": lon, "precise": True})
        rows = list(SOURCES) + [
            (f"meetup-{group}"[:50], "Meetup", "ical", f"https://www.meetup.com/{group}/events/ical/",
             f"https://www.meetup.com/{group}/", insee, category,
             {"notes": "Groupe Meetup (flux iCal public) ; le flux ne donne pas le lieu : commune du groupe par défaut."})
            for group, insee, category in MEETUP
        ]
        created = 0
        for slug, name, kind, url, website, insee, category, extra in rows:
            values = {
                "name": name, "kind": kind, "url": url, "website": website or url,
                "default_commune": Commune.objects.get(insee=insee) if insee else None,
                "default_category": Category.objects.get(slug=category) if category else None,
                "max_pages": 3, "link_pattern": "", "title_pattern": "", "default_place": "", "images_allowed": True,
                "notes": "", **extra,
            }
            if options["scan"]:
                values["scan_requested"] = True
            _source, new = Source.objects.update_or_create(slug=slug, defaults=values)
            created += new
        self.stdout.write(f"{len(rows)} sources ({created} nouvelles)")
