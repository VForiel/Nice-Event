# Nice-Event

Agenda participatif de Nice et de sa région : https://nice-event.fr. Django 6.1, gabarits et CSS écrits à la main,
aucune ressource tierce chargée par les visiteurs (polices, scripts et fond de carte servis par le site). Cahier des
charges et plan : [docs/CAHIER_DES_CHARGES.md](docs/CAHIER_DES_CHARGES.md) ; maquette d'identité :
[design/maquette.html](design/maquette.html).

Une partie du code vient du site de l'AJC06 (sécurité, images, Markdown, traductions, espace membres, sauvegardes),
copiée puis adaptée.

## Lancer en local

```sh
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Linux/macOS : .venv/bin/pip
.venv/Scripts/python manage.py migrate              # charge aussi les communes (06 + Monaco) et les catégories
.venv/Scripts/python manage.py createsuperuser
.venv/Scripts/python manage.py demo_events          # facultatif : 16 événements fictifs (DEBUG seulement)
.venv/Scripts/python scripts/extract_tiles.py       # facultatif : fond de carte (tiles/nice-region.pmtiles, ~80 Mo)
.venv/Scripts/python manage.py runserver
```

Site : http://localhost:8000 (anglais sous `/en/`), gestion : `/gestion/`, admin Django : `/admin/`.
`python manage.py worker` lance les tâches planifiées (publications, scans, sauvegarde).

## Applications

| App | Rôle |
|---|---|
| `core` | accueil, pages fixes, sécurité (blocage des IP), images, Markdown, planificateur de tâches (`core/jobs.py`, commande `worker`), sauvegardes |
| `venues` | communes des Alpes-Maritimes et de Monaco (zones Nice / Métropole / Côte / Arrière-pays / Monaco), lieux, géocodage BAN (`venues/geocode.py`) |
| `events` | catégories (`events/categories.py` : emoji, couleur, pictogramme), événements, publication, liste filtrable, carte, iCal, JSON-LD |
| `community` | comptes (connexion par courriel), confirmation d'adresse, profils, amis, « J'y vais », invitations, notifications (+ courriel), signalements |
| `social` | visuels générés (`social/visuals.py`), diffusion Instagram / Facebook / X / Bluesky (`social/networks.py`), publications programmées |
| `aggregator` | agendas externes : connecteurs iCal, JSON-LD (schema.org Event) et OpenAgenda, import, doublons, disparitions |
| `siteconfig` | réglages en base (courriel, réseaux, horaires des scans…), secrets chiffrés |
| `gestion` | espace de l'équipe : modération, événements, diffusions, sources, signalements, membres, réglages |

## Publier, modérer

- Tout membre au courriel confirmé peut publier (réglage « courriel confirmé pour publier »). Formulaire en cinq étapes :
  catégories (3 au plus), dates (répétition hebdomadaire possible, 26 semaines au plus), lieu (suggestions des lieux connus et
  des adresses de la BAN, interrogée par le serveur), prix, âge, langue, organisateur, version anglaise facultative.
- Le **premier événement** de chaque compte attend la validation de l'équipe (`/gestion/moderation/`) ; validé, le compte
  devient « de confiance » et publie directement. Refus : motif envoyé à l'auteur.
- Trois signalements de membres différents masquent un événement en attendant l'équipe.
- Modifier un événement (date, lieu, annulé, reporté) prévient les personnes inscrites.

## Carte

`/carte/` : Leaflet + leaflet.markercluster + protomaps-leaflet (`static/vendor/leaflet/`, licences à côté), fond de carte
PMTiles extrait des constructions mondiales de Protomaps (données © OpenStreetMap) par `scripts/extract_tiles.py`. En
production, le fichier `tiles/nice-region.pmtiles` (hors git) est servi par le conteneur `tiles` sous `/tiles/` (requêtes par
plages d'octets, sans compression) ; en développement, par une vue Django (`core/media.py`). À renouveler de temps en temps :
relancer le script, puis copier le fichier dans `~/Nice-Event/tiles/` sur VPS1.

## Diffusion sur les réseaux

`/gestion/evenements/<id>/diffuser/` : aperçu des visuels (portrait 1080×1350 pour Instagram et Facebook, paysage 1200×675
pour X et Bluesky, story 1080×1920, aperçu de lien 1200×630), texte proposé par réseau et modifiable (limites : X 280 avec liens
comptés 23, Bluesky 300, Instagram 2 200 sans lien cliquable), publication immédiate ou programmée. La tâche `publications`
envoie les publications dues chaque minute et retente trois fois les erreurs réseau ; historique dans `/gestion/diffusions/`.

Identifiants dans `/gestion/reglages/` (bouton « Tester » par réseau, vérification automatique chaque matin) :

- **Bluesky** : identifiant + mot de passe d'application ;
- **Facebook** : identifiant de la Page + jeton de Page longue durée (app Meta) ;
- **Instagram** : compte professionnel relié à la Page, même jeton ; Instagram télécharge l'image depuis nice-event.fr ;
- **X** : clés de l'app (droits lecture et écriture) et jetons du compte (OAuth 1.0a).

Les visuels sont aussi publics : `/evenements/<slug>/visuel/<og|portrait|paysage|story>.jpg` (image des aperçus de liens,
bouton « Visuel pour ta story »), mis en cache dans `media/visuels/` et régénérés quand l'événement change.

## Agendas externes

`/gestion/sources/` : une source par agenda (flux iCal, page JSON-LD, agenda OpenAgenda avec clé d'API). Scans à
10 h, 16 h et 22 h (réglable), ou à la demande (« Scanner maintenant », traité dans la minute). Le robot s'identifie
(`NiceEventBot`), respecte robots.txt et fait une pause d'une seconde entre deux pages d'un même site ; il ne reprend que le
titre, les dates, le lieu, le prix et un extrait de 200 caractères, avec le lien vers la page d'origine (images seulement si
la licence le permet). Ignorés : événements passés, hors Alpes-Maritimes et Monaco, étalés sur plus de 45 jours (sauf
expositions), doublons d'un événement déjà présent (même titre, même jour, même commune). Disparu d'un flux complet (iCal,
OpenAgenda) : marqué, puis masqué au bout de 24 h. Supprimés six mois après la fin.

## Réglages depuis l'interface

Le `.env` ne contient que l'infrastructure (clé secrète, clé de chiffrement, domaines). Le reste se règle dans
`/gestion/reglages/` (superutilisateurs) et s'applique immédiatement : courriel (avec courriel de test), confirmation
d'adresse pour publier, horaires des scans, réseaux sociaux. Secrets chiffrés (Fernet, `CONFIG_ENCRYPTION_KEY`), jamais
réaffichés ; chaque modification est journalisée.

## Tâches planifiées

| Tâche | Quand |
|---|---|
| `publications` | chaque minute : publications programmées sur les réseaux |
| `scan-sources` | 10 h, 16 h, 22 h (réglable) : tous les agendas externes actifs |
| `scan-a-la-demande` | chaque minute : sources dont un scan a été demandé |
| `verification-reseaux` | 8 h : identifiants des réseaux encore valides ? |
| `sauvegarde` | 3 h 30 : base chaque jour (30 jours gardés), médias le dimanche (8 archives) |

`python manage.py worker --run <tâche>` lance une tâche tout de suite. L'état de chaque tâche est sur le tableau de bord.

## Français et anglais

Français à la racine, anglais sous `/en/` avec adresses traduites. Après avoir modifié un texte : `python scripts/i18n.py`
(extrait, conserve, compile, sans GNU gettext) puis compléter les `msgstr` vides ; `--check` échoue s'il en reste. Pages
rédactionnelles : `templates/core/<page>.html` et `templates/core/en/<page>.html`. Les visuels et textes des réseaux sont en
français ; `/gestion/` aussi.

## Logo

`python scripts/build_logo.py` régénère `static/img/logo*.svg`, `favicon.svg` et `avatar.svg` (piste A, « la chaise bleue »).
Les visuels redessinent le logo avec Pillow (`social/visuals.py`) à partir des polices de `social/fonts/` (TTF statiques).

## Tests

```sh
.venv/Scripts/python manage.py test tests
```

## Production : VPS1

Docker Compose dans `~/Nice-Event` (clone du dépôt), derrière le reverse proxy Caddy partagé (`~/reverse-proxy`, réseau
`proxy`) : `web` (gunicorn), `worker` (tâches planifiées), `tiles` (fond de carte). Base SQLite et médias dans le volume
`data`, sauvegardes dans `~/Nice-Event/backups`.

Première installation :

```sh
git clone https://github.com/VForiel/Nice-Event.git ~/Nice-Event && cd ~/Nice-Event
cp .env.example .env   # remplir DJANGO_SECRET_KEY et CONFIG_ENCRYPTION_KEY ; chmod 600 .env
mkdir -p backups tiles   # puis copier tiles/nice-region.pmtiles depuis le poste de développement
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
cp deploy/nice-event.caddy ~/reverse-proxy/sites/ && cd ~/reverse-proxy && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

Mise à jour :

```sh
cd ~/Nice-Event && git pull && docker compose up -d --build
```

Restauration : arrêter les conteneurs, `gunzip` la copie voulue de `backups/` à la place de `/data/db.sqlite3` dans le
volume, extraire l'archive des médias dans `/data`, redémarrer.

## Plus tard

Publication à 1 € (Stripe Checkout, après création d'un statut juridique), récapitulatif hebdomadaire automatique sur les
réseaux, traduction automatique facultative.
