"""Téléchargements polis : agent identifié, robots.txt respecté, une requête à la fois avec une pause par domaine."""

import re
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from core.text import decode

AGENT = "NiceEventBot/1.0 (+https://nice-event.fr/contact/)"
PAUSE = 1.0  # secondes entre deux requêtes vers un même domaine
MAX_BYTES = 8 * 1024 * 1024


class FetchError(Exception):
    pass


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": AGENT, "Accept-Language": "fr,en;q=0.5"})
        self.robots = {}
        self.last = {}
        self.count = 0

    def allowed(self, url):
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self.robots:
            parser = RobotFileParser()
            try:
                response = self.session.get(f"{base}/robots.txt", timeout=15)
                parser.parse(response.text.splitlines() if response.status_code == 200 else [])
            except requests.RequestException:
                parser.parse([])
            self.robots[base] = parser
        return self.robots[base].can_fetch(AGENT, url)

    def get(self, url, *, params=None, check_robots=True, binary=False):
        if check_robots and not self.allowed(url):
            raise FetchError(f"Interdit par robots.txt : {url}")
        host = urlsplit(url).netloc
        wait = PAUSE - (time.monotonic() - self.last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        try:
            response = self.session.get(url, params=params, timeout=30, stream=True)
            content = response.raw.read(MAX_BYTES + 1, decode_content=True)
        except requests.RequestException as exc:
            raise FetchError(f"{url} : {exc}") from exc
        finally:
            self.last[host] = time.monotonic()
            self.count += 1
        if response.status_code >= 400:
            raise FetchError(f"{url} : HTTP {response.status_code}")
        if len(content) > MAX_BYTES:
            raise FetchError(f"{url} : réponse trop volumineuse")
        if binary:
            return content
        # requests suppose Latin-1 quand l'en-tête ne précise rien (flux iCal de Meetup…) : accents et emojis cassés.
        match = re.search(r"charset=[\"']?([\w.-]+)", response.headers.get("Content-Type", ""), re.I)
        return decode(content, match.group(1) if match else None)
