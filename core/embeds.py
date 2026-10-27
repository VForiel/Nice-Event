"""Médias hébergés ailleurs (YouTube, Vimeo, Pinterest, Google Photos…) : reconnaissance des liens collés par les membres.

YouTube, Vimeo et Dailymotion se lisent sur place, mais le lecteur n'est chargé qu'au clic (rien n'est demandé à ces
sites avant : RGPD, performances). Les autres plateformes s'affichent en carte avec un lien sortant.
Les domaines des lecteurs doivent figurer dans la directive CSP frame-src (FRAME_SOURCES).
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

FRAME_SOURCES = ["https://www.youtube-nocookie.com", "https://player.vimeo.com", "https://geo.dailymotion.com"]

# (motif du domaine, nom affiché) : plateformes reconnues sans lecteur intégré
PLATFORMS = [
    (r"(^|\.)pinterest\.[a-z.]+$|^pin\.it$", "Pinterest"),
    (r"^photos\.google\.com$|^photos\.app\.goo\.gl$", "Google Photos"),
    (r"^(drive|docs)\.google\.com$", "Google Drive"),
    (r"(^|\.)flickr\.com$|^flic\.kr$", "Flickr"),
    (r"(^|\.)instagram\.com$", "Instagram"),
    (r"(^|\.)facebook\.com$|^fb\.watch$", "Facebook"),
    (r"(^|\.)tiktok\.com$", "TikTok"),
    (r"(^|\.)icloud\.com$", "iCloud"),
    (r"^(onedrive\.live\.com|1drv\.ms)$|(^|\.)sharepoint\.com$", "OneDrive"),
    (r"(^|\.)dropbox\.com$", "Dropbox"),
    (r"(^|\.)we\.tl$|(^|\.)wetransfer\.com$", "WeTransfer"),
    (r"(^|\.)imgur\.com$", "Imgur"),
    (r"(^|\.)twitch\.tv$", "Twitch"),
    (r"(^|\.)peertube\.|(^|\.)framatube\.org$", "PeerTube"),
]

YOUTUBE_ID = re.compile(r"^[\w-]{11}$")


@dataclass
class Embed:
    provider: str  # nom affiché
    player: str = ""  # adresse du lecteur intégrable, vide = simple lien


def _youtube(url):
    host = url.hostname.removeprefix("www.").removeprefix("m.")
    video = ""
    if host == "youtu.be":
        video = url.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com", "youtube-nocookie.com"):
        parts = url.path.strip("/").split("/")
        if parts[0] == "watch":
            video = parse_qs(url.query).get("v", [""])[0]
        elif parts[0] in ("shorts", "live", "embed") and len(parts) > 1:
            video = parts[1]
    else:
        return None
    if not YOUTUBE_ID.match(video):
        return Embed("YouTube")
    return Embed("YouTube", f"https://www.youtube-nocookie.com/embed/{video}")


def _vimeo(url):
    host = url.hostname.removeprefix("www.")
    if host not in ("vimeo.com", "player.vimeo.com"):
        return None
    parts = [p for p in url.path.split("/") if p]
    ids = [i for i, p in enumerate(parts) if p.isdigit()]
    if not ids:
        return Embed("Vimeo")
    i = ids[0]
    player = f"https://player.vimeo.com/video/{parts[i]}?dnt=1"
    unlisted = parse_qs(url.query).get("h", [""])[0] or (parts[i + 1] if len(parts) > i + 1 and parts[i + 1].isalnum() else "")
    return Embed("Vimeo", player + (f"&h={unlisted}" if unlisted else ""))


def _dailymotion(url):
    host = url.hostname.removeprefix("www.")
    if host == "dai.ly":
        video = url.path.strip("/")
    elif host == "dailymotion.com" and url.path.startswith("/video/"):
        video = url.path.split("/")[2].split("_")[0]
    else:
        return None
    if not re.match(r"^[a-zA-Z0-9]+$", video or ""):
        return Embed("Dailymotion")
    return Embed("Dailymotion", f"https://geo.dailymotion.com/player.html?video={video}")


def parse(link):
    """Embed pour une adresse https, None si l'adresse n'est pas acceptable (autre protocole, pas de domaine)."""
    try:
        url = urlparse(link.strip())
    except ValueError:
        return None
    if url.scheme != "https" or not url.hostname:
        return None
    for reader in (_youtube, _vimeo, _dailymotion):
        found = reader(url)
        if found:
            return found
    host = url.hostname.removeprefix("www.")
    for pattern, name in PLATFORMS:
        if re.search(pattern, host):
            return Embed(name)
    return Embed(host)
