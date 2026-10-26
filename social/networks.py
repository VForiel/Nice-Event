"""Clients minimaux des API de publication : Bluesky (AT Protocol), Facebook et Instagram (API Graph de Meta), X (API v2).

Chaque fonction `publish_<réseau>` renvoie (identifiant, lien) ou lève PublishError avec un message lisible ;
`check(<réseau>, config)` vérifie les identifiants sans rien publier.
"""

import base64
import hashlib
import hmac
import io
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from PIL import Image

TIMEOUT = 30
BSKY = "https://bsky.social/xrpc"
X_API = "https://api.x.com/2"
URL = re.compile(r"https?://[^\s]+")


class PublishError(Exception):
    pass


def _raise(response, what):
    try:
        data = response.json()
    except ValueError:
        data = {}
    detail = (data.get("error", {}) or {}).get("message") if isinstance(data.get("error"), dict) else None
    detail = detail or data.get("message") or data.get("detail") or data.get("error") or response.text[:300]
    raise PublishError(f"{what} : {response.status_code} {detail}")


def _ok(response, what):
    if response.status_code >= 400:
        _raise(response, what)
    return response.json() if response.content else {}


# Bluesky ---------------------------------------------------------------------------------------------------------------


def bluesky_session(config):
    r = requests.post(f"{BSKY}/com.atproto.server.createSession", timeout=TIMEOUT,
                      json={"identifier": config.bluesky_handle.lstrip("@"), "password": config.bluesky_app_password})
    return _ok(r, "Connexion à Bluesky")


def small_jpeg(path, limit=950_000):
    """Bluesky refuse les images de plus d'environ 1 Mo : on réduit la qualité, puis la taille, jusqu'à passer."""
    img = Image.open(path).convert("RGB")
    for quality in (88, 80, 72, 64):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
        if buf.tell() <= limit:
            return buf.getvalue(), img.size
    img.thumbnail((img.width * 3 // 4, img.height * 3 // 4))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70, optimize=True)
    return buf.getvalue(), img.size


def link_facets(text):
    """Liens cliquables : Bluesky repère les URL par leurs positions en octets UTF-8."""
    facets = []
    for match in URL.finditer(text):
        start = len(text[:match.start()].encode())
        end = start + len(match.group().encode())
        facets.append({"index": {"byteStart": start, "byteEnd": end},
                       "features": [{"$type": "app.bsky.richtext.facet#link", "uri": match.group()}]})
    return facets


def publish_bluesky(post, config, image_path, image_url, alt):
    session = bluesky_session(config)
    auth = {"Authorization": f"Bearer {session['accessJwt']}"}
    data, (width, height) = small_jpeg(image_path)
    blob = _ok(requests.post(f"{BSKY}/com.atproto.repo.uploadBlob", data=data, timeout=TIMEOUT,
                             headers={**auth, "Content-Type": "image/jpeg"}), "Envoi de l'image à Bluesky")["blob"]
    record = {
        "$type": "app.bsky.feed.post",
        "text": post.text,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "langs": ["fr"],
        "facets": link_facets(post.text),
        "embed": {"$type": "app.bsky.embed.images",
                  "images": [{"alt": alt, "image": blob, "aspectRatio": {"width": width, "height": height}}]},
    }
    answer = _ok(requests.post(f"{BSKY}/com.atproto.repo.createRecord", headers=auth, timeout=TIMEOUT,
                               json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record}),
                 "Publication sur Bluesky")
    rkey = answer["uri"].rsplit("/", 1)[-1]
    return answer["uri"], f"https://bsky.app/profile/{session['handle']}/post/{rkey}"


# Facebook et Instagram (API Graph) ---------------------------------------------------------------------------------------


def graph(config, path):
    return f"https://graph.facebook.com/{config.meta_api_version}/{path}"


def publish_facebook(post, config, image_path, image_url, alt):
    with open(image_path, "rb") as f:
        answer = _ok(requests.post(graph(config, f"{config.facebook_page_id}/photos"), timeout=60,
                                   data={"caption": post.text, "access_token": config.facebook_page_token},
                                   files={"source": ("visuel.jpg", f, "image/jpeg")}), "Publication sur Facebook")
    post_id = answer.get("post_id") or answer.get("id")
    return post_id, f"https://www.facebook.com/{post_id}"


def publish_instagram(post, config, image_path, image_url, alt):
    """Instagram va chercher l'image à son adresse publique (servie par nice-event.fr), en JPEG."""
    token = config.facebook_page_token
    container = _ok(requests.post(graph(config, f"{config.instagram_user_id}/media"), timeout=60,
                                  data={"image_url": image_url, "caption": post.text, "alt_text": alt[:1000],
                                        "access_token": token}), "Préparation sur Instagram")["id"]
    for _attempt in range(20):  # Instagram traite l'image avant publication
        state = _ok(requests.get(graph(config, container), timeout=TIMEOUT,
                                 params={"fields": "status_code", "access_token": token}), "Suivi Instagram")
        if state.get("status_code") == "FINISHED":
            break
        if state.get("status_code") in ("ERROR", "EXPIRED"):
            raise PublishError(f"Instagram a refusé l'image ({state.get('status_code')})")
        time.sleep(3)
    media = _ok(requests.post(graph(config, f"{config.instagram_user_id}/media_publish"), timeout=60,
                              data={"creation_id": container, "access_token": token}), "Publication sur Instagram")["id"]
    link = _ok(requests.get(graph(config, media), timeout=TIMEOUT,
                            params={"fields": "permalink", "access_token": token}), "Lien Instagram").get("permalink", "")
    return media, link


# X (OAuth 1.0a, contexte utilisateur) ------------------------------------------------------------------------------------


def _enc(value):
    return quote(str(value), safe="~")


def oauth1_header(method, url, config, params=None):
    oauth = {
        "oauth_consumer_key": config.x_api_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": config.x_access_token,
        "oauth_version": "1.0",
    }
    pairs = sorted((_enc(k), _enc(v)) for k, v in {**(params or {}), **oauth}.items())
    base = "&".join([method.upper(), _enc(url), _enc("&".join(f"{k}={v}" for k, v in pairs))])
    key = f"{_enc(config.x_api_secret)}&{_enc(config.x_access_secret)}"
    oauth["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_enc(k)}="{_enc(v)}"' for k, v in sorted(oauth.items()))


def publish_x(post, config, image_path, image_url, alt):
    upload_url = f"{X_API}/media/upload"
    with open(image_path, "rb") as f:
        media = _ok(requests.post(upload_url, timeout=60, headers={"Authorization": oauth1_header("POST", upload_url, config)},
                                  files={"media": ("visuel.jpg", f, "image/jpeg")},
                                  data={"media_category": "tweet_image"}), "Envoi de l'image à X")
    media_id = (media.get("data") or {}).get("id") or media.get("media_id_string")
    tweet_url = f"{X_API}/tweets"
    answer = _ok(requests.post(tweet_url, timeout=TIMEOUT, headers={"Authorization": oauth1_header("POST", tweet_url, config)},
                               json={"text": post.text, "media": {"media_ids": [str(media_id)]}}), "Publication sur X")
    tweet = answer["data"]["id"]
    return tweet, f"https://x.com/i/status/{tweet}"


PUBLISHERS = {"bluesky": publish_bluesky, "facebook": publish_facebook, "instagram": publish_instagram, "x": publish_x}


# Vérification des comptes --------------------------------------------------------------------------------------------------


def check(network, config):
    """(ok, message) : les identifiants permettent-ils de publier ?"""
    try:
        if network == "bluesky":
            session = bluesky_session(config)
            return True, f"Connecté en tant que @{session['handle']}"
        if network == "facebook":
            page = _ok(requests.get(graph(config, config.facebook_page_id), timeout=TIMEOUT,
                                    params={"fields": "name", "access_token": config.facebook_page_token}), "Page Facebook")
            return True, f"Page « {page.get('name')} »"
        if network == "instagram":
            account = _ok(requests.get(graph(config, config.instagram_user_id), timeout=TIMEOUT,
                                       params={"fields": "username", "access_token": config.facebook_page_token}),
                          "Compte Instagram")
            return True, f"Compte @{account.get('username')}"
        if network == "x":
            me_url = f"{X_API}/users/me"
            me = _ok(requests.get(me_url, timeout=TIMEOUT, headers={"Authorization": oauth1_header("GET", me_url, config)}),
                     "Compte X")
            return True, f"Connecté en tant que @{me['data']['username']}"
    except (PublishError, requests.RequestException, KeyError) as exc:
        return False, str(exc)[:300]
    return False, "Réseau inconnu"
