"""Catégories d'événements : chargées en base par la migration events.0002, réglables ensuite dans l'admin.

(slug, nom, nom anglais, emoji du marqueur de carte, couleur, pictogramme de core.templatetags.ne.ICONS)
Couleurs : chaise, corail, ocre, soleil, pin, lavande, nuit (classes CSS cat-*, tone-*).
"""

CATEGORIES = [
    ("concert", "Concert & musique", "Concerts & music", "🎵", "chaise", "music"),
    ("soiree", "Soirée & fête", "Nights out & parties", "🪩", "lavande", "party"),
    ("spectacle", "Spectacle & théâtre", "Shows & theatre", "🎭", "corail", "show"),
    ("humour", "Humour", "Comedy", "😂", "soleil", "smile"),
    ("cinema", "Cinéma", "Cinema", "🎬", "nuit", "film"),
    ("expo", "Expo & musée", "Exhibitions & museums", "🖼️", "ocre", "frame"),
    ("festival", "Festival", "Festivals", "🎪", "corail", "tent"),
    ("traditions", "Fête populaire & traditions", "Local festivals & traditions", "🎉", "soleil", "confetti"),
    ("marche", "Marché & brocante", "Markets & flea markets", "🧺", "ocre", "market"),
    ("gastronomie", "Gastronomie & dégustation", "Food & drink", "🍷", "corail", "food"),
    ("sport", "Sport (pratiquer)", "Sport (play)", "🏃", "pin", "run"),
    ("match", "Sport (assister)", "Sport (watch)", "🏟️", "pin", "stadium"),
    ("plein-air", "Plein air & rando", "Outdoors & hiking", "🥾", "pin", "hike"),
    ("mer", "Mer & plage", "Sea & beach", "🏖️", "chaise", "sea"),
    ("atelier", "Atelier & cours", "Workshops & classes", "🎨", "ocre", "brush"),
    ("conference", "Conférence & rencontre", "Talks & meetings", "🎤", "nuit", "mic"),
    ("langues", "Échanges linguistiques & international", "Language exchanges & international", "🌍", "chaise", "lang"),
    ("rencontres", "Rencontres en groupe", "Group meetups", "💞", "corail", "meet"),
    ("networking", "Networking & pro", "Networking & business", "🤝", "nuit", "handshake"),
    ("bien-etre", "Bien-être", "Wellbeing", "🧘", "pin", "leaf"),
    ("solidarite", "Solidarité & bénévolat", "Volunteering & solidarity", "🙌", "ocre", "heart"),
    ("jeux", "Jeux & gaming", "Games & gaming", "🎲", "lavande", "dice"),
    ("famille", "Famille & enfants", "Family & kids", "🧸", "soleil", "kids"),
    ("autre", "Autre", "Other", "📍", "nuit", "pin"),
]
