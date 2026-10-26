"""Extrait le fond de carte des Alpes-Maritimes et de Monaco d'une construction mondiale Protomaps (PMTiles).

    python scripts/extract_tiles.py                     # construction du jour -> tiles/nice-region.pmtiles
    python scripts/extract_tiles.py --build 20261026    # construction précise

Seules les tuiles de l'emprise sont téléchargées (requêtes HTTP par plages d'octets, regroupées quand les tuiles
se suivent dans le fichier) : quelques centaines de requêtes et ~100–300 Mo, au lieu des 140 Go du fichier mondial.
Le fichier obtenu est servi par le conteneur « tiles » (voir compose.yaml) ; à refaire de temps en temps (les
données OpenStreetMap évoluent), il n'y a rien d'autre à changer.

Dépendance de développement : pmtiles (pip).
"""

import argparse
import math
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from pmtiles.tile import deserialize_directory, deserialize_header, find_tile, zxy_to_tileid
from pmtiles.writer import Writer

ROOT = Path(__file__).resolve().parent.parent
BBOX = (6.62, 43.46, 7.73, 44.37)  # ouest, sud, est, nord
MAX_ZOOM = 15
GAP = 256 * 1024  # deux tuiles séparées de moins de 256 Ko sont lues d'un seul coup
CHUNK = 8 * 1024 * 1024
HEADERS = {"User-Agent": "Nice-Event tile extract (+https://nice-event.fr)"}


def fetch(url, offset, length, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={**HEADERS, "Range": f"bytes={offset}-{offset + length - 1}"})
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()
            if len(data) != length:
                raise OSError(f"réponse incomplète ({len(data)}/{length})")
            return data
        except OSError:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


def tile_range(z, west, south, east, north):
    n = 2 ** z

    def x_of(lon):
        return min(n - 1, max(0, int((lon + 180) / 360 * n)))

    def y_of(lat):
        r = math.radians(lat)
        return min(n - 1, max(0, int((1 - math.asinh(math.tan(r)) / math.pi) / 2 * n)))

    return range(x_of(west), x_of(east) + 1), range(y_of(north), y_of(south) + 1)


class Archive:
    def __init__(self, url):
        self.url = url
        self.header = deserialize_header(fetch(url, 0, 127))
        self.root = deserialize_directory(fetch(url, self.header["root_offset"], self.header["root_length"]))
        self.leaves = {}

    def leaf(self, offset, length):
        if offset not in self.leaves:
            self.leaves[offset] = deserialize_directory(fetch(self.url, self.header["leaf_directory_offset"] + offset, length))
        return self.leaves[offset]

    def locate(self, tile_id):
        """(décalage absolu, longueur) de la tuile, ou None si elle n'existe pas (mer, zoom absent)."""
        directory = self.root
        for _depth in range(4):
            entry = find_tile(directory, tile_id)
            if entry is None:
                return None
            if entry.run_length == 0:
                directory = self.leaf(entry.offset, entry.length)
                continue
            return self.header["tile_data_offset"] + entry.offset, entry.length
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default=(date.today() - timedelta(days=1)).strftime("%Y%m%d"))
    parser.add_argument("--out", default=str(ROOT / "tiles" / "nice-region.pmtiles"))
    args = parser.parse_args()
    url = f"https://build.protomaps.com/{args.build}.pmtiles"
    archive = Archive(url)
    print(f"Source : {url} (zoom {archive.header['min_zoom']}–{archive.header['max_zoom']})")

    wanted = []
    for z in range(0, min(MAX_ZOOM, archive.header["max_zoom"]) + 1):
        xs, ys = tile_range(z, *BBOX)
        wanted += [zxy_to_tileid(z, x, y) for x in xs for y in ys]
    wanted.sort()
    print(f"{len(wanted)} tuiles dans l'emprise")

    # Répertoires feuilles nécessaires, téléchargés en parallèle.
    needed = {}
    for tile_id in wanted:
        entry = find_tile(archive.root, tile_id)
        if entry is not None and entry.run_length == 0:
            needed[entry.offset] = entry.length
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda item: archive.leaf(*item), needed.items()))
    located = [(tile_id, archive.locate(tile_id)) for tile_id in wanted]
    located = [(t, loc) for t, loc in located if loc]
    print(f"{len(located)} tuiles existantes, {len(archive.leaves)} répertoires lus")

    # Regroupe les plages proches, puis télécharge en parallèle.
    spans = []
    for _tile_id, (offset, length) in sorted(located, key=lambda item: item[1][0]):
        if spans and offset - (spans[-1][0] + spans[-1][1]) <= GAP and spans[-1][1] + length <= CHUNK:
            start = spans[-1][0]
            spans[-1][1] = max(spans[-1][1], offset + length - start)
        else:
            spans.append([offset, length])
    total = sum(s[1] for s in spans)
    print(f"{len(spans)} requêtes, {total / 1e6:.0f} Mo à télécharger")
    done = [0]

    def get(span):
        data = fetch(url, *span)
        done[0] += 1
        if done[0] % 50 == 0:
            print(f"  {done[0]}/{len(spans)}", flush=True)
        return span[0], data

    with ThreadPoolExecutor(8) as pool:
        blobs = dict(pool.map(get, spans))
    starts = sorted(blobs)

    def data_of(offset, length):
        import bisect

        start = starts[bisect.bisect_right(starts, offset) - 1]
        blob = blobs[start]
        return blob[offset - start: offset - start + length]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    header = dict(archive.header)
    west, south, east, north = BBOX
    header.update({
        "min_lon_e7": int(west * 1e7), "min_lat_e7": int(south * 1e7), "max_lon_e7": int(east * 1e7),
        "max_lat_e7": int(north * 1e7), "max_zoom": min(MAX_ZOOM, archive.header["max_zoom"]),
        "center_zoom": 11, "center_lon_e7": int(7.27 * 1e7), "center_lat_e7": int(43.70 * 1e7),
    })
    metadata = {"name": "Nice-Event : Alpes-Maritimes et Monaco", "attribution":
                "© OpenStreetMap contributors, Protomaps", "source": url}
    with open(tmp, "wb") as f:
        writer = Writer(f)
        for tile_id, (offset, length) in located:  # déjà triées par identifiant (ordre de Hilbert)
            writer.write_tile(tile_id, data_of(offset, length))
        writer.finalize(header, metadata)
    tmp.replace(out)
    print(f"Écrit : {out} ({out.stat().st_size / 1e6:.0f} Mo)")


if __name__ == "__main__":
    sys.exit(main())
