"""Own Roblox profile (name + avatar) via the public Roblox API – no login, no cookie.
The avatar is stored as an image in the data folder and appears in the sidebar and on the statistics cards."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from . import app_paths
from .i18n import tr

log = logging.getLogger("profile")

USERS_API = "https://users.roblox.com/v1/usernames/users"
AVATAR_API = ("https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={id}&size=150x150&format=Png"
              "&isCircular=true")
REFRESH_EVERY = 24 * 3600                       # reload the avatar at most once a day
_NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")  # Roblox user names


@dataclass
class Profile:
    user_id: int
    name: str
    display_name: str


class ProfileError(RuntimeError):
    pass


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name.strip()))


def avatar_file():
    return app_paths.data_dir() / "avatar.png"


def _info_file():
    return app_paths.data_dir() / "profile.json"


def lookup(name: str, poster: Callable = requests.post, timeout: float = 10.0) -> Profile:
    """User name -> profile. Errors -> ProfileError (text for display)."""
    name = name.strip()
    if not valid_name(name):
        raise ProfileError(tr("Not a valid Roblox name (3–20 characters: letters, digits, _)."))
    try:
        resp = poster(USERS_API, json={"usernames": [name], "excludeBannedUsers": True}, timeout=timeout)
        data = resp.json().get("data") if resp.status_code == 200 else None
    except (requests.RequestException, ValueError, AttributeError) as exc:
        raise ProfileError(tr("Roblox can't be reached right now.")) from exc
    if not data:
        raise ProfileError(tr("This Roblox name doesn't exist."))
    user = data[0]
    return Profile(int(user["id"]), str(user.get("name") or name), str(user.get("displayName") or name))


def download_avatar(user_id: int, getter: Callable = requests.get, timeout: float = 10.0) -> bool:
    """Load and save the avatar (head, round). Returns: did it work?"""
    try:
        resp = getter(AVATAR_API.format(id=int(user_id)), timeout=timeout)
        items = resp.json().get("data") or [] if resp.status_code == 200 else []
        url = items[0].get("imageUrl") if items else None
        if not url or not url.startswith("https://") or not re.match(r"https://[\w.-]*rbxcdn\.com/", url):
            return False                                    # only images from the Roblox CDN
        img = getter(url, timeout=timeout)
        if img.status_code != 200 or not img.content.startswith(b"\x89PNG"):
            return False
        avatar_file().write_bytes(img.content)
        return True
    except (requests.RequestException, ValueError, AttributeError, OSError):
        log.info("Could not load the avatar", exc_info=True)
        return False


def save_info(profile: Profile) -> None:
    _info_file().write_text(json.dumps({"id": profile.user_id, "name": profile.name,
                                        "display": profile.display_name, "at": time.time()}), encoding="utf-8")


def load_info() -> Optional[dict]:
    try:
        return json.loads(_info_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def needs_refresh(name: str, info: Optional[dict], now: Optional[float] = None) -> bool:
    """Reload if a different name is entered, the image is missing or older than a day."""
    if not name:
        return False
    if not info or str(info.get("name", "")).lower() != name.strip().lower() or not avatar_file().is_file():
        return True
    return (now or time.time()) - float(info.get("at", 0)) > REFRESH_EVERY


def clear() -> None:
    for path in (avatar_file(), _info_file()):
        path.unlink(missing_ok=True)


def refresh(name: str) -> Profile:
    """Look up the profile, load the avatar, remember it (call in a background thread)."""
    profile = lookup(name)
    download_avatar(profile.user_id)
    save_info(profile)
    return profile
