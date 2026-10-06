"""Sprache der Oberfläche und der Meldungen (Deutsch/Englisch).

Texte stehen im Code auf Deutsch und werden mit tr() übersetzt; die englischen Fassungen liegen in i18n_en.py
(Schlüssel = deutscher Text). Platzhalter wie {wave} werden nach dem Übersetzen eingesetzt:

    tr("Fehlversuch bei Welle {wave}", wave=29)

tests/test_i18n.py prüft, dass jeder tr()-Text eine englische Übersetzung hat. Die Sprache wird beim Start gesetzt;
ein Wechsel gilt nach einem Neustart. Protokoll (monitor.log) bleibt Deutsch.
"""
from __future__ import annotations

LANGUAGES = {"de": "Deutsch", "en": "English"}
_lang = "de"


def set_language(code: str) -> None:
    global _lang
    _lang = code if code in LANGUAGES else "de"


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
    if _lang == "en":
        from .i18n_en import EN
        text = EN.get(text, text)
    return text.format(**values) if values else text
