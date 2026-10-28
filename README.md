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
| `community` | comptes (connexion par courriel), confirmation d'adresse, profils, amis, « J'y vais », invitations, notifications (+ courriel), signalements, avis (commentaires + notes) et photos/vidéos des événements |
| `social` | visuels générés (`social/visuals.py`), diffusion Instagram / Facebook / X / Bluesky (`social/networks.py`), publications programmées |
| `aggregator` | agendas externes : connecteurs iCal, JSON-LD (schema.org Event) et OpenAgenda, import, doublons, disparitions |
| `siteconfig` | réglages en base (courriel, réseaux, horaires des scans…), secrets chiffrés |
| `gestion` | espace de l'équipe : modération, événements, diffusions, sources, signalements, membres, réglages |

## Publier, modérer

- Tout membre au courriel confirmé peut publier (réglage « courriel confirmé pour publier »). Formulaire en cinq étapes :
  catégories (3 au plus), dates (répétition chaque jour, semaine, mois, année ou tous les N jours/semaines/mois : un an et 60 dates au plus, cinq ans pour l'annuelle), lieu (suggestions des lieux connus et
  des adresses de la BAN, interrogée par le serveur), prix, âge, langue, organisateur, version anglaise facultative.
- Le **premier événement** de chaque compte attend la validation de l'équipe (`/gestion/moderation/`) ; validé, le compte
  devient « de confiance » et publie directement. Refus : motif envoyé à l'auteur.
- Trois signalements de membres différents masquent un événement en attendant l'équipe.
- Modifier un événement (date, lieu, annulé, reporté) prévient les personnes inscrites.

## Avis, photos et vidéos

- **Avis** sous chaque événement publié (y compris ceux des agendas externes) : commentaire et/ou note de 1 à 5 étoiles,
  la note seulement une fois l'événement commencé ; une seule note compte par membre (la plus récente). Moyenne affichée
  en haut de la fiche.
- **Photos et vidéos** (`/evenements/<slug>/souvenirs/ajouter/`) : plusieurs fichiers d'un coup (photos converties en
  WebP, 12 Mo max. ; vidéos MP4/MOV/WebM jusqu'à 50 Mo, servies par plages d'octets pour Safari) et liens externes, un
  par ligne. YouTube, Vimeo et Dailymotion se lisent sur place mais le lecteur ne se charge qu'au clic (`core/embeds.py`,
  domaines ajoutés à la CSP `frame-src`) ; Pinterest, Google Photos, Drive, Flickr, Instagram… s'affichent en carte. Un
  fichier trop lourd ou non convertible (HEIC…) est refusé avec le conseil de passer par un lien.
- Modération : signalement des commentaires et médias (masqués après trois signalements), suppression par l'auteur·rice
  et l'équipe, y compris depuis `/gestion/signalements/`.
- **Profil** : rubrique « Y est allé·e » (événements passés où le membre a cliqué « J'y vais »), visible selon le réglage
  « qui voit les événements auxquels j'ai participé » (tous ceux qui voient le profil, amis, moi seul·e).

## Filtres

Agenda et carte partagent une barre de menus déroulants (`events/_filters.html`, `static/js/filterbar.js`) : types (tout
cocher / décocher), dates (raccourcis ou plage choisie sur un calendrier), où (zones ou rayon autour d'une adresse BAN ou de
sa position), âge (public ou tranche), langue, prix, sources. OU à l'intérieur d'un menu, ET entre les menus. Chaque clic
met à jour l'adresse (`history.replaceState`) et les résultats sans recharger : fragment `?partiel=1` pour la liste,
`evenements.json` pour la carte. Anciens liens (`?gratuit=1`, `?source=membres`, `?masquer=…`) toujours compris.

Page **Filtres & alertes** (`/filtres/`, app `alerts`, éditeur `static/js/rulebuilder.js`) : tuto et exemples, conditions
choisies dans une liste filtrable (« âge », « type=adresse »), groupes ET / OU, SAUF, tranche d'âge, rayon autour d'une
adresse, expression régulière (motifs longs ou à répétitions imbriquées refusés), aperçu en direct
(`/api/filtres/apercu/`). Le moteur est `events/rules.py`. « Voir dans l'agenda / sur la carte » garde le filtre dans la
session (il s'ajoute aux menus). Les membres l'enregistrent (`SavedFilter`) et activent une alerte : tout de suite, résumé
quotidien (18 h) ou hebdomadaire (jeudi 18 h), tâche `alertes` du worker toutes les 10 minutes (`alerts/send.py`).
Canaux : notification sur le site (toujours), courriel, notification du navigateur (Web Push, clés VAPID créées
automatiquement, service worker `/sw.js`), Discord (webhook) et Telegram (bot à configurer dans `/gestion/reglages/`).

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
titre, les dates, le lieu, le prix, l'image et un extrait de 200 caractères, avec le lien vers la page d'origine. Image et
prix manquants : lus dans le texte (« 10 € », « entrée libre »), puis sur la page de l'événement (JSON-LD ou og:image ;
40 pages par scan, chacune une seule fois en 14 jours). Les images refusées par le robots.txt de leur serveur (Meetup) ne
sont pas reprises ; « reprendre les images » se décoche par source. Textes décodés en UTF-8 même quand l'en-tête annonce
autre chose, et l'UTF-8 lu comme du Latin-1 (« ApÃ©ro ») est réparé (`core.text.repair`). Ignorés : événements passés, hors Alpes-Maritimes et Monaco, étalés sur plus de 45 jours (sauf
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

Mise à jour : automatique (`.github/workflows/deploy.yml`). Un push lance les tests, puis le déploiement sur VPS1 :

- `main` → https://beta.nice-event.fr (`~/Nice-Event-beta`, `NICE_EVENT_INSTANCE=nice-event-beta` dans son `.env`) ;
- `stable` → https://nice-event.fr (`~/Nice-Event`). Mettre en production ce qui est validé sur la beta :
  `git push origin main:stable`.

Sur VPS1, `~/deploy/deploy.sh` fait `git merge --ff-only` de la branche puis `docker compose up -d --build` (la beta
sans `worker` : ni scans, ni alertes, ni diffusion). Journaux dans `~/deploy/logs/`. La base de la beta est une copie de
celle de prod, sans secrets (SMTP, réseaux, Telegram), sans abonnements push ni webhooks Discord, avec un bandeau
« version de test » ; `~/deploy/beta-reset.sh nice-event` la recopie.

À la main si besoin : `ssh VPS1 '~/deploy/deploy.sh nice-event prod'` (ou `beta`).

Restauration : arrêter les conteneurs, `gunzip` la copie voulue de `backups/` à la place de `/data/db.sqlite3` dans le
volume, extraire l'archive des médias dans `/data`, redémarrer.

## Plus tard

Publication à 1 € (Stripe Checkout, après création d'un statut juridique), récapitulatif hebdomadaire automatique sur les
réseaux, traduction automatique facultative.
