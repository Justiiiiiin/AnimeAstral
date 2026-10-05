# Anime Astral Monitor

Überwacht dein Roblox-Fenster (Anime Astral Simulator) und meldet Raids, Fehlversuche, Quests und Alarme an Discord –
mit Live-Statistik, Statistik-Karten und automatischen Updates. Das Programm **liest nur Bilder aus** und sendet keine
Eingaben an das Spiel.

## Download und Installation

1. Auf der Seite **[Releases](../../releases/latest)** die Datei `AnimeAstralMonitor-Setup-….exe` laden und starten.
2. Windows meldet bei unbekannten Herausgebern evtl. „Der Computer wurde durch Windows geschützt“:
   **Weitere Informationen → Trotzdem ausführen**.
3. Beim ersten Start führt dich der Einrichtungsassistent in einer Minute durch alles (Roblox, Zähler, Discord).

Es muss nichts weiter installiert werden (Texterkennung ist enthalten). Windows 10/11, 64 Bit.

## Funktionen

- **Raid-Erkennung** am Wellenzähler („Wave 12/100“), Auslöser z. B. bei 99/100, Screenshot und Meldung nach Raid-Ende
- **Fehlversuche/Neustarts** werden mitgezählt (Anzahl, Ø Dauer, erreichte Welle, Erfolgsquote)
- **Statistik je Raid und gesamt**, Zeiträume, Verteilung der Endwellen, Trend, Rekorde, **Statistik-Karte** zum Teilen
- **Live-Status** in Discord: eine Nachricht, die sich selbst aktualisiert – per Knopf/Hotkey ganz nach unten neu sendbar
- **Quests** (Fortschritt in Programm und Discord), **Raid-Erkennung per Referenzbild** (Profile teilbar)
- **Wächter:** Alarm bei Roblox-Absturz, Disconnect, Stillstand, hohem Speicherverbrauch
- Hotkeys, Fenster-Aufnahme auch bei verdecktem Roblox, **Discord-Profilstatus** (optional)
- **Automatische Updates** über GitHub

## Datenschutz

Das Programm sendet Daten ausschließlich an die Discord-Webhook-URL, die du selbst einträgst, sowie (nur für die
Update-Prüfung) an GitHub. Einstellungen und Verlauf liegen lokal in `%APPDATA%\AnimeAstralMonitor`.
Ein Screenshot wird nur an deinen eigenen Webhook gesendet.

## Für Entwickler

```
pip install -r requirements.txt
python run.py                       # starten
python -m unittest discover -s tests -v
python build_exe.py                 # EXE bauen (Tesseract muss installiert sein, wird mitgepackt)
```

Neue Version veröffentlichen: siehe [docs/GITHUB_ANLEITUNG.md](docs/GITHUB_ANLEITUNG.md). Der GitHub-Build erzeugt
Programm, Installer und Prüfsumme automatisch, sobald ein Release mit Tag `vX.Y.Z` angelegt wird.

Hinweis: Dies ist ein inoffizielles Fan-Werkzeug und steht in keiner Verbindung zu Roblox oder dem Spiel. Ob das Auslesen
von Bildschirminhalten mit den Regeln des Spiels vereinbar ist, kann nicht garantiert werden – Nutzung auf eigene Verantwortung.
