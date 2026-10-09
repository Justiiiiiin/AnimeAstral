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
    """Decimal number in a text: German with comma (“1,6”), English with point (“1.6”)."""
    return text.replace(".", ",") if _lang == "de" else text


def thousands(text: str) -> str:
    """Thousands separator from f"{x:,}": German with point (“1.234”), English with comma (“1,234”)."""
    return text.replace(",", ".") if _lang == "de" else text


def N_(text: str) -> str:
    """Marks texts in lists/constants that are shown later with tr() (for the completeness check)."""
    return text


def tr(text: str, **values) -> str:
    if _lang == "de":
        from .i18n_de import DE
        text = DE.get(text, text)
    return text.format(**values) if values else text
