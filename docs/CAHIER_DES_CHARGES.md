# Nice-Event — cahier des charges et plan de développement

> Version 1.0 du 26/10/2026, validée (décisions récapitulées au § 14).

## 1. Objectif

**nice-event.fr** : un agenda participatif de Nice et de sa région. N'importe qui peut y publier un événement, quel
qu'il soit (concert, rando, atelier, échange linguistique, marché, match…), et le partager. Le site s'adresse à tout le
monde : habitant·es, étudiant·es, familles, touristes et non-francophones.

Trois sources d'événements :

1. **Événements publiés par les membres** (cœur du site) ;
2. **Événements externes** récupérés automatiquement sur d'autres agendas (10 h, 16 h et 22 h), affichés avec leur
   source et un lien vers la page d'origine ;
3. **Mise en avant par l'équipe** : un administrateur peut diffuser un événement sur Instagram, Facebook, X et Bluesky,
   tout de suite ou à une date programmée, avec un visuel généré automatiquement.

Ce que le site n'est pas (pour l'instant) : ni une billetterie, ni une association ; pas de demande de soutien, pas de
dossiers, pas de HelloAsso. Pas de paiement au lancement (la publication à 1 € est prévue plus tard, § 11).

## 2. Ce qu'on reprend de l'AJC06

Le site de l'AJC06 sert de base technique. On **copie puis adapte** les modules (pas de bibliothèque partagée : les
deux sites vont diverger et n'ont pas le même hébergement).

| Repris (adapté) | Abandonné |
|---|---|
| `core` : sécurité (blocage des IP, limites d'envoi), CSP, images (WebP, miniatures, limites), Markdown + nh3, médias, sauvegardes, `scripts/i18n.py` | Missions, équipe, ressources, bureaux, effets saisonniers propres à l'asso (le mécanisme peut resservir : Carnaval, Fête de la musique…) |
| `community` : comptes (connexion par courriel), profils, amis, « J'y vais », invitations, notifications, signalements, suppression de compte | Champs doctoraux (discipline, école doctorale, labo, thèse) |
| `events` : modèle, iCal, duplication, éditeur Markdown | Types réservés au bureau, soutien, statut « en attente » lié au soutien |
| `gestion` : espace d'administration hors admin Django | `projets` (PDF UniCA), synchro HelloAsso, blog (pas au lancement) |
| Organisation FR à la racine / EN sous `/en/` avec adresses traduites | — |

## 3. Publics et rôles

| Rôle | Peut |
|---|---|
| **Visiteur** | parcourir, filtrer, chercher, ajouter au calendrier, partager un lien, voir les événements externes |
| **Membre** (compte gratuit) | publier et gérer ses événements, profil, amis, « J'y vais », invitations, notifications, signaler |
| **Membre de confiance** | publier sans modération préalable (statut acquis automatiquement, § 5.3) |
| **Modérateur·rice** | traiter les signalements et la file de modération, masquer un événement ou un compte |
| **Administrateur·rice** | tout, plus : diffusion sur les réseaux, sources externes, réglages (mail, API, horaires de scan) |

## 4. Fiche événement

### 4.1 Champs

| Bloc | Champs |
|---|---|
| **Essentiel** | titre ; catégories (1 à 3, § 4.2) ; photo ou affiche (facultative) ; résumé court (200 caractères, sert aux visuels et aux posts) ; description (Markdown) |
| **Quand** | début, fin ; journée entière ; sur plusieurs jours ; **répétition simple** (« chaque semaine jusqu'au… », crée des occurrences qu'on peut modifier une à une) |
| **Où** | lieu réutilisable (nom, adresse, commune, coordonnées) avec saisie assistée (§ 4.3) ; précisions d'accès ; accessible PMR (oui / non / je ne sais pas) |
| **Prix** | gratuit / payant (prix ou fourchette en €, ex. 8–15 €) / prix libre ; réservation obligatoire (oui/non) ; lien de billetterie ou d'inscription ; places limitées (nombre facultatif, sert au « complet » du « J'y vais ») |
| **Pour qui** | tranche d'âge : tout public / famille et enfants / à partir de N ans / de N à M ans / 18+ ; **langue** : « En français » / « International – accessible sans parler français » / « Sans barrière de langue » (musique, sport…) ; langues parlées sur place (multi-choix : français, anglais, italien, espagnol, allemand, autre) |
| **Contact** | organisateur·rice affiché·e (soi-même, ou un nom d'organisme : asso, bar, salle…) ; site, Instagram ou Facebook de l'organisme (facultatif) |
| **Traduction** | section repliable « Version anglaise » (titre, résumé, description) comme sur l'AJC06, repli sur le français avec mention |
| **État** | publié, en attente de modération, masqué ; et pour le public : prévu, **complet**, **reporté**, **annulé** (l'événement reste visible, barré, au lieu de disparaître) |

### 4.2 Catégories

Une couleur et un pictogramme par catégorie (dessinés à la main, SVG), et un visuel générique pour les réseaux.

Concert & musique · Soirée & fête · Spectacle & théâtre · Humour · Cinéma · Expo & musée · Festival · Fête populaire &
traditions (Carnaval, festins, Fête de la musique…) · Marché & brocante · Gastronomie & dégustation · Sport (pratiquer) ·
Sport (assister) · Plein air & rando · Mer & plage · Atelier & cours · Conférence & rencontre · Échanges linguistiques
& international · Rencontres en groupe (amicales ou amoureuses, à la Timeleft : dîners, apéros entre inconnu·es) · Networking & pro · Bien-être · Solidarité & bénévolat · Jeux & gaming · Famille & enfants · Autre.

### 4.3 Lieu et périmètre

- **Périmètre** : Alpes-Maritimes + Monaco. La commune est obligatoire et choisie dans une liste ; les filtres
  proposent « Nice », « Métropole Nice Côte d'Azur », « Côte (Cannes → Menton) », « Arrière-pays », « Monaco ».
- **Géocodage** de l'adresse via l'API Adresse de l'État (BAN, gratuite, sans clé, données publiques) ; le lieu est
  enregistré et proposé aux suivants (« Théâtre de Verdure », « Place Masséna »…).
- **Carte** : lien « Itinéraire » vers Google Maps / OpenStreetMap sur chaque fiche, et la page `/carte/` (§ 5.1).

## 5. Fonctionnalités publiques

### 5.1 Découverte

| URL | Contenu |
|---|---|
| `/` | accroche, « Aujourd'hui », « Ce week-end », sélection de l'équipe, catégories en tuiles colorées, derniers ajouts, bouton « Publier un événement » très visible |
| `/evenements/` | liste par jour avec **filtres combinables** : quand (aujourd'hui, demain, ce week-end, cette semaine, dates), catégorie, commune / zone, gratuit, âge, « accessible sans parler français », source (membres / externes) ; recherche plein texte (accents ignorés) |
| `/evenements/<slug>/` | toutes les infos, bouton billetterie, « J'y vais », amis qui y vont, ajouter au calendrier (.ics, Google), partager (copier le lien, WhatsApp, natif mobile), signaler, événements proches |
| `/lieux/<slug>/`, `/organisateurs/<slug>/` | événements à venir d'un lieu ou d'un organisme |
| `/carte/` | **carte interactive** de tous les événements à venir (membres et externes) : un marqueur par événement, l'**emoji de sa catégorie** dans une pastille de sa couleur ; regroupement des marqueurs proches aux petits zooms ; clic → aperçu (photo, titre, date, lieu, prix, langue) avec bouton « Voir l'événement » ; mêmes filtres que la liste (quand, catégorie, gratuit…), « autour de moi » si la personne l'accepte |
| `/membres/<nom>/` | profil |
| `/evenements/agenda.ics` (+ `?categorie=…&commune=…`) | flux à s'abonner, filtrable |

**Carte** : Leaflet servi par le site et **fond de carte auto-hébergé** (extrait OpenStreetMap des Alpes-Maritimes et de
Monaco au format PMTiles, ~100–200 Mo sur VPS1, rendu dans le navigateur) : aucune requête vers un tiers, pas de
quota, pas de fuite d'adresses IP. Attribution « © OpenStreetMap » affichée. Les emoji ne servent qu'aux marqueurs de la
carte (et éventuellement aux posts), pas à décorer l'interface.

**Partage** : sur chaque fiche, un bloc « Fais tourner ! » invite à partager l'événement : bouton de partage natif sur
mobile (ouvre toutes les applis installées, Instagram compris), et liens directs WhatsApp, Messenger, Facebook, X,
Bluesky, LinkedIn, Telegram, courriel, copier le lien. Instagram n'ayant pas de lien de partage web, un bouton
« Visuel pour ta story » télécharge le visuel 9:16 de l'événement (§ 7). Juste après avoir publié, l'organisateur·rice
arrive sur une page « C'est en ligne ! » qui pousse au partage. Liens de partage simples (pas de boutons ni de scripts
des réseaux : rien n'est chargé chez eux tant qu'on ne clique pas).

**Événements externes** : carte au même format avec un badge « via *Source* », résumé court, bouton « Voir sur le
site de l'organisateur » (lien sortant). Pas de « J'y vais » ni de diffusion sur les réseaux pour eux.

**Référencement** : données structurées schema.org `Event` sur chaque page (éligibles aux résultats « événements » de
Google), sitemap, image de partage (Open Graph) générée par le même moteur que les visuels réseaux (§ 7).

### 5.2 Espace membres (repris de l'AJC06)

Inscription par courriel, profil (photo, présentation, centres d'intérêt = catégories, langues parlées, communes,
couleur du profil, coordonnées visibles des amis seulement), amis, invitations, notifications sur le site (+ courriel
facultatif : « un ami va à… », « rappel la veille », « événement annulé »), suppression du compte. Pas de champs
doctoraux. « Mes événements » : brouillons, publiés, passés, statistiques simples (vues, « J'y vais »).

### 5.3 Modération

Site ouvert à tous ⇒ risque de spam et d'arnaques (faux concerts, revente de billets). Proposition :

- **compte confirmé par courriel** obligatoire pour publier (donc SMTP dès le lancement) ;
- **le premier événement** d'un compte passe en file de modération ; une fois validé, le compte devient « de confiance »
  et publie directement (l'équipe peut retirer ce statut) ;
- signalement sur chaque événement et profil, masquage immédiat par l'équipe ; masquage automatique à 3 signalements
  en attendant la décision ;
- limites : 5 événements par jour et par compte, piège à robots et limites par IP (repris de l'AJC06) ;
- charte de publication affichée sous le formulaire (interdits : contenus illégaux, haineux, commerciaux déguisés,
  revente de billets) ; obligations de plateforme d'hébergement (DSA) : point de contact et procédure de signalement.

## 6. Diffusion sur les réseaux (administrateurs)

Depuis la fiche d'un événement dans `/gestion/`, panneau **« Diffuser »** :

1. choix des réseaux (Instagram, Facebook, X, Bluesky) ;
2. **aperçu des visuels** par format, avec possibilité de recadrer la photo (point focal) ou de forcer le visuel générique ;
3. **texte par réseau** pré-rempli et modifiable (titre, date, lieu, prix, langue, lien), en FR, EN ou les deux, avec le
   compteur de la limite de chaque réseau (X 280, Bluesky 300, Instagram 2 200 sans lien cliquable → « lien en bio ») ;
4. **« Publier maintenant »** ou **« Programmer le … à … »** ;
5. **historique** : état par réseau (programmé, publié + lien vers le post, échec + message d'erreur, « Réessayer »),
   annulation tant que ce n'est pas parti.

Une **tâche de fond** (§ 12) vérifie chaque minute les publications programmées.

Option v2 : **récapitulatif automatique** (« Ce week-end à Nice », carrousel de 5 événements) programmé chaque jeudi.

### Contraintes par réseau (à connaître avant de valider)

| Réseau | Ce qu'il faut | Remarques |
|---|---|---|
| **Bluesky** | identifiant + **mot de passe d'application** | Le plus simple. Images ≤ ~1 Mo (compression automatique), texte alternatif, carte de lien. |
| **Facebook** | une **Page** Facebook Nice-Event, une app Meta (developers.facebook.com), jeton de Page longue durée | Publication sur la Page uniquement (pas sur un profil perso). |
| **Instagram** | compte **professionnel** (Créateur ou Entreprise) **relié à la Page Facebook**, même app Meta, permission de publication de contenu | L'image doit être accessible par URL publique (c'est le cas : servie par nice-event.fr). Pas de lien cliquable dans la légende. Limite de 100 publications par 24 h via l'API, largement suffisant. Pour ses propres comptes, pas besoin de la revue d'app Meta. |
| **X** | compte développeur X, app avec droits d'écriture, clés OAuth | **L'accès API en écriture est payant ou très limité selon l'offre en vigueur** : à vérifier au moment de l'inscription (quota mensuel gratuit réduit, sinon paiement à l'usage). Le connecteur sera prêt ; tu décides de l'activer. |

Les jetons Meta expirent ou sont révoqués (changement de mot de passe…) : le site vérifie leur validité chaque jour et
affiche une alerte dans `/gestion/` avant qu'une publication programmée échoue.

## 7. Visuels générés

Générés côté serveur (Pillow), sans service externe, mis en cache et régénérés quand l'événement change.

| Format | Taille | Usage |
|---|---|---|
| Portrait 4:5 | 1080 × 1350 | Instagram, Facebook |
| Paysage | 1200 × 675 | X, Bluesky |
| Open Graph | 1200 × 630 | aperçu des liens partagés (WhatsApp, Messenger, Slack…) |
| Story 9:16 | 1080 × 1920 | Story Instagram / Facebook, bouton « Visuel pour ta story » des fiches |

Composition : la **photo de l'événement** recadrée (point focal), un bandeau aux couleurs de la catégorie avec titre,
date et heure, commune, prix (« Gratuit » mis en valeur), pastille de langue (« EN friendly ») ; en pied, le **logo et
« nice-event.fr »**. Sans photo : le **visuel générique de la catégorie** avec le résumé de l'événement intégré en
grand.

**Visuels génériques** : je propose des compositions graphiques dessinées (formes, motifs et pictogrammes aux
couleurs de chaque catégorie), plutôt que des photos de banques d'images (droits, aspect « stock »). Chaque visuel
générique reste **remplaçable depuis l'interface** par une photo de ton choix.

## 8. Événements externes (agrégation)

### 8.1 Fonctionnement

- **Connecteurs par type de source**, configurés depuis `/gestion/sources/` (URL, type, actif, catégorie par défaut,
  commune par défaut) : flux **iCal**, flux **RSS**, pages contenant des données **schema.org Event (JSON-LD)**,
  **API OpenAgenda**, flux **DATAtourisme** ; un connecteur HTML spécifique seulement quand rien d'autre n'existe.
- **Trois passages par jour à 10 h, 16 h et 22 h** (heure de Paris), horaires modifiables dans l'interface ; bouton
  « Scanner maintenant » par source.
- **Dédoublonnage** : par identifiant de la source, puis par rapprochement titre + date + commune entre sources ; un
  événement publié par un membre l'emporte sur sa copie externe.
- Disparu de la source ⇒ marqué « peut-être annulé » puis masqué ; passé ⇒ archivé puis supprimé après 6 mois.
- **Tableau de bord** des scans : nombre récupéré / nouveau / mis à jour / erreurs, dernier succès, alerte si une source
  ne renvoie plus rien (site refait).
- **Bonne conduite** : respect de `robots.txt` et des conditions d'utilisation, agent identifié (`NiceEventBot` +
  adresse de contact), une requête à la fois avec pause, pas de JavaScript exécuté (pas de navigateur headless : trop
  lourd pour VPS1).
- **Droits** : on ne republie que titre, date, lieu, prix et un **extrait court** (≤ 300 caractères), avec
  lien vers l'original. Image reprise seulement si la licence le permet (OpenAgenda, DATAtourisme), sinon visuel générique
  de la catégorie. Pas de diffusion des événements externes sur nos réseaux.

### 8.2 Sources candidates (faisabilité à vérifier en phase 5)

| Source | Accès envisagé |
|---|---|
| OpenAgenda (agendas de villes, assos et lieux azuréens) | API officielle avec clé gratuite |
| DATAtourisme (base nationale des offices de tourisme, dont la Côte d'Azur) | flux open data, licence ouverte |
| Agenda de la Ville de Nice, Métropole, office du tourisme | JSON-LD / iCal / RSS si disponibles |
| Salles et lieux (Opéra, TNN, Nikaïa, Forum Nice Nord, MAMAC, Acropolis…) | JSON-LD / iCal / page dédiée |
| Agenda de l'AJC06 (`beta.ajc06.com/evenements/agenda.ics`) | iCal, accès garanti |
| Billetteries (Ticketmaster, Shotgun…) | API publique quand elle existe |

Exclus : événements Facebook et Meetup (pas d'accès autorisé), sites qui l'interdisent.

## 9. Réglages depuis l'interface (sans toucher au `.env`)

Page **`/gestion/reglages/`** (administrateurs seulement) :

- **Courriel** : hôte, port, sécurité (SSL/STARTTLS), identifiant, mot de passe, expéditeur, adresse de contact ;
  bouton « Envoyer un courriel de test ». Le site utilise un backend de courriel qui lit ces réglages à chaque envoi :
  pas de redémarrage.
- **Réseaux** : un bloc par réseau (Instagram, Facebook, X, Bluesky) avec activation, identifiants, bouton
  « Tester la connexion », date d'expiration des jetons et texte de signature par défaut (hashtags…).
- **Sources externes** et **horaires de scan**.
- **Comptes** : mode de validation, statut de confiance automatique (nombre d'événements avant confiance).
- **Site** : bandeau d'annonce, mise en avant de la page d'accueil.

Sécurité : les secrets (mots de passe, jetons) sont **chiffrés en base** (Fernet) et ne sont jamais réaffichés (champ
« ••••••• – laisser vide pour conserver »), chaque modification est journalisée (qui, quand, quel réglage). Seuls restent
dans le `.env` : `DJANGO_SECRET_KEY`, la clé de chiffrement des réglages, l'accès à la base et les noms de domaine.

**Même module pour l'AJC06** : SMTP et clés HelloAsso dans `/gestion/reglages/` du site de l'AJC06, avec la même
logique. Ça marche aussi sous Passenger (o2switch) puisque les réglages sont relus en base. Je propose de le faire
juste après la phase 1, dès que le module existe (§ 12).

## 10. Identité visuelle

### 10.1 Principes

Parenté avec l'AJC06 (effet affiche, titres condensés, papier clair, bordures fines, rayon 8 px, thème clair/sombre,
pas de dégradés ni de verre dépoli, pas d'emoji décoratifs), mais une identité propre : **impactante, joyeuse,
accueillante**, plus colorée et plus « Riviera ».

### 10.2 Proposition

- **Palette** inspirée de Nice : *bleu chaise* (le bleu des chaises de la Promenade, accent principal), *ocre et rose
  Vieux-Nice* (façades), *jaune soleil*, *vert pin parasol* ; fond papier chaud ; encre bleu nuit. Chaque catégorie
  reçoit une des couleurs de la palette (tuiles, pastilles, visuels).
- **Typographies** auto-hébergées : une grotesque expressive et ronde pour les titres (ex. *Bricolage Grotesque*, libre
  OFL) pour se démarquer de l'Archivo de l'AJC06, et une police de texte très lisible (Archivo ou *Atkinson
  Hyperlegible*).
- **Détails joyeux mais sobres** : tuiles de catégories colorées en aplats, étiquettes « Gratuit » / « EN friendly » /
  « Ce soir » bien visibles, motif discret de vagues ou de rayures de parasol en bordure de section.

### 10.3 Logo — trois pistes (dessinées en SVG en phase 0, au choix)

1. **La chaise bleue** : silhouette simplifiée de la chaise de la Promenade des Anglais, emblème immédiatement niçois et
   accueillant (« installe-toi »).
2. **Le repère soleil** : une épingle de carte dont la tête est un soleil, sur la courbe de la Baie des Anges.
3. **Le monogramme N·E** : lettres pleines façon affiche, le point remplacé par un soleil ou une vague.

Déclinaisons : logo complet « Nice-Event.fr », symbole seul (favicon, avatar des réseaux), version claire et sombre,
filigrane des visuels.

## 11. Plus tard : publication à 1 €

Prévu dans le modèle dès le départ (état de paiement, réglage `PUBLICATION_FEE` désactivé) mais rien d'actif au lancement.
Au moment de l'activer : paiement par Stripe Checkout (carte, Apple/Google Pay), événement publié après paiement,
gratuité possible (associations, premier événement…), reçus. **Préalables non techniques** : statut juridique pour
encaisser (micro-entreprise ou association), conditions générales de vente, mentions légales à jour, TVA selon le
statut. À anticiper le moment venu.

## 12. Architecture technique

| Élément | Choix |
|---|---|
| Langage, framework | Python 3.13, **Django 6.1** (puis 6.2 LTS en avril 2027) ; pas la contrainte de Python 3.11 d'o2switch |
| Base | **SQLite** en mode WAL (comme l'AJC06 : transactions `IMMEDIATE`, partagée entre `web` et `worker` par le volume `/data`) ; recherche sur un champ normalisé sans accents |
| Tâches de fond | un conteneur **`worker`** avec un petit planificateur maison (commande Django) : publications programmées chaque minute, scans 10/16/22 h, vérification des jetons, rappels, sauvegarde. **Pas de Celery ni de Redis** (inutile à ce volume, économise la RAM de VPS1) |
| Front | gabarits Django, CSS et JS écrits à la main, aucune ressource tierce (polices, scripts servis par le site) |
| Images | Pillow (WebP, miniatures, visuels réseaux) |
| Réseaux | `httpx` + appels directs aux API (Graph API Meta, API X v2, `atproto` pour Bluesky) |
| Agrégation | `httpx`, `icalendar`, `extruct` (JSON-LD), `selectolax` |
| Hébergement | **VPS1**, Docker Compose (`web` gunicorn + WhiteNoise, `worker`), réseau `proxy`, fichier `~/reverse-proxy/sites/nice-event.caddy` (nice-event.fr, redirection de www) |
| Sauvegardes | copie à chaud de la base (`backup_site` de l'AJC06) quotidienne + archive des médias hebdomadaire, 30 jours, dans `~/Nice-Event/backups` (comme UNICA) |
| Courriel | **contact@nice-event.fr** sur le Zimbra d'OVH : envoi par `smtp.mail.ovh.net:465` (SSL), SPF, DKIM et DMARC dans la zone OVH (étapes dans `todo.md`) |
| Empreinte estimée | ~300 Mo de RAM au total ; VPS1 a ~2,3 Go disponibles |
| Tests | tests Django sur les modèles, formulaires, droits, générateur de visuels, connecteurs (avec réponses d'API enregistrées) |

Applications Django : `core`, `events`, `venues`, `community`, `gestion`, `social` (visuels + diffusion),
`aggregator` (sources externes), `siteconfig` (réglages en base, chiffrement).

## 13. Plan de développement

Chaque phase se termine par des tests, une vérification réelle (captures, essai en ligne) et un point avec toi.

| Phase | Contenu | Livrable |
|---|---|---|
| **0. Identité** | 3 pistes de logo en SVG, palette, typos, maquette statique de l'accueil et d'une fiche événement | tu choisis la piste |
| **1. Socle** | projet Django repris de l'AJC06 (sécurité, CSP, i18n, images, Markdown), Docker, `siteconfig` (SMTP depuis l'interface), DA appliquée, déploiement sur VPS1 en préproduction (accès protégé) | site vide en ligne, mail de test envoyé |
| **1 bis. AJC06** | portage de `siteconfig` dans l'AJC06 (SMTP, HelloAsso), déploiement o2switch | plus de `.env` à éditer pour le SMTP de l'AJC06 |
| **2. Événements** | modèle complet, lieux + géocodage, formulaire de publication pas à pas, répétition, liste et filtres, recherche, fiche, partage, carte interactive, iCal, JSON-LD, Open Graph, modération | on peut publier, trouver et partager des événements |
| **3. Communauté** | comptes, profils, amis, « J'y vais », invitations, notifications, signalements (repris de l'AJC06) | espace membres complet |
| **4. Visuels et réseaux** | générateur de visuels, visuels génériques par catégorie, connecteurs Bluesky → Facebook → Instagram → X, programmation, historique | diffusion testée sur chaque réseau configuré |
| **5. Agrégation** | étude des sources (§ 8.2), connecteurs, dédoublonnage, scans planifiés, tableau de bord | agenda enrichi automatiquement |
| **6. Lancement** | mentions légales, CGU et charte, confidentialité, performances (Lighthouse), sauvegardes vérifiées (restauration testée), bascule sur nice-event.fr | site ouvert au public |
| **Plus tard** | récapitulatif hebdo automatique, traduction automatique facultative (API DeepL), publication à 1 € | — |

Actions de ton côté (je les mettrai dans `todo.md` avec les étapes exactes au bon moment) : DNS de nice-event.fr vers
VPS1, boîte mail / SMTP, Page Facebook + compte Instagram pro + app Meta, compte Bluesky + mot de passe d'application,
compte développeur X (si l'offre te convient), clé OpenAgenda.

## 14. Décisions (26/10/2026)

| Sujet | Décision |
|---|---|
| Périmètre | Alpes-Maritimes + Monaco |
| Modération | compte confirmé par courriel ; **1 premier événement** validé par l'équipe, puis publication directe |
| Catégories | liste du § 4.2, avec « Rencontres en groupe » (amicales ou amoureuses, à la Timeleft) |
| Base | SQLite |
| Visuels génériques | dessinés, remplaçables par des photos |
| Événements externes | extrait court + lien vers l'événement d'origine, ni « J'y vais » ni diffusion |
| X | connecteur prévu, activé ou non au moment de l'inscription selon l'offre |
| Identité | direction « Riviera » validée ; logo à choisir parmi les 3 pistes |
| AJC06 | réglages du `.env` éditables depuis Django : à faire dès que le module existe |
| Domaine | nice-event.fr chez OVH, enregistrement A vers VPS1 fait ; mail contact@nice-event.fr sur le Zimbra OVH |
| Éditeur du site | Vincent Foriel |
| Ajouts | carte interactive (`/carte/`, marqueurs emoji) et invitation au partage sur chaque fiche |
