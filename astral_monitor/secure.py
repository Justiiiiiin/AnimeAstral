"""Geheimnisse schützen.

1. Lokal (settings.json): Webhook-URL, Server-Links und IDs werden mit Windows-DPAPI verschlüsselt („dpapi:…“) – nur
   dein Windows-Konto auf diesem PC kann sie lesen. Auf einem anderen PC bleiben sie leer → dafür gibt es:
2. Export mit Passwort (.astralsettings): alle Einstellungen, AES-256-GCM, Schlüssel per scrypt aus dem Passwort.
   Ohne Passwort unlesbar; ein vergessenes Passwort lässt sich nicht wiederherstellen."""
from __future__ import annotations

import base64
import json
import logging
import os
import sys
from pathlib import Path

from .i18n import tr

log = logging.getLogger("secure")

PREFIX = "dpapi:"
EXPORT_FORMAT = "astral-settings-1"
EXPORT_SUFFIX = ".astralsettings"
MIN_PASSWORD = 8
_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}           # ~0,1 s und 32 MB je Versuch – bremst Passwort-Raten


class SecureError(ValueError):
    pass


# ------------------------------------------------------------------ lokal: Windows-DPAPI
def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = BLOB()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    entropy = b"AnimeAstralMonitor"
    ebuf = ctypes.create_string_buffer(entropy, len(entropy))
    blob_entropy = BLOB(len(entropy), ctypes.cast(ebuf, ctypes.POINTER(ctypes.c_char)))
    if not fn(ctypes.byref(blob_in), None, ctypes.byref(blob_entropy), None, None, 0x1, ctypes.byref(blob_out)):
        raise OSError(ctypes.GetLastError(), "DPAPI fehlgeschlagen")      # 0x1 = CRYPTPROTECT_UI_FORBIDDEN
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect(text: str) -> str:
    """Für settings.json verschlüsseln (nur Windows; sonst unverändert)."""
    if not text or text.startswith(PREFIX) or sys.platform != "win32":
        return text
    try:
        return PREFIX + base64.b64encode(_dpapi(text.encode("utf-8"), True)).decode("ascii")
    except Exception:
        log.warning("Konnte nicht lokal verschlüsseln – wird unverschlüsselt gespeichert.", exc_info=True)
        return text


def unprotect(text: str) -> str:
    """Gegenstück zu protect(). Klartext (ältere Versionen) bleibt, wie er ist; nicht lesbar (anderer PC/Benutzer) → ""."""
    if not isinstance(text, str) or not text.startswith(PREFIX):
        return text
    try:
        return _dpapi(base64.b64decode(text[len(PREFIX):]), False).decode("utf-8")
    except Exception:
        log.warning("Ein gespeicherter Wert ist auf diesem PC nicht lesbar (anderer PC oder Benutzer?) – "
                    "bitte neu eintragen oder Einstellungen importieren.")
        return ""


# ------------------------------------------------------------------ Export/Import mit Passwort
def _key(password: str, salt: bytes, params: dict) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=params["n"], r=params["r"], p=params["p"]).derive(password.encode("utf-8"))


def check_password(password: str, repeat: str | None = None) -> str | None:
    """Fehlermeldung oder None."""
    if len(password) < MIN_PASSWORD:
        return tr("The password needs at least {n} characters.", n=MIN_PASSWORD)
    if repeat is not None and password != repeat:
        return tr("The passwords do not match.")
    return None


def export_settings(data: dict, password: str, path: Path) -> Path:
    """Einstellungen (Klartext-Dict) verschlüsselt als Datei speichern."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    problem = check_password(password)
    if problem:
        raise SecureError(problem)
    salt, nonce = os.urandom(16), os.urandom(12)
    plain = json.dumps({"settings": data}, ensure_ascii=False).encode("utf-8")
    header = {"format": EXPORT_FORMAT, "kdf": "scrypt", **_SCRYPT}
    aad = json.dumps(header, sort_keys=True).encode("ascii")          # Kopfdaten sind mit geschützt
    cipher = AESGCM(_key(password, salt, _SCRYPT)).encrypt(nonce, plain, aad)
    payload = dict(header, salt=base64.b64encode(salt).decode(), nonce=base64.b64encode(nonce).decode(),
                   data=base64.b64encode(cipher).decode())
    path = path if path.suffix.lower() == EXPORT_SUFFIX else path.with_suffix(EXPORT_SUFFIX)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def import_settings(path: Path, password: str) -> dict:
    """Datei entschlüsseln → Einstellungen (Klartext-Dict). Falsches Passwort/kaputte Datei → SecureError."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("format") != EXPORT_FORMAT or payload.get("kdf") != "scrypt":
            raise SecureError(tr("This is not a settings file of this program."))
        params = {k: int(payload[k]) for k in ("n", "r", "p")}
        if not (2 ** 14 <= params["n"] <= 2 ** 20 and 1 <= params["r"] <= 32 and 1 <= params["p"] <= 16):
            raise SecureError(tr("The file is damaged."))
        header = {"format": EXPORT_FORMAT, "kdf": "scrypt", **params}
        aad = json.dumps(header, sort_keys=True).encode("ascii")
        salt, nonce = base64.b64decode(payload["salt"]), base64.b64decode(payload["nonce"])
        plain = AESGCM(_key(password, salt, params)).decrypt(nonce, base64.b64decode(payload["data"]), aad)
        data = json.loads(plain.decode("utf-8"))["settings"]
    except InvalidTag:
        raise SecureError(tr("Wrong password or damaged file.")) from None
    except SecureError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SecureError(tr("The file is damaged.") + f" ({type(exc).__name__})") from None
    if not isinstance(data, dict):
        raise SecureError(tr("The file is damaged."))
    return data
