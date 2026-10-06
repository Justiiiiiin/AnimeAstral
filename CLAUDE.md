# CLAUDE.md – Übergabe für Claude Code

Dieses Dokument beschreibt das Projekt **Anime Astral Monitor**, damit du ohne Einarbeitung weiterarbeiten kannst.
Der Entwicklungsverlauf stammt aus einem langen Chat (Claude im Browser), in dem **nichts unter Windows, nichts mit echtem
Roblox, keine echte Oberfläche und kein echter GitHub-Lauf** getestet werden konnte. Alles Genannte unter „Ungetestet“
ist deshalb die wichtigste Arbeit für dich: **selbst ausführen, Fehler lesen, beheben.**

## Was das Programm ist

Windows-Desktop-App (Python 3.12, PySide6), die das Roblox-Fenster des Spiels **Anime Astral Simulator** per Bildaufnahme
überwacht. Sie liest den Wellenzähler („Wave 12/100“) und die Quest-Liste per Texterkennung, zählt **Versuche und Wellen**,
führt Statistiken je Raid und meldet per **Discord-Webhook** (Raid-Ende mit Screenshot, Alarme, eine sich selbst
aktualisierende Statusnachricht, Statistik-Karten). Sie **sendet nie Eingaben** an Roblox (kein Klicken, keine Tasten) und
greift nicht in den Roblox-Prozess ein – das ist eine bewusste Grenze, bitte beibehalten.

Benutzer ist der Eigentümer (Deutsch, Windows 11); Freunde sollen es später ebenfalls nutzen („full release 1.0.0“).
**Alle Texte in der Oberfläche, in Meldungen und in der Dokumentation sind Deutsch.** Code, Kommentare und Docstrings
ebenfalls Deutsch (so ist der Bestand), Bezeichner englisch.

## Befehle

```
pip install -r requirements.txt           # Windows; windows-capture nur dort
python run.py                             # Programm starten (Oberfläche)
python -m unittest discover -s tests -v   # 43 Tests, ohne Qt/Tesseract/Netz lauffähig
python -m astral_monitor.selftest bild.png   # Erkennung an einem Screenshot prüfen (braucht Tesseract)
python build_exe.py [--no-zip] [--no-bundle-tesseract]   # EXE (PyInstaller, Ordner-Variante) + Tesseract bündeln
```

Datenordner zur Laufzeit: `%APPDATA%\AnimeAstralMonitor` (Umgebungsvariable `ASTRAL_DATA_DIR` überschreibt ihn, die Tests
nutzen das). Dort: `settings.json`, `raid_history.csv`, `monitor.log`, `profiles/`, `status_message.json`, `ui_state.json`,
`rpc_icon.json`, `updates/`, `debug/`.

## Architektur (Paket `astral_monitor/`)

| Datei | Aufgabe |
|---|---|
| `engine.py` | Zentrale Überwachungsschleife (eigener Thread), hält Zustand (`EngineState`), verbindet alle Teile, Ereignis-Queue zur Oberfläche |
| `capture.py` | Bildquellen: `WgcSource` (Windows Graphics Capture über Paket `windows-capture`, funktioniert bei verdecktem Fenster) und `ScreenSource` (Fallback). Liefert nur angeforderte Ausschnitte |
| `wave.py` | Wellenzähler **finden und lesen**: sucht „Wave x/y“ im Suchbereich selbst (Tesseract mit Wortpositionen), merkt sich den Ort, liest dann nur einen engen Bereich; Zwischenspeicher je Bild |
| `tracker.py` | Zustandsautomat der Wellen: Lauf-Start/-Ende, Neustart-Erkennung (2 passende Lesungen), **Plausibilitätsfilter** (unmögliche Sprünge nach oben werden ignoriert), Auslöser bei 99/100 |
| `quests.py` | Quest-Liste (Titel + Fortschritt) per OCR, `QuestTracker` in `tracker.py` |
| `stats.py` | `StatsStore` (CSV `raid_history.csv`), alle Kennzahlen, Verteilung, Trend, Rekorde |
| `profiles.py` | Raid-Profile: Referenzbilder, ORB-Merkmalsvergleich zur **Raid-Erkennung**, Export/Import (`.astralprofile`) |
| `guard.py` | Wächter: Roblox-Prozess, Disconnect-Dialog (OCR), Stillstand, RAM/CPU |
| `status.py` | **Live-Statusnachricht**: eine Discord-Nachricht, die per `PATCH` bearbeitet wird; „unten neu senden“ = `DELETE` + `POST` |
| `discord_client.py`, `messages.py` | Versand (eigener Thread, Wiederholung bei 429) und Embeds |
| `report_card.py` | Statistik-Karte als PNG (Pillow, kein Qt) |
| `presence.py` | Discord-Profilstatus (pypresence), Spiel-Thumbnail von Roblox als Bild |
| `updater.py` | Update-Prüfung über GitHub-Releases, Download mit SHA256-Prüfung, leiser Installer-Start |
| `ocr.py` | Tesseract-Anbindung; **mitgeliefertes** Tesseract (`tesseract/` neben der EXE) hat Vorrang |
| `settings.py` | `Settings`-Dataclass (JSON), `Roi`, Ereignis-Definitionen, Migration über `settings_version` |
| `hotkeys.py`, `winapi.py`, `imaging.py`, `diagnostics.py`, `app_paths.py` | Hilfen (globale Hotkeys per `RegisterHotKey`, Fenstersuche per ctypes, Bildverarbeitung, Diagnose-ZIP, Pfade) |
| `ui/` | PySide6-Oberfläche: `main_window.py` (Seitenleiste, Hotkeys, Update-Start, Assistent), Seiten `page_*.py`, `wizard.py` (Einrichtung), `update_dialog.py`, `widgets.py` (Bausteine, **Tabellen** `make_table`/`SortItem`), `theme.py` (dunkles QSS) |

Wichtige Entwurfsentscheidungen:

- **Engine und Oberfläche sind getrennt.** Die Engine läuft in einem Thread; die Oberfläche liest `engine.state` per Timer und
  Ereignisse aus `engine.events`. Widgets nur im GUI-Thread anfassen (`MainWindow.post(callable)` für Rückrufe aus Threads).
- **Statistik zählt alle Versuche gleich** (der Eigentümer bekommt pro Welle Belohnungen). Kein „erfolgreich/Fehlversuch“ mehr
  als Hauptsicht; „bis zum Ende geschafft“ ist nur Nebeninfo. In der CSV heißt ein nicht komplett beendeter Lauf weiter
  `abgebrochen` (Abwärtskompatibilität). Zeit-/Raten-Kennzahlen nutzen nur **gemessene** Dauern; geschätzte (Notiz
  „geschätzt“, Anzeige mit `~`) fließen nicht ein.
- **Wellenzähler-Suchbereich ist groß** (Standard obere Mitte), das Programm findet den Zähler selbst. Frühere enge Bereiche
  funktionierten im Fenstermodus (Titelleiste) nicht.
- **Performance ist Absicht:** kein OCR ohne Bildänderung, Zwischenspeicher, adaptiver Takt, Tesseract mit einem Thread,
  niedrige Prozesspriorität. Leerlauf-Last in Messungen etwa 1–4 % eines Kerns. Nicht verschlechtern.
- **Raid-Statistik je Raid oder gesamt** (Auswahlfeld „Alle Raids (gesamt)“). Der Eigentümer will **keine vielen
  Einzelprofile**, nur je gespieltem Raid einen Eintrag mit Referenzbildern.
- **Zeitangaben:** Die Engine nutzt `time.monotonic()` für Takt/Dauer; in Tests wird die Uhr teils künstlich gesetzt.

## Release-Ablauf (GitHub, Repository `Justiiiiiin/AnimeAstral`)

1. Änderungen committen und pushen (Standard-Branch `main`).
2. Version veröffentlichen: Release mit Tag `vX.Y.Z` anlegen **oder** Actions → „Release“ → *Run workflow* mit `X.Y.Z`.
3. `.github/workflows/release.yml` (Windows-Runner): Version aus Tag/Eingabe, `pip install`, **Tesseract per Chocolatey**,
   Tests, `tools/write_build_info.py` (schreibt Version, `GITHUB_REPO`, `RPC_CLIENT_ID` aus Repository-Variable),
   PyInstaller (`build_exe.py --no-zip`, bündelt Tesseract), **Inno Setup** (`installer/AnimeAstralMonitor.iss`),
   SHA256-Datei, Veröffentlichung per `softprops/action-gh-release`.
4. Ergebnis: `AnimeAstralMonitor-Setup-X.Y.Z.exe` + `SHA256SUMS.txt` am Release. Installierte Programme prüfen beim Start
   (nach ~6 s, höchstens alle 6 h) `releases/latest` und aktualisieren sich leise (`/SILENT … /relaunch=1`).
   Nur Installer-Builds haben eine Update-Quelle (`build_info.GITHUB_REPO` leer = keine Prüfung).

Die Versionsnummer steht in `astral_monitor/version.py` und wird vom Build aus dem Tag überschrieben. Aufwärts zählen.
`update.py`/`update.bat` sind ein **veralteter lokaler Updater** (ZIP-Weg) und können entfernt werden, sobald der
GitHub-Weg bestätigt ist; `build_exe.bat` baut lokal.

## Ungetestet – bitte als Erstes prüfen

Stand 06.10.2026 (Claude Code unter Windows): Punkte 1, 3 und 5 erledigt, 2 und 4 teilweise.

1. ~~**Gesamte Oberfläche**~~ – geprüft (alle Seiten bei 1180×800 und 980×680, Assistent, Update-Dialog, Statistik:
   sortieren, Spaltenbreite merken über `ui_state.json`). Behoben: Statistik- und Raids-Seite zu breit bei kleinem Fenster,
   Hauptknöpfe in Karten unlesbar (QSS-Regel `QFrame#card QWidget` überschrieb `QPushButton#primary`), Update-Dialog zeigt
   Versionshinweise jetzt als Markdown mit lesbaren Links. Offen: echte Klick-Bedienung durch den Eigentümer.
2. **Fenster-Aufnahme (`WgcSource`):** Läuft mit echtem Roblox stundenlang stabil (v0.5.0, `windows-capture` 2.0.1,
   Lesezeit ~81 ms). Verdecktes Fenster liefert weiter Bilder und Werte; minimiert kommen keine Bilder (wird gemeldet,
   danach automatisch weiter). Beim Umschalten (F11) kommen kurz eingefrorene Bilder – dabei wurde „25“ als „29“
   gelesen und als Fehlversuch gezählt; behoben im Tracker (kleiner Rückgang = Korrektur statt Neustart).
   Prüfhilfe: `_shots/capture_probe.py` (nicht im Repo). Fenstermodus ↔ Vollbild (F11): Erkennung läuft in beiden.
   **Gelber Rahmen:** erscheint trotz `draw_border=False` (wird von `windows-capture` 2.0.1 fehlerfrei angenommen, von
   Windows 11 25H2 aber ignoriert). Kein Code-Fehler; Windows erlaubt das Ausblenden nur per Datenschutz-Einstellung.
   Rahmen ist nur optisch, nicht in den Bildern.
3. ~~**GitHub-Bau**~~ – Lauf vom 05.10.2026 erfolgreich, Release `v0.5.0` mit Installer + `SHA256SUMS.txt`.
4. **Installer:** Kompiliert und installiert (v0.5.0 läuft). Noch offen: echtes Update über die App auf eine neuere
   Version inkl. `/relaunch=1`.
5. ~~**Mitgeliefertes Tesseract**~~ – findet `tessdata` neben sich ohne `TESSDATA_PREFIX`, TSV-Ausgabe funktioniert.
6. **Discord-Profilstatus (`presence.py`):** Nur gegen Attrappen getestet. Nötig ist eine **Discord-Anwendungs-ID** (Entwicklerportal
   → Anwendung → „Application ID“, nicht geheim). Sie fehlt noch: bitte als Repository-Variable `RPC_CLIENT_ID` oder fest in
   `build_info.py` eintragen. Als Bild dient das Roblox-Spiel-Thumbnail (öffentliche Roblox-Schnittstellen `universes/v1/places/…/universe`
   und `thumbnails.roblox.com/v1/games/icons`); Standardlink `rpc_game_link` zeigt auf Place `9797806474`, **die richtige
   Spielnummer ist unbestätigt** (das Spiel hat mehrere Seiten, u. a. `10502841145`).
7. **Formatierung der Statusnachricht:** Die Beschreibung nutzt Discord-Markdown (`## Überschrift`, `-# kleine Zeile`). Ob Discord das
   in Embeds so darstellt, ist nicht bestätigt.
8. **Hotkeys (`RegisterHotKey`)** und das Tray-/Autostart-Verhalten (Tray gibt es noch nicht).
9. **Disconnect-Erkennung:** nur mit einem selbst gezeichneten Dialog getestet; echte Roblox-Dialoge prüfen
   (Fehlercodes u. a. 277, 278 = 20 Min. inaktiv, 279, 288, 273, 267, 268).

## Bekannte Schwächen / Ideen

- Die Wellenauswertung erwartet alle Läufe als „Wave x/y“ mit erlaubter Gesamtzahl (Einstellung `allowed_totals`, Standard `100`).
  **Defense-Modi und andere Raids** könnten ein anderes Format haben – der Eigentümer liefert Screenshots; dann Parser/Suche erweitern.
- Plausibilitätsfilter im Tracker: erlaubter Sprung `UP_BASE + UP_PER_SECOND * Sekunden` (4 + 1,5/s). Passt zu etwa einer Welle alle
  3,7 s. Schnellere Modi könnten Anpassung brauchen (Simulationen setzen `UP_BASE` hoch, weil sie 100× schneller laufen).
- Raid-Erkennung per Referenzbild vertrug in Tests andere Auflösungen, aber nur mit **einer** echten Map. Mit mehreren echten Raids prüfen.
- **Geplant für Version 1.0** (Vorschläge, noch nicht gebaut; Reihenfolge nach Wunsch des Eigentümers klären):
  Dauerlauf-Test (Nacht) und Absturz-Neustart, Tray-Symbol + Autostart, Hilfe-Seite im Programm, Push per ntfy, Lizenz/„Über“-Seite,
  Browser-Ansicht im Heimnetz (Handy), Deutsch/Englisch, Tages-/Wochenziele, Zeitraum-Vergleich, Excel-Export/Backup,
  mehrere Roblox-Fenster. Eine Android-App ist **nicht** sinnvoll möglich (Windows-Aufnahme, MediaProjection-Einschränkungen).
- Der Eigentümer legt Wert auf: **modernes, sauberes, dunkles Design**, kurze verständliche Erklärungen, geringe Systemlast,
  ruhige Discord-Kanäle (eine Statusnachricht statt vieler Meldungen; Pings nur bei echten Problemen).

## Arbeitsweise

- **Python auf dem Rechner des Eigentümers ist die Microsoft-Store-Version:** Sie leitet `%APPDATA%` um (sieht dort eine
  alte Kopie statt der echten Daten) und scheitert bei globalem `pip install` an langen Pfaden. Deshalb immer die
  virtuelle Umgebung `.venv` im Projektordner nutzen (`.venv\Scripts\python.exe`).

- Vor größeren Änderungen einen Git-Stand anlegen. Nach jeder Änderung `python -m unittest discover -s tests` ausführen.
- Neue Logik möglichst **ohne Qt** halten, damit sie in `tests/` prüfbar bleibt (Muster: `tests/_env.py` setzt `ASTRAL_DATA_DIR`).
- Einstellungen erweitern: Feld in `Settings` + Seite `load()`/`apply()` + bei Bedarf Migration über `settings_version`.
- Neue Discord-Ereignisse in `settings.EVENT_DEFS` eintragen (erscheinen automatisch unter „Meldungen“).
- Keine Webhook-URL, keine Tokens, keine persönlichen Daten in Code oder Repository. Die Update-Prüfung akzeptiert nur Downloads
  aus dem eigenen Repository und prüft SHA256 – diese Schutzmaßnahmen nicht aufweichen.
- Nutzer-Screenshots/Logs: `Einstellungen → Diagnose-Paket erstellen` erzeugt eine ZIP (ohne Webhook) mit Protokoll, Wertverlauf,
  Systeminfo und Fensterbild – ideal zur Fehlersuche.
