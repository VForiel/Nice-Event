"""Données structurées schema.org Event (résultats « événements » des moteurs de recherche)."""

import json

from django.conf import settings
from django.utils.safestring import mark_safe

from core import markdown

STATUS = {
    "scheduled": "https://schema.org/EventScheduled",
    "full": "https://schema.org/EventScheduled",
    "postponed": "https://schema.org/EventPostponed",
    "cancelled": "https://schema.org/EventCancelled",
}


def event_jsonld(event, image_url=""):
    venue = event.venue
    data = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": event.title_tr,
        "description": event.summary_tr or markdown.plain(event.description_tr, 300),
        "startDate": event.local_start.isoformat() if not event.all_day else event.local_start.date().isoformat(),
        "eventStatus": STATUS.get(event.state, STATUS["scheduled"]),
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "url": settings.SITE_URL + event.get_absolute_url(),
        "location": {
            "@type": "Place",
            "name": venue.name,
            "address": {"@type": "PostalAddress", "streetAddress": venue.address, "addressLocality": venue.commune.name,
                        "postalCode": venue.commune.postcodes.split(",")[0],
                        "addressCountry": "MC" if venue.commune.insee == "99138" else "FR"},
            "geo": {"@type": "GeoCoordinates", "latitude": venue.lat, "longitude": venue.lon},
        },
    }
    if event.end:
        data["endDate"] = event.local_end.isoformat() if not event.all_day else event.local_end.date().isoformat()
    if image_url:
        data["image"] = [image_url]
    if event.display_organizer:
        data["organizer"] = {"@type": "Organization", "name": event.display_organizer}
        if event.organizer_url:
            data["organizer"]["url"] = event.organizer_url
    offer = {"@type": "Offer", "priceCurrency": "EUR", "availability":
             "https://schema.org/SoldOut" if event.is_full else "https://schema.org/InStock"}
    if event.is_free:
        offer["price"] = "0"
    elif event.price_min is not None:
        offer["price"] = f"{event.price_min:.2f}"
    if event.ticket_url:
        offer["url"] = event.ticket_url
    data["offers"] = offer
    if event.age_min:
        data["typicalAgeRange"] = f"{event.age_min}-{event.age_max or ''}"
    raw = json.dumps(data, ensure_ascii=False)
    # Même échappement que json_script : rien ne peut refermer la balise <script>.
    raw = raw.replace("<", "\\u003C").replace(">", "\\u003E").replace("&", "\\u0026")
    return mark_safe(raw)
