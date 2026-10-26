# Sources d'événements externes

Recherche du 26/10/2026. Les sources retenues sont créées par `python manage.py load_sources` (liste dans
`aggregator/management/commands/load_sources.py`) et se gèrent ensuite dans `/gestion/sources/`.

## Retenues

| Source | Type | Ce qu'elle apporte |
|---|---|---|
| Ville de Nice (nice.fr) | API WordPress (`wpnice`) | ~370 événements à venir : concerts, spectacles, expos, ateliers, projections, visites, avec lieu, gratuité et tarif. Données ouvertes sous Licence Ouverte (jeu « [VDN] Agenda de la Ville de Nice » sur data.gouv.fr, dont le flux RSS d'origine a changé d'adresse). Types administratifs écartés (permanences, dépistages, réunions d'information, formations). |
| Opéra de Nice | API WordPress (`wpnice`, même modèle que nice.fr) | ~60 représentations, concerts, ateliers. |
| Office de tourisme Nice Côte d'Azur | JSON-LD (liste + pages) | Événements de la Métropole. |
| Valberg (office de tourisme) | JSON-LD (liste + pages, plateforme IRIS) | ~45 animations de la station. |
| Unidivers (Alpes-Maritimes) | JSON-LD, liens suivis par motif | ~80 événements culturels dans tout le département (en partie issus d'OpenAgenda). |
| 12 communes sur The Events Calendar | API `tribe` | Saint-Paul-de-Vence, Saint-Vallier-de-Thiey, Mouans-Sartoux, Théoule-sur-Mer, Tourrettes-sur-Loup, Le Bar-sur-Loup, Andon, Drap, Touët-de-l'Escarène, Bonson, Falicon, Saint-Martin-du-Var (~135 événements ; une série répétée ne garde que sa prochaine date). |
| Le Cannet | iCal | Agenda municipal. |
| AJC06 | iCal | Événements de l'association. |
| OGC Nice, AS Monaco | iCal (fixtur.es) | Matchs à domicile uniquement (filtre sur le titre), à l'Allianz Riviera et au Stade Louis-II. |
| 17 groupes Meetup (Nice, Antibes) | iCal public des groupes | Échanges linguistiques, apéros internationaux, nomades, yoga, data/IA, networking (~90 événements). Le flux ne donne pas le lieu : commune du groupe ; les événements en ligne sont écartés. |

Méthode : sites des 163 mairies tirés de l'annuaire de l'administration (api-lannuaire.service-public.fr), offices de
tourisme, stations, salles et musées ; pour chacun, test automatique de l'API WordPress (types d'événements, The Events
Calendar), des flux iCal et des données schema.org Event. robots.txt vérifié pour chaque site retenu.

## Écartées

| Source | Raison |
|---|---|
| Vence, Sophia Antipolis (Modern Events Calendar) | Agendas plus mis à jour (aucun événement à venir). |
| Saorge, L'Escarène, Saint-Étienne-de-Tinée, Roure, Caille | Une entrée par jour d'exposition ou cycles de plusieurs mois ; Saorge est couvert par Unidivers. |
| MAMAC, musée Matisse, Villefranche-sur-Mer, Valbonne, La Gaude, Théâtre de Grasse, Cap-d'Ail, Le Broc, Tende, La Trinité, Saint-Martin-Vésubie… | Types WordPress sans dates dans l'API ni données structurées : demanderaient un connecteur HTML par site. Les musées de Nice sont en partie couverts par nice.fr. |
| Mandelieu (office de tourisme) | Pages sans données structurées. |
| TNN, Cannes, Menton, Monaco, Antibes, Grasse, Département 06, Université Côte d'Azur | Pas de flux ni de données structurées. |
| Fest.fr, Cityzeum, Songkick, AllEvents | Pas de données structurées exploitables. |
| Infoconcert (403), Shotgun (429), HelloAsso (interdit par robots.txt) | Accès refusé ou limité. |
| Eventbrite, Facebook | Conditions d'utilisation. |
| OpenAgenda | Exports publics `…/agendas/<numéro>/events.v2.ics` utilisables sans clé, mais les agendas trouvés pour le 06 sont vides ou anciens. À ajouter dès qu'un agenda actif est repéré. |
| Mobilizon | Pas de groupe local trouvé. |

## Pistes

Demander un flux iCal (ou une publication sur OpenAgenda) aux salles et mairies écartées ; écrire un connecteur HTML pour les
plus importantes (TNN, Théâtre de Grasse, MAMAC) si le volume le justifie.
