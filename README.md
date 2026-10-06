# Anime Astral Monitor

Begleit-Programm für **Anime Astral Simulator** (Roblox): zählt deine Raids und Wellen, meldet alles an Discord und
hält dich beim AFK-Farmen im Spiel – mit Live-Statistik, Auto-Rejoin und automatischen Updates.

## Download und Installation

1. Auf der Seite **[Releases](../../releases/latest)** die Datei `AnimeAstralMonitor-Setup-….exe` laden und starten.
2. Windows meldet bei unbekannten Herausgebern evtl. „Der Computer wurde durch Windows geschützt“:
   **Weitere Informationen → Trotzdem ausführen**.
3. Beim ersten Start führt dich der Einrichtungsassistent in einer Minute durch alles (Roblox, Zähler, Discord).

Es muss nichts weiter installiert werden (Texterkennung ist enthalten). Windows 10/11, 64 Bit.

## Funktionen

- **Wellenzähler** („Wave 12/100“): jeder Raid zählt mit der erreichten Welle, Meldung mit Screenshot an Discord
- **Statistik** je Raid und gesamt: Wellen pro Stunde, Endwellen, Trend, Rekorde, „Wand“, **Statistik-Karte** zum Teilen
- **Live-Status** in Discord: eine Nachricht, die sich selbst aktualisiert
- **Privater Server ohne Browser**, Server-Favoriten, **Auto-Rejoin** nach Disconnect, Kick oder Absturz
- **Auto-Start** der Überwachung beim Betreten des Spiels, optionales **Anti-AFK**
- **Wächter:** Alarm bei Absturz, Disconnect, Stillstand, hohem Speicherverbrauch
- Quests, Hotkeys, Tray-Symbol, Discord-Profilstatus, Deutsch/Englisch
- **Monatsrückblick** und Wochenüberblick, Server-Favoriten per Code teilen, Tages-Beiträge im Forum-Kanal
- Designs **Nebula**, Astral, Klassisch und Saison-Designs, hell/dunkel, Akzentfarbe, eigenes Hintergrundbild,
  UI-Größe 50–200 %
- **Automatische Updates** (meist nur wenige MB), alle Versionshinweise im Programm, Downgrade möglich

## Datenschutz

Das Programm sendet Daten nur an die Discord-Webhook-URL, die du selbst einträgst, und (für Updates) an GitHub.
Einstellungen und Verlauf liegen lokal in `%APPDATA%\AnimeAstralMonitor`; Webhook-URL und Server-Links sind dort mit
deinem Windows-Konto verschlüsselt. Für einen PC-Wechsel lassen sich die Einstellungen mit Passwort exportieren.

## Für Entwickler

```
pip install -r requirements.txt
python run.py                       # starten
python -m unittest discover -s tests -v
python build_exe.py                 # EXE lokal bauen (oder build_exe.bat)
```

Neue Version: `astral_monitor/version.py` anheben, Abschnitt `## X.Y.Z` in `CHANGELOG.md` ergänzen (kurze
Stichpunkte), Tag `vX.Y.Z` pushen – GitHub baut Programm, Installer, Update-Paket und Versionshinweis automatisch.
Logo: `python tools/make_icon.py`.

Hinweis: Dies ist ein inoffizielles Fan-Werkzeug und steht in keiner Verbindung zu Roblox oder dem Spiel. Ob das Auslesen
von Bildschirminhalten mit den Regeln des Spiels vereinbar ist, kann nicht garantiert werden – Nutzung auf eigene Verantwortung.
