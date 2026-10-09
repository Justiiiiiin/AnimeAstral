"""German UI: every text in tr()/N_() has a translation with the same placeholders."""
import ast
import re
import string
import unittest
from pathlib import Path

import _env  # noqa: F401
from astral_monitor import i18n
from astral_monitor.i18n_de import DE

PACKAGE = Path(__file__).resolve().parent.parent / "astral_monitor"


def keys_in_code() -> dict[str, str]:
    """All texts that are the first argument of tr()/N_() in the package -> location."""
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


def needs_translation(key: str) -> bool:
    """Texts without letters (symbols, numbers) or identical in both languages need no entry."""
    return bool(re.search(r"[A-Za-z]", key))


class I18nTests(unittest.TestCase):
    def test_every_text_has_german(self):
        missing = {k: where for k, where in keys_in_code().items() if k not in DE and needs_translation(k)}
        self.assertEqual(missing, {}, f"{len(missing)} texts without a German translation")

    def test_placeholders_match(self):
        wrong = {k: v for k, v in DE.items() if placeholders(k) != placeholders(v)}
        self.assertEqual(wrong, {})

    def test_no_stale_entries(self):
        stale = sorted(set(DE) - set(keys_in_code()))
        self.assertEqual(stale, [], "translations not used in the code")

    def test_tr_switches_language(self):
        try:
            i18n.set_language("de")
            self.assertEqual(i18n.tr("Wave {wave}", wave="3/100"), "Welle 3/100")
            self.assertEqual(i18n.dec("1.5"), "1,5")
            i18n.set_language("en")
            self.assertEqual(i18n.tr("Wave {wave}", wave="3/100"), "Wave 3/100")
            self.assertEqual(i18n.dec("1.5"), "1.5")
            self.assertEqual(i18n.tr("Does not exist"), "Does not exist")       # unknown: unchanged
        finally:
            i18n.set_language("en")

    def test_code_texts_are_english(self):
        german = {k: v for k, v in keys_in_code().items() if re.search(r"[äöüÄÖÜß]", k)}
        self.assertEqual(german, {})


if __name__ == "__main__":
    unittest.main()
