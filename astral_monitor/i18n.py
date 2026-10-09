"""Language of the UI and of the messages (English/German).

Texts are written in English in the code and translated with tr(); the German versions live in i18n_de.py
(key = English text). Placeholders like {wave} are filled in after translating:

    tr("Raid finished · Wave {wave}", wave=29)

tests/test_i18n.py checks that every tr() text has a German translation. The language is set at start-up;
switching takes effect after a restart. English is the default since 0.9.9-beta.13.
"""
from __future__ import annotations

LANGUAGES = {"de": "Deutsch", "en": "English"}
_lang = "en"


def set_language(code: str) -> None:
    global _lang
    _lang = code if code in LANGUAGES else "en"


def language() -> str:
    return _lang


def dec(text: str) -> str:
    """Dezimalzahl im Text: Deutsch mit Komma („1,6“), Englisch mit Punkt („1.6“)."""
    return text.replace(".", ",") if _lang == "de" else text


def thousands(text: str) -> str:
    """Tausendertrennung aus f"{x:,}": Deutsch mit Punkt („1.234“), Englisch mit Komma („1,234“)."""
    return text.replace(",", ".") if _lang == "de" else text


def N_(text: str) -> str:
    """Markiert Texte in Listen/Konstanten, die erst später mit tr() angezeigt werden (für die Vollständigkeitsprüfung)."""
    return text


def tr(text: str, **values) -> str:
    if _lang == "de":
        from .i18n_de import DE
        text = DE.get(text, text)
    return text.format(**values) if values else text
