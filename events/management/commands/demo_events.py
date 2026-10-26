"""Événements de démonstration, pour le développement uniquement (refusé quand DEBUG est faux).

    python manage.py demo_events          # crée ~16 événements fictifs sur les deux semaines à venir
    python manage.py demo_events --clear  # supprime les événements de démonstration
"""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from events.models import Category, Event
from venues.models import Commune, Venue

DEMO = [
    # (titre, catégories, commune, lieu, adresse, lat, lon, jour, heure, prix, langue, résumé)
    ("Apéro jazz face à la mer", ["concert"], "Nice", "Plage du Castel", "Quai des États-Unis", 43.6935, 7.2830, 0, "19:30", "free", "international",
     "Un trio jazz, les pieds dans les galets et le soleil qui se couche sur la Baie des Anges."),
    ("Language café du jeudi", ["langues", "rencontres"], "Nice", "Le Comptoir du Port", "12 rue Bonaparte", 43.7006, 7.2843, 1, "19:00", "free", "international",
     "Anglais, italien, espagnol… on change de table toutes les 20 minutes. Débutant·es bienvenu·es."),
    ("Dîner à six inconnu·es", ["rencontres", "gastronomie"], "Nice", "Vieux-Nice", "Rue de la Préfecture", 43.6970, 7.2760, 2, "20:00", "25", "fr",
     "Six personnes, une table, des questions pour briser la glace. Pour les 25-35 ans."),
    ("Rando du Mont Boron au lever du soleil", ["plein-air"], "Nice", "Fort du Mont Alban", "Chemin du Fort du Mont Alban", 43.7036, 7.3040, 3, "06:30", "free", "none",
     "Deux heures de marche facile, café offert au sommet. Prévoir une frontale."),
    ("Brocante du cours Saleya", ["marche"], "Nice", "Cours Saleya", "Cours Saleya", 43.6955, 7.2755, 4, "08:00", "free", "fr",
     "Chaque lundi, antiquaires et brocanteurs sur le plus beau marché de Nice."),
    ("Soirée électro au port", ["soiree"], "Nice", "Le Bateau", "Quai Lunel", 43.6960, 7.2860, 5, "23:00", "12", "none",
     "Trois DJ, une terrasse sur le port et ça jusqu'au bout de la nuit."),
    ("Atelier céramique pour débutants", ["atelier"], "Vallauris", "Atelier Terre & Feu", "Avenue Georges Clemenceau", 43.5780, 7.0540, 6, "14:00", "45", "fr",
     "Initiation au tour en petit groupe, dans la ville de Picasso. Matériel fourni."),
    ("Ciné plein air : classiques de la Riviera", ["cinema"], "Antibes", "Pinède Gould", "Boulevard Baudoin", 43.5650, 7.1170, 2, "21:30", "free", "fr",
     "Projection sous les pins, transats fournis dans la limite des places."),
    ("Match OGC Nice - Lyon", ["match"], "Nice", "Allianz Riviera", "Boulevard des Jardiniers", 43.7050, 7.1926, 7, "21:00", "15", "none",
     "Ambiance garantie : rendez-vous au tram Allianz Riviera une heure avant."),
    ("Yoga au lever du jour", ["bien-etre", "mer"], "Villefranche-sur-Mer", "Plage des Marinières", "Promenade des Marinières", 43.7020, 7.3110, 1, "07:00", "pwyw", "international",
     "Une heure de vinyasa face à la rade. Apporte ton tapis et une serviette."),
    ("Festival des jeux de société", ["jeux", "famille"], "Cagnes-sur-Mer", "Salle des fêtes", "Place du Docteur Maris", 43.6640, 7.1490, 8, "10:00", "free", "fr",
     "Plus de 200 jeux à tester, des tournois et un coin pour les petits."),
    ("Conférence : la Méditerranée en 2050", ["conference"], "Nice", "Médiathèque Louis Nucéra", "2 place Yves Klein", 43.7020, 7.2810, 3, "18:30", "free", "fr",
     "Une océanographe de l'Observatoire de Villefranche répond à toutes vos questions."),
    ("Stand-up en anglais", ["humour"], "Monaco", "Théâtre des Variétés", "1 boulevard Albert Ier", 43.7350, 7.4230, 4, "20:30", "18", "international",
     "Five comedians, one mic, zero French required. Bar ouvert dès 19 h 30."),
    ("Nettoyage de plage solidaire", ["solidarite", "mer"], "Cannes", "Plage du Midi", "Boulevard Jean Hibert", 43.5470, 7.0050, 5, "09:30", "free", "fr",
     "Gants et sacs fournis, pique-nique partagé à la fin. Venez nombreux !"),
    ("Fête du citron : défilé de nuit", ["traditions", "festival"], "Menton", "Promenade du Soleil", "Promenade du Soleil", 43.7740, 7.5040, 9, "20:30", "12", "none",
     "Chars d'agrumes géants, fanfares et lumières le long de la mer."),
    ("Expo photo : les chaises bleues", ["expo"], "Nice", "Galerie des Ponchettes", "77 quai des États-Unis", 43.6950, 7.2770, 0, "10:00", "free", "fr",
     "Cinquante ans de clichés de la Promenade des Anglais."),
]


class Command(BaseCommand):
    help = "Crée des événements de démonstration (développement uniquement)."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Commande réservée au développement (DJANGO_DEBUG=True).")
        demo = Event.objects.filter(organizer_name="Démo Nice-Event")
        if options["clear"]:
            self.stdout.write(f"{demo.count()} événements supprimés")
            demo.delete()
            return
        user = get_user_model().objects.filter(is_superuser=True).first()
        today = timezone.localdate()
        for i, (title, cats, commune, place, address, lat, lon, day, hour, price, lang, summary) in enumerate(DEMO):
            city = Commune.objects.get(name=commune)
            venue, _ = Venue.objects.get_or_create(name=place, commune=city, address=address,
                                                   defaults={"lat": lat, "lon": lon, "precise": True})
            h, m = (int(x) for x in hour.split(":"))
            start = timezone.make_aware(datetime.combine(today + timedelta(days=day), time(h, m)))
            if start < timezone.now():
                start += timedelta(days=7)
            kind = price if price in ("free", "pwyw") else "paid"
            event = Event.objects.create(
                title=title, summary=summary, venue=venue, starts_at=start, end=start + timedelta(hours=3),
                price_kind=kind, price_min=None if kind != "paid" else int(price), language=lang,
                spoken="fr,en" if lang == "international" else "", organizer=user, organizer_name="Démo Nice-Event",
                featured=i in (0, 6, 12), status=Event.Status.PUBLISHED,
                description="Événement **fictif** de démonstration.\n\n- Point de rendez-vous à l'entrée\n- Apporte ta bonne humeur",
            )
            event.categories.set(Category.objects.filter(slug__in=cats))
        self.stdout.write(f"{len(DEMO)} événements créés")
