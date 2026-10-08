# CLAUDE.md – Übergabe für Claude Code

Dieses Dokument beschreibt das Projekt **Anime Astral Monitor**, damit du ohne Einarbeitung weiterarbeiten kannst.
Der Entwicklungsverlauf stammt aus einem langen Chat (Claude im Browser), in dem **nichts unter Windows, nichts mit echtem
Roblox, keine echte Oberfläche und kein echter GitHub-Lauf** getestet werden konnte. Alles Genannte unter „Ungetestet“
ist deshalb die wichtigste Arbeit für dich: **selbst ausführen, Fehler lesen, beheben.**

## Was das Programm ist

Windows-Desktop-App (Python 3.12, PySide6), die das Roblox-Fenster des Spiels **Anime Astral Simulator** per Bildaufnahme
überwacht. Sie liest den Wellenzähler („Wave 12/100“) und die Quest-Liste per Texterkennung, zählt **Versuche und Wellen**,
führt Statistiken je Raid und meldet per **Discord-Webhook** (Raid-Ende mit Screenshot, Alarme, eine sich selbst
aktualisierende Statusnachricht, Statistik-Karten). Sie greift nicht in den Roblox-Prozess ein und **sendet keine
Eingaben an Roblox – einzige Ausnahme ist das optionale Anti-AFK** (`antiafk.py`, Standard aus, Schalter in der
Kopfzeile, auf ausdrücklichen Wunsch des Eigentümers 06.10.2026): alle N Minuten Roblox kurz nach vorne, einmal
Leertaste, zurück. Roblox nimmt Tasten nur im Vordergrund an (getestet: `PostMessage` an das Hintergrundfenster wirkt
nicht). **Seit 0.9.5-beta.2** nach dem AutoHotkey-Skript des Eigentümers: alle Roblox-Clients (Prozess
RobloxPlayerBeta.exe), minimierte wiederherstellen und offen lassen (sonst keine Aufnahme), 4× Esc + 1× Esc direkt ans
Fenster, danach `EmptyWorkingSet` auf Roblox; **kein Warten** auf Ruhe des Nutzers, nur Pause während das Makro
klickt. **Seit 0.9.5-beta.1 zweite Ausnahme: Automatik (Beta)** (`automation.py`, Standard aus, Karte unter
Einstellungen → Roblox, Einschalten nur nach Warnung zu den Roblox-Regeln; Wunsch des Eigentümers 07.10.2026, Ziel
1.0.0): öffnet Menüs anhand der Oberflächen-Karte (`uimap.py` + `astral_monitor/uimap/`, Erkennung `vision.py`) –
Teleporter auf, per Mausrad zur Welt scrollen, Symbol klicken, Titel prüfen; Pets-Roll „Auto!“ drücken und das
Menü gleich wieder schließen (Auto-Roll läuft im Hintergrund weiter – nie auf das Rollen warten). **Oberfläche seit
0.9.9-beta.7:** keine eigene Makro-Karte mehr; `ui/macro_controller.py` (`MainWindow.macro`) hält Karte, Navigator und
das **Makro-Protokoll** (`ui/macro_log.py`, kompakt mit Uhrzeit, unter Einstellungen → Makro; auf der Startseite nur mit
`settings.macro_log_home`). „Makro erlauben“, Stopp und Erkunden: Einstellungen → Makro. Startseite: links die
**Farm-Routine** (bis beta.6 „Makro-Warteschlange“; `ui/macro_queue_card.py`, „Was?/Wo?“ + Optionen im festen Stapel –
Breite springt nicht; `Navigator.run_queue`, laufender Schritt über `Navigator.queue_pos`; Aufgaben
`automation.TASK_KINDS`, gespeichert in `settings.macro_queue`/`macro_loop`; während „Pause“ ist `_ACTIVE` aus, damit
das Anti-AFK laufen kann), rechts Live, Quests und ganz unten **„Automatisch abholen“** (`ui/extras_card.py`).
Schritte: **Raid / Defense farmen** (Create/Join, Ende nach N Raids / M Min. / nie, Auto Leave ab Welle; startet die
Überwachung selbst, setzt den Raid der Statistik; schon im selben Raid = nicht neu starten; **verlassen nur, wenn
danach ein anderer Raid/Modus folgt** – `automation.leave_before`), Auto Roll, Progressions: Auto All, Pause.
Automatisch abholen (Schalter, keine Schritte): **Fixer Gigs** (Claim, „Send Pets“ → Pets-Fenster nach unten, eins
der letzten `GIGS_PETS` Pets – Raster `automation.pet_tiles` – anklicken = losgeschickt, kein Bestätigen, je Gig einzeln; jede Karte einzeln gelesen
`automation.gig_cards`: Art QUICK 20 Min./STANDARD 1 Std./BIG JOB 3 Std. ist zufällig, Restzeit genau per
Ziffern-Lesung `_read_timer`, `gig_next_due`; „FINISH NOW“ kostet Währung – nie drücken), **Gilden-Missionen**
(Guild → Missions → Personal + Guild Weekly „Claim“, einmal am Tag `GUILD_EVERY`), Progressions: Auto All als Knopf
für einmal. Zeiten überdauern Neustarts (`extras_state.json`). Fehler: einmal wiederholen, dann überspringen;
Nutzer-Abbruch (`UserStop`) beendet die Routine. Unbekannte Schritte: Bild `debug/makro_*.jpg`.
Ältere Aufgaben (raid_farm/leave/create/join/navigate/close) laufen weiter, sind aber nicht mehr wählbar
(„Hin navigieren“/„Menü schließen“ entfernt – nur Test). Recherche InformaalFrog/Faxi: siehe Memory.
**Erkunden (seit 0.9.7-beta.1, `explorer.py`, Wissen in `knowledge.py`):** übernimmt Roblox ein paar Minuten, geht
den Teleporter durch, öffnet in neuen Welten und bei Symbolen ohne Fenster jedes Symbol einmal, ordnet es ein
(Titel + gelesene Wörter), schließt (X, Vorlage-Close oder „Close“/„Exit“ bei ganzen Bildschirmen) – **seit
0.9.9-beta.7 zuerst die Welten** (Pets, Crafting, Raids, Gachas haben Vorrang, Eigentümer), danach die
Knöpfe am Bildschirmrand (`extra.hud`, feste Lage mit Bildprüfung). Nie Aktions-Knöpfe klicken
(`knowledge.ACTION_WORDS`). Ergebnis: `uimap_local.json` im Datenordner (mitgelieferte Karte hat Vorrang) +
`explore/<zeit>/report.json` mit Bildern. Fehlen der Karte Welt-Fenster (z. B. nach „Gelerntes vergessen“), holt
`explorer.restore_from_reports` sie beim Start aus den Berichten zurück (nur Berichte nach `explore/forgot_at`). **„Nicht drücken“** (`extra.avoid` in der Karte, Bildvergleich
`vision.same_icon`): Gates (W5) und Totenkopf/MaxTac Call (W21) sind zeitbasierte Modi – Klick schließt den Teleporter.
**Raid-Steuerung (seit 0.9.7-beta.2):** Zahnrad oben rechts neben Welle/Timer (`uimap_static/raid_gear.png`, Suche in
mehreren Größen) öffnet „Auto Retry“/„Auto Leave“ + Feld „Wave N“; Schalterzustand an der Farbe des Knopfs (größter
grüner vs. rosa Fleck, `vision.toggle_state` – „Wave cleared!“-Meldungen liegen oft darüber). Mit Auto Retry an kann
man nicht verlassen: `_leave_raid` = Auto Retry aus, dann „LEAVE!“. Aufgabe „Raid farmen“ wartet auf N Raid-Enden der
Überwachung (`engine.stats.snapshot().total_attempts`). Kopfzeile: Start/Stopp/Pause/Status nur als gezeichnete
Symbole (`widgets.media_icon`, `discord_icon`), Countdowns klein über den Schaltern (`MainWindow._stacked`).
**Startseite seit 0.9.5-beta.4:** kein Titel/Fenster-Info/Raid-Auswahl; Start/Pause/Status als Knöpfe links in der
Kopfzeile (`MainWindow._mount_controls`); Ereignisse als Debug-Karte unter Einstellungen → Programm
(`ui/events_card.py`, gesammelt in `MainWindow.event_log`). Die Raid-Auswahl kommt neu (Eigentümer ändert das). Eingaben per
SendInput nur mit Roblox im Vordergrund, Not-Aus bei Mausbewegung/Esc. **Kein Laufen/Teleportieren** (TELEPORT!-Knöpfe
werden nicht benutzt – Wunsch des Eigentümers). Darüber hinaus nichts automatisieren, ohne zu fragen.
**Oberflächen-Karte:** gepflegt im privaten Entwickler-Werkzeug (`_dev/calibrate.py`: Aufnahme, Baum, Vorlagen),
für das Programm ausgegeben mit `_dev/library.export_for_program()` -> `astral_monitor/uimap/` (index.json + nur die
nötigen Erkennungsbilder als JPG/PNG). Verknüpfung „Knopf öffnet Fenster“ über `opened_by_id` (Kennung), nicht über
den Namen – „Crafting Unit“, „Progression“ gibt es in jeder Welt. Menüs im Teleporter-Rahmen erkennt man am rosa X
oben rechts und am Titel im schrägen Banner; Sonder-Menüs (Pets-Roll) über eine Vorlage mit Erkennungsmerkmal.
**Privater Server** (`roblox_join.py`): Teilen-Link oder klassischer Link -> `roblox://`-Protokoll-Link, `os.startfile`
(kein Browser, kein Cookie/Passwort). Der Link bleibt lokal (Diagnose schwärzt ihn) – nie ins Repo.
**Auto-Rejoin** (`rejoin.py`, Standard aus, Schalter in der Kopfzeile, Wunsch des Eigentümers 06.10.2026): liest alle
3 s nur neue Zeilen der Client-Protokolle (`%LOCALAPPDATA%\Roblox\logs\*_Player_*.log`): „! Joining game … place N“ =
im Spiel; „Disconnection Notification. Reason: N“ u. ä. = verloren, außer 264/273/276/285 (selbst verlassen / anderes
Gerät) – dann nie zurückholen; Prozess weg ohne „verlassen“ = Absturz. Nach 15 s (Teleports treten selbst neu bei)
Client beenden und neu beitreten (Link, sonst öffentlich dieselbe Place), 5 Versuche mit Pausen. Derselbe Thread
liefert den **Disconnect-Alarm des Wächters** (läuft, solange Wächter oder Auto-Rejoin an ist; Alarm erst nach der
Wartezeit, einmal je Abbruch). Die frühere OCR-Suche nach dem Dialog in der Fenstermitte (`disconnect_check`) ist seit
0.6.4 entfernt. Hinweis: Startet man einen Beitritt, während ein Client läuft, übernimmt der laufende Client den
Beitritt (getestet).
**Oberfläche:** Seiten mit Einstellungen setzen `SAVES = True` und bekommen von `main_window._with_savebar` eine feste
Speichern-Leiste unten (keine eigenen Speichern-Knöpfe, keine verschachtelten Scrollbereiche). Bausteine in
`widgets.py`: `section()`, `columns()` (Karten nebeneinander), `form_grid()`, `short_field()`; Zahlenfelder sind auf
`FIELD_WIDTH` begrenzt. Uptime-Intervall steht unter „Meldungen“ (nur ohne Live-Status aktiv); `total_offset` wird
weiter angewendet, hat aber kein Eingabefeld mehr.

Benutzer ist der Eigentümer (Deutsch, Windows 11); Freunde sollen es später ebenfalls nutzen („full release 1.0.0“).
**Oberfläche und Meldungen gibt es auf Deutsch und Englisch** (Einstellungen → Oberfläche, gilt nach Neustart):
Texte stehen im Code auf Deutsch und laufen durch `tr()` aus `i18n.py` (Platzhalter: `tr("Welle {wave}", wave=3)`);
Texte in Listen/Konstanten mit `N_()` markieren und bei der Anzeige `tr()` anwenden; Zahlen mit `i18n.dec()`/
`thousands()`. Englisch in `i18n_en.py`. **`tests/test_i18n.py` schlägt fehl, wenn ein Text keine Übersetzung hat**
– neue Texte also immer mit `tr()` schreiben und übersetzen. Protokoll (monitor.log), Code, Kommentare und Doku
bleiben Deutsch, Bezeichner englisch.

## Befehle

```
pip install -r requirements.txt           # Windows; windows-capture nur dort
python run.py                             # Programm starten (Oberfläche)
.venv\Scripts\python.exe -m unittest discover -s tests -v   # 63 Tests, ohne Qt/Tesseract/Netz lauffähig
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
| `tracker.py` | Zustandsautomat der Wellen: Lauf-Start/-Ende, Neustart-Erkennung (2 passende Lesungen), **Plausibilitätsfilter** (unmögliche Sprünge nach oben werden ignoriert), Raid-Ende bei 100/100 (fest) |
| `quests.py` | Quest-Liste (Titel + Fortschritt) per OCR, `QuestTracker` in `tracker.py` |
| `stats.py` | `StatsStore` (CSV `raid_history.csv`), alle Kennzahlen, Verteilung, Trend, Rekorde |
| `profiles.py` | Raids als Namensliste (anlegen, umbenennen, löschen) – seit 0.9.0 ohne Einstellungen je Raid |
| `guard.py` | Wächter: Roblox-Prozess, Stillstand, RAM/CPU (Disconnects: `rejoin.py`) |
| `status.py` | **Live-Statusnachricht**: eine Discord-Nachricht, die per `PATCH` bearbeitet wird; „unten neu senden“ = `DELETE` + `POST` |
| `discord_client.py`, `messages.py` | Versand (eigener Thread, Wiederholung bei 429) und Embeds |
| `report_card.py` | Statistik-Karte als PNG (Pillow, kein Qt) |
| `presence.py` | Discord-Profilstatus (pypresence), Spiel-Thumbnail von Roblox als Bild |
| `updater.py` | Update-Prüfung über GitHub-Releases, Download mit SHA256-Prüfung, leiser Installer-Start |
| `ocr.py` | Tesseract-Anbindung; **mitgeliefertes** Tesseract (`tesseract/` neben der EXE) hat Vorrang |
| `uimap.py`, `vision.py`, `automation.py` | Automatik (Beta): Oberflächen-Karte lesen, Zeilen/Menüs erkennen, Wege gehen (eigener Thread, eigene OCR-Instanz); Oberfläche `ui/macro_controller.py`, `macro_queue_card.py`, `extras_card.py`, `macro_log.py` |
| `settings.py` | `Settings`-Dataclass (JSON), `Roi`, Ereignis-Definitionen, Migration über `settings_version` |
| `debuglog.py` | Debug-Reiter: `BUFFER` hängt nur bei `settings.debug_view` (Standard aus) am Logger, lädt das Ende von monitor.log vor; Anzeige `ui/events_card.py` |
| `search.py` | Einstellungssuche: Umlaute/Bindestriche egal, kleine Tippfehler erlaubt (difflib); Strg+F = `MainWindow.open_search` |
| `i18n.py`, `i18n_en.py` | Sprache: `tr()`, `N_()`, Zahlenformat; englische Texte |
| `hotkeys.py`, `winapi.py`, `imaging.py`, `diagnostics.py`, `app_paths.py` | Hilfen (globale Hotkeys per `RegisterHotKey`, Fenstersuche per ctypes, Bildverarbeitung, Diagnose-ZIP, Pfade) |
| `ui/` | PySide6-Oberfläche: `main_window.py` (Seitenleiste, Hotkeys, Update-Start, Assistent), Seiten `page_*.py`, `wizard.py` (Einrichtung), `update_dialog.py`, `widgets.py` (Bausteine, **Tabellen** `make_table`/`SortItem`), `theme.py` (dunkles QSS) |

Wichtige Entwurfsentscheidungen:

- **Oberfläche skaliert mit der Fenstergröße** (Entwurf 1180 × 800 = Faktor 1, 0,7–1,3): `theme.set_scale()` rechnet
  alle px/pt im Stylesheet um; feste Größen im Code nur über `theme.track_margins/_spacing/_min_height/_fixed_width …`
  (nie direkt `setMinimumHeight(320)` o. Ä.). Das Hauptfenster setzt den Faktor 150 ms nach dem Größenändern.
  Faktor = **UI-Größe** (`ui_zoom` 50–200 %) × optional Fensteranpassung (`ui_auto_fit`), siehe `theme.factor_for`.
- **Auto-Start** (`automonitor.py`, Schalter in der Kopfzeile, Standard aus): reine Entscheidungslogik
  (`AutoMonitor.tick` → start/pause/resume/stop), Spielzustand aus `rejoin.py` (Log-Thread läuft auch nur für
  Auto-Start). Nur **Übergänge** lösen aus: selbst gestoppt im Spiel → bleibt aus bis zum nächsten Betreten; selbst
  gestartet außerhalb → wird nicht gestoppt; Disconnect → Pause (gleiche Session), Verlassen → Stopp nach 20 s.
  Ausgeführt in `MainWindow._auto_tick` (läuft auch, wenn das Fenster im Tray ist).
- **Geheimnisse** (`secure.py`): `settings.json` speichert `SECRET_FIELDS` und Favoriten-Links mit Windows-DPAPI
  („dpapi:…“, `Settings.to_dict(protect=True)`); alte Klartext-Dateien laden weiter, auf fremdem PC werden die Werte
  leer. PC-Wechsel: Export/Import als `.astralsettings` mit Passwort (AES-256-GCM, scrypt; `cryptography` gepinnt,
  im Build als hidden import). Kein Server/Konto – bewusst.
- **Erklärtexte gehören in ⓘ** (`Card(title, info)`, `InfoButton`), nicht als Fließtext auf die Seite;
  auf den Seiten nur Bedienelemente und Statuszeilen (Wunsch des Eigentümers: weniger überladen).
- **Design „Night City“** (seit 0.9.9-beta.7, Standard; Migration settings_version 12 stellt Nebula um): passend zum Spiel – violett-schwarz, Neon-Gelb/Magenta, Kartenränder Magenta → Cyan, kantiger; Vorlage `_NIGHTCITY` = Nebula + Überschreibungen, nur dunkel.
- **Design „Nebula“** (seit 0.7.0, bis 0.9.9-beta.6 Standard): aus dem Logo abgeleitet; Layout-Flag `rail` = schmale Symbolleiste (76 px, Logo oben, Namen als Tooltip), Status als Pille in der Kopfzeile, Hinweise oben (`top_toast`). Vorlage = Astral + Überschreibungen (`_NEBULA`). Logo: `tools/make_icon.py`.
- **Seit 0.9.0 – Erkennung ohne Einstellungen** (Wunsch des Eigentümers): keine Seiten „Erkennung“ und „Raids“
  mehr (Symbolleiste: Überwachung, Statistik, Meldungen, Einstellungen; `PAGE_*`-Konstanten in `main_window.py`).
  `settings.fix_detection()` setzt beim Laden immer die festen Werte (`FIXED_DETECTION`: Raid-Ende bei 100/100 mit
  einer Lesung, Fenster-Aufnahme, Standardbereiche) – die Felder bleiben nur für Downgrades in der Datei.
  Bereiche kommen aus `astral_monitor/regions.json` (fehlt sie: `DEFAULT_*_ROI`). **Kein „heißer“ Takt** mehr:
  `PRESETS[…]["interval"]` (Standard 0,5 s; 100/100 steht bis ~1 s da). **Raid-Meldungen ohne Screenshot.**
  Entwickler-Werkzeug (privat, `_dev/`, per `.git/info/exclude` nie im Repo): `_dev/calibrate.py` zeigt das
  Roblox-Fenster mit den Bereichen, legt sie fest und schreibt `regions.json`; Bildbibliothek (`_dev/library/`,
  Raids/Upgrade-Shops mit Namen und Position) als Vorarbeit für die Automatik in 1.0.0.
- **Seit 0.8.0:** Einstellungen mit Reitern (Abschnitte = `section()`-Überschriften, `_assign_groups`) und Suche;
  Saison-Designs mit Deko (`ui/seasonal.py`, gemalt von `ui/backdrop.py`, Karten leicht durchscheinend über
  `cardGlass`-Tokens, 15 Bilder/s nur bei sichtbarem Fenster); Kürbisnacht-Überraschung (`ui/spooky.py`, höchstens
  1×/Std.); Roblox-Profil (`roblox_profile.py`, nur öffentliche API, Name in `SECRET_FIELDS`); Statistik-Werte per
  `@_cached` bis zum nächsten Raid zwischengespeichert (gemessen mit 120 000 Raids); „Neu“-Punkte je Version in
  `ui/newdots.py` (`NEW_FEATURES` bei jedem Release pflegen). Wellenzahlen immer genau, andere Mengen mit k
  (`messages.fmt_k`). Glas-/Mica-Effekt wurde verworfen: Qt zeichnet Fenster mit Windows-Rahmen deckend.
- **Designs** (`theme.DESIGNS`, Einstellungen → Darstellung, `ui_design`/`ui_mode`): „Astral“ (seit 0.6.5, vorher Standard:
  Symbole aus der Windows-Symbolschrift, Zahnrad unten links, Überblendung beim Seitenwechsel, Hell/Dunkel/Wie Windows)
  und „Klassisch“ (seit 0.5.0, nur dunkel, unverändert). **Alte Designs nie löschen** – neues Design = neuer Eintrag mit
  `since`-Version. Farben nur als `@token` in den Vorlagen bzw. `theme.color("token")` im Code (keine festen Hex-Werte in
  den Seiten), sonst stimmen Hell-Modus und Designwechsel nicht. Umschalten wirkt sofort (`MainWindow.set_appearance`,
  `theme.on_change` für gezeichnete Inhalte). Prüfbilder aller Varianten: `_shots/shots.ps1`, Umschalt-Test:
  `_shots/look_test.py`.
- **Infobereich (Tray):** Fenster schließen = im Hintergrund weiterlaufen (Einstellung `close_to_tray`), Beenden über
  das Tray-Menü. Ein zweiter Programmstart schreibt `show.request` in den Datenordner und beendet sich; die laufende
  Instanz zeigt dann ihr Fenster. Kein Autostart (Wunsch des Eigentümers).
- **Wand:** `StatsStore.wall(raid)` – die Welle, an der ≥ 60 % der letzten 20 Versuche eines Raids enden (z. B. Boss);
  angezeigt in Überwachung/Statistik/Statusnachricht, Meldung „Wand durchbrochen“ (Ereignis `wall`).
- **Engine und Oberfläche sind getrennt.** Die Engine läuft in einem Thread; die Oberfläche liest `engine.state` per Timer und
  Ereignisse aus `engine.events`. Widgets nur im GUI-Thread anfassen (`MainWindow.post(callable)` für Rückrufe aus Threads).
- **Es gibt keine Fehlversuche** (seit 0.7.1, Wunsch des Eigentümers): In Anime Astral scheitert ein Raid nicht, man kommt
  nur unterschiedlich weit, und jede Welle gibt Belohnungen. Jedes Raid-Ende läuft durch `Engine._finish_run` (gleiche
  Meldung „Raid beendet · Welle X/100“, Raid-Nummer = alle Versuche). Neue CSV-Zeilen haben immer `ok`; alte Zeilen mit
  `abgebrochen` zählen genauso. Keine Erfolgsquote, kein „bis zum Ende geschafft“ wieder einführen. Zeit-/Raten-Kennzahlen nutzen nur **gemessene** Dauern; geschätzte (Notiz
  „geschätzt“, Anzeige mit `~`) fließen nicht ein.
- **Wellenzähler-Suchbereich ist groß** (Standard obere Mitte), das Programm findet den Zähler selbst. Frühere enge Bereiche
  funktionierten im Fenstermodus (Titelleiste) nicht.
- **Performance ist Absicht** (Ziel: auch schwache PCs): kein OCR ohne Bildänderung, Zwischenspeicher, adaptiver Takt,
  niedrige Prozesspriorität. Gemessen 06.10.2026 mit echtem Roblox (Raid läuft): **~1,6 % eines Kerns, ~120 MB privat**
  (vorher 6,6 % + Tesseract-Prozesse, 706 MB). Die Hebel – nicht zurückbauen:
  - WGC mit `minimum_update_interval` (halber „heißer“ Takt): ungedrosselt liefert Windows bis 60 Bilder/s, die Bibliothek
    kopiert jedes in den RAM (~7 % CPU allein dafür).
  - Tesseract **direkt über `libtesseract`** (ctypes, `ocr._TessLib`), Modell bleibt geladen: ~5 statt ~65 ms je Lesung,
    keine Prozessstarts. Fallback `tesseract.exe` über pytesseract, falls die DLL nicht ladbar ist.
  - `astral_monitor/__init__.py` setzt `OPENBLAS_NUM_THREADS=1` usw. **vor** dem numpy-Import (OpenBLAS legt sonst je Kern
    Puffer an: 257 statt 32 MB), `cv2.setNumThreads(1)`.
  - Oberfläche zeichnet nicht, solange das Fenster minimiert ist.
  - Arbeitsspeicher: `winapi.trim_memory()` 30 s nach Start, alle 10 Min. und beim Minimieren. Der Working Set enthält
    sonst Start-Reste und geteilte Seiten von Grafiktreibern (WGC lädt AMD- und NVIDIA-Treiber, ~370 MB) und Schriften;
    gemessen 178 MB → dauerhaft ~50 MB (eigener Anteil/USS ~36 MB). Die Anzeige „Dieses Programm“ zeigt den Working Set.
  - Update-Downloads werden beim Start gelöscht (`updater.cleanup_downloads`), sonst blieben ~60 MB liegen.
- **Raid-Statistik je Raid oder gesamt** (Auswahlfeld „Alle Raids (gesamt)“). Raids sind nur noch **Namen**
  (`profiles.py`; verwaltet unter Einstellungen → Roblox, `ui/raids_card.py`). Der aktuelle Raid wird auf der Startseite per
  Dropdown gewählt (`settings.current_raid`, `Engine.set_current_raid` – gilt sofort, auch für den laufenden Versuch).
  Umbenennen (`Engine.rename_raid`) benennt Ordner, CSV-Verlauf und Auswahl mit um; Löschen behält die Statistik.
- **Server-Favoriten** (`settings.server_favorites`, max. 20; `private_server_link` = der markierte, gilt für
  „Server beitreten“ und Auto-Rejoin). Änderungen werden sofort gespeichert (`MainWindow.set_server_favorites`), nicht
  über die Speichern-Leiste. Kopfzeilen-Knopf mit Pfeil-Menü und Tray-Untermenü. Diagnose schwärzt die Links.
- **Zeitangaben:** Die Engine nutzt `time.monotonic()` für Takt/Dauer; in Tests wird die Uhr teils künstlich gesetzt.
- **Seit 0.9.7-beta.4/0.9.8 – Seiten ohne Scrollen** (Wunsch des Eigentümers): Seitenkopf `widgets.page_header`
  (Titel + ⓘ + Bedienelemente in einer Zeile), Statistik-Listen als Reiter, Meldungen zweispaltig, Einstellungen mit
  Reitern Roblox/Überwachung/Darstellung/Programm/Debug (`_assign_groups` packt Kartenreihen in Widgets, damit
  ausgeblendete Reihen keinen Abstand lassen). Prüfen: `_shots/pages_fit.py [breite hoehe]` (meldet Scrollbedarf
  je Seite/Reiter). Kopfzeilen-Knöpfe aktualisiert `MonitorPage.refresh_controls` auf jeder Seite.
- **Erkennung (0.9.7-beta.4):** `WaveTracker` wertet „4“ nach „53/54“ (vordere Ziffer verdeckt, `_cut_digits`) erst
  nach `CUT_CONFIRM` s als Neustart; solange das Makro klickt (`antiafk._macro_busy`), ruft die Engine nur
  `tracker.hold()` auf und liest keine Quests. Makro-Bilderkennung: Zeilensuche nur im Streifen `X_BAND` um den
  Zeilenanfang (~4× schneller), Titel werden vor der Texterkennung gerade gedreht (`read_title`), Wörter einer
  Titelzeile verbunden (`_join_words`); Prüfung `_shots/title_regress.py` (136 echte Titel), Laufzeit
  `_shots/bench_vision.py`. RapidOCR wurde verglichen und verworfen (nicht genauer, 18× langsamer, +60 MB).

## Release-Ablauf (GitHub, dieses Repository – der Build liest den Namen selbst aus `github.repository`)

1. Änderungen committen und pushen (Standard-Branch `main`).
2. Version veröffentlichen: Release mit Tag `vX.Y.Z` anlegen **oder** Actions → „Release“ → *Run workflow* mit `X.Y.Z`.
3. `.github/workflows/release.yml` (Windows-Runner): Version aus Tag/Eingabe, `pip install`, **Tesseract per Chocolatey**,
   Tests, `tools/write_build_info.py` (schreibt Version, `GITHUB_REPO`, `RPC_CLIENT_ID` aus Repository-Variable),
   PyInstaller (`build_exe.py --no-zip`, bündelt Tesseract), **Inno Setup** (`installer/AnimeAstralMonitor.iss`),
   SHA256-Datei, Veröffentlichung per `softprops/action-gh-release`.
4. Ergebnis am Release: `AnimeAstralMonitor-Setup-X.Y.Z.exe`, `files-X.Y.Z.json` (Prüfsumme jeder Programmdatei),
   `AnimeAstralMonitor-Update-X.Y.Z.zip` (nur die seit der vorigen Version geänderten Dateien, `tools/make_patch.py`)
   und `SHA256SUMS.txt` über alle. Installierte Programme prüfen beim Start (nach ~6 s, höchstens alle 6 h)
   `releases/latest`. **Kleines Update:** passt das Paket zum installierten Stand (`files.json` im Programmordner,
   `updater.plan_patch`), werden nur diese Dateien geladen, einzeln per Prüfsumme kontrolliert und nach dem Beenden von
   einem PowerShell-Skript ausgetauscht (`updater.APPLY_SCRIPT`: sichert vorher, stellt bei Fehler alles wieder her,
   startet neu). Sonst (Version übersprungen, Ordner nicht beschreibbar …) der komplette Installer leise
   (`/SILENT … /relaunch=1`). Nur Installer-Builds haben eine Update-Quelle (`build_info.GITHUB_REPO` leer = keine Prüfung).
   Damit Pakete klein bleiben, baut CI mit **festen Versionen** aus `requirements-build.txt` (bewusst anheben).
   Programmgröße: `build_exe.py` packt von Tesseract nur die tatsächlich geladenen DLLs ein und entfernt unbenutzte
   Qt-/OpenCV-/Pillow-Teile (`PRUNE`, mit Prüfung, dass keine verbleibende Datei sie braucht): 380 → 228 MB installiert.

Die Versionsnummer steht in `astral_monitor/version.py` und wird vom Build aus dem Tag überschrieben. Aufwärts zählen.
`build_exe.bat` baut lokal (der alte ZIP-Updater `update.py` ist seit 0.7.1 entfernt).

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
4. ~~**Installer**~~ – Update 0.5.0 → 0.5.1 über die App inkl. automatischem Neustart erfolgreich (06.10.2026).
5. ~~**Mitgeliefertes Tesseract**~~ – findet `tessdata` neben sich ohne `TESSDATA_PREFIX`, TSV-Ausgabe funktioniert.
6. **Discord-Profilstatus (`presence.py`):** Jeder Nutzer trägt seine **eigene** Anwendungs-ID in den Einstellungen ein.
   **Keine persönlichen IDs/Nummern ins Repository oder in den Build** (Wunsch des Eigentümers; das Repo ist öffentlich und
   wird an Freunde weitergegeben) – die Repository-Variable `RPC_CLIENT_ID` bleibt leer. Spiel: Place `102072869879193` = Universe `10502841145`
   „[CYBER] Anime Astral Simulator“ (aus dem laufenden Roblox-Client gelesen); der alte Standard `9797806474` war ungültig und
   wird per Migration (settings_version 6) ersetzt. Verbindung zur Discord-App und Thumbnail-Abruf funktionieren, im
   Profil des Eigentümers war die Aktivität beim ersten Test aber **nicht sichtbar** – Ursache noch offen.
7. ~~**Formatierung der Statusnachricht**~~ – `##` und `-#` werden in Embeds korrekt dargestellt (Screenshot des Eigentümers).
8. ~~**Hotkeys**~~ – funktionieren laut Eigentümer. Tray/Autostart gibt es weiterhin nicht.
9. **Disconnect-Erkennung** (seit 0.6.4 über das Roblox-Protokoll): Grund 276 („anderes Gerät“) und 285 (selbst
   verlassen) an echten Protokollen geprüft. Echte Kicks (277, 278 = 20 Min. inaktiv, 279, 267, 268) noch nicht live
   erlebt – sie landen als „verloren“ und lösen Alarm/Rejoin aus.

## Bekannte Schwächen / Ideen

- Die Wellenauswertung erwartet alle Läufe als „Wave x/y“ mit erlaubter Gesamtzahl (Einstellung `allowed_totals`, Standard `100`).
  **Defense-Modi und andere Raids** könnten ein anderes Format haben – der Eigentümer liefert Screenshots; dann Parser/Suche erweitern.
- Plausibilitätsfilter im Tracker: erlaubter Sprung `UP_BASE + UP_PER_SECOND * Sekunden` (4 + 1,5/s). Passt zu etwa einer Welle alle
  3,7 s. Schnellere Modi könnten Anpassung brauchen (Simulationen setzen `UP_BASE` hoch, weil sie 100× schneller laufen).
- **Keine Raid-Erkennung per Bild mehr** (seit 0.6.4, Wunsch des Eigentümers): Die Kamera im Spiel ist frei
  einstellbar und zeigt zum Ressourcensparen manchmal nichts – der ORB-Vergleich (bis 0.6.3) war dadurch unzuverlässig.
  Nicht wieder einbauen, ohne zu fragen. Die Wellenzähler-Texterkennung bleibt natürlich.
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
