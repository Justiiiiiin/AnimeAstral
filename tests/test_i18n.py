"""Englische Oberfläche: Jeder Text in tr()/N_() hat eine Übersetzung mit denselben Platzhaltern."""
import ast
import re
import string
import unittest
from pathlib import Path

import _env  # noqa: F401
from astral_monitor import i18n
from astral_monitor.i18n_en import EN

PACKAGE = Path(__file__).resolve().parent.parent / "astral_monitor"


def keys_in_code() -> dict[str, str]:
    """Alle Texte, die als erstes Argument von tr()/N_() im Paket stehen -> Fundstelle."""
    found: dict[str, str] = {}
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("tr", "N_") and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.setdefault(node.args[0].value, f"{path.name}:{node.lineno}")
    return found


def placeholders(text: str) -> set[str]:
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name}


class I18nTests(unittest.TestCase):
    def test_every_text_has_english(self):
        missing = {k: where for k, where in keys_in_code().items() if k not in EN}
        self.assertEqual(missing, {}, f"{len(missing)} Texte ohne englische Übersetzung")

    def test_placeholders_match(self):
        wrong = {k: v for k, v in EN.items() if placeholders(k) != placeholders(v)}
        self.assertEqual(wrong, {})

    def test_no_stale_entries(self):
        stale = sorted(set(EN) - set(keys_in_code()))
        self.assertEqual(stale, [], "Übersetzungen ohne Verwendung im Code")

    def test_tr_switches_language(self):
        try:
            i18n.set_language("en")
            self.assertEqual(i18n.tr("Welle {wave}", wave="3/100"), "Wave 3/100")
            self.assertEqual(i18n.dec("1.5"), "1.5")
            i18n.set_language("de")
            self.assertEqual(i18n.tr("Welle {wave}", wave="3/100"), "Welle 3/100")
            self.assertEqual(i18n.dec("1.5"), "1,5")
            self.assertEqual(i18n.tr("Gibt es nicht"), "Gibt es nicht")       # unbekannt: unverändert
        finally:
            i18n.set_language("de")

    def test_english_has_no_umlauts(self):
        german = {k: v for k, v in EN.items() if re.search(r"[äöüÄÖÜß]", v)}
        self.assertEqual(german, {})


if __name__ == "__main__":
    unittest.main()
