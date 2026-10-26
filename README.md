# Nice-Event

Agenda participatif de Nice et de sa région : https://nice-event.fr. Django 6.1, gabarits et CSS écrits à la main,
aucune ressource tierce (polices et scripts servis par le site). Le cahier des charges et le plan de développement sont
dans [docs/CAHIER_DES_CHARGES.md](docs/CAHIER_DES_CHARGES.md), la maquette d'identité dans
[design/maquette.html](design/maquette.html).

Une partie du code vient du site de l'AJC06 (sécurité, images, Markdown, traductions, sauvegardes), copiée puis adaptée.

## Lancer en local

```sh
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Linux/macOS : .venv/bin/pip
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py createsuperuser
.venv/Scripts/python manage.py runserver
```

- Site : http://localhost:8000 (anglais sous `/en/`)
- Gestion (tableau de bord, réglages) : http://localhost:8000/gestion/
- Admin Django : http://localhost:8000/admin/

## Réglages depuis l'interface

Le `.env` ne contient que l'infrastructure (clé secrète, clé de chiffrement, domaines). Le reste se règle dans
**`/gestion/reglages/`** (réservé aux superutilisateurs) et s'applique immédiatement :

- **courriel** : serveur SMTP, port, sécurité, identifiant, mot de passe, expéditeur, adresse de contact, bouton
  « courriel de test ». Tant qu'aucun serveur n'est réglé, les courriels s'affichent dans les journaux ;
- réseaux sociaux (phase 4) et sources d'événements externes (phase 5) viendront s'y ajouter.

Les secrets sont chiffrés en base (Fernet, clé `CONFIG_ENCRYPTION_KEY`) et ne sont jamais réaffichés : un champ laissé
vide conserve la valeur enregistrée. Chaque modification est journalisée (qui, quand, quels réglages) en bas de la page.

## Tâches planifiées

Le conteneur `worker` lance `python manage.py worker`, une boucle qui exécute les tâches dues (`core/jobs.py`, et les
`jobs.py` des autres applications) et note chaque passage (visible sur le tableau de bord de `/gestion/`) :

| Tâche | Quand |
|---|---|
| `sauvegarde` | 3 h 30 : base chaque jour (30 jours gardés), médias le dimanche (8 archives) |

`python manage.py worker --run sauvegarde` lance une tâche tout de suite ; `--once` fait un seul passage.

Restauration : arrêter les conteneurs, `gunzip` la copie voulue de `backups/` à la place de `/data/db.sqlite3` dans le
volume, extraire l'archive des médias dans `/data`, redémarrer.

## Français et anglais

Français à la racine, anglais sous `/en/` avec adresses traduites. Textes de l'interface : `{% translate %}` dans les
gabarits, catalogue `locale/en/LC_MESSAGES/django.po`. Après avoir modifié un texte, lancer `python scripts/i18n.py`
(extrait, conserve les traductions, compile, sans GNU gettext) puis compléter les `msgstr` vides ; `--check` échoue
s'il en reste. Pages rédactionnelles : `templates/core/<page>.html` et `templates/core/en/<page>.html`.
`/gestion/` et l'admin restent en français.

## Logo

`python scripts/build_logo.py` régénère `static/img/logo*.svg`, `favicon.svg` et `avatar.svg` (piste A, « la chaise
bleue ») ; le texte est converti en tracés depuis Bricolage Grotesque.

## Tests

```sh
.venv/Scripts/python manage.py test tests
```

## Production : VPS1

Docker Compose dans `~/Nice-Event` (clone du dépôt), derrière le reverse proxy Caddy partagé (`~/reverse-proxy`, réseau
`proxy`). Base SQLite et médias dans le volume `data`, sauvegardes dans `~/Nice-Event/backups`.

Première installation :

```sh
git clone https://github.com/VForiel/Nice-Event.git ~/Nice-Event && cd ~/Nice-Event
cp .env.example .env   # remplir DJANGO_SECRET_KEY et CONFIG_ENCRYPTION_KEY ; chmod 600 .env
mkdir -p backups && docker compose up -d --build
docker compose exec web python manage.py createsuperuser
cp deploy/nice-event.caddy ~/reverse-proxy/sites/ && cd ~/reverse-proxy && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

Mise à jour :

```sh
cd ~/Nice-Event && git pull && docker compose up -d --build
```
