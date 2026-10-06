# GitHub einrichten – Schritt für Schritt (einmalig, ca. 10 Minuten)

Ziel: Das Programm liegt in deinem Repository **AnimeAstral**; bei jeder neuen Version baut GitHub automatisch den
Installer, und das Programm bei dir und deinen Freunden aktualisiert sich selbst.

> Das Repository sollte **öffentlich** sein (Einstellungen → ganz unten „Change visibility“). Nur dann kann das Programm
> ohne Anmeldung nach Updates fragen. Im Quellcode steht keine Webhook-URL und kein Passwort.

## 1. Dateien hochladen

1. ZIP entpacken. Du erhältst den Ordner `AnimeAstral`.
2. Auf GitHub dein Repository öffnen → **Add file → Upload files**.
3. Im Windows-Explorer **alles im Ordner** markieren (Strg+A) und in das Browserfenster ziehen.
   Der Ordner `.github` ist versteckt: Explorer → **Ansicht → Anzeigen → Ausgeblendete Elemente** aktivieren.
4. Warten, bis die Liste vollständig ist (rund 60 Dateien), unten **Commit changes**.
5. **Prüfen:** Im Repository muss es den Ordner `.github/workflows` mit `release.yml` geben. Fehlt er (Browser verlieren
   Punkt-Ordner manchmal): **Add file → Create new file**, als Namen `.github/workflows/release.yml` eintippen
   (die Schrägstriche erzeugen die Ordner), den Inhalt aus der Datei `docs/release.yml.txt` hineinkopieren, **Commit**.

*Mit Git:* `git clone <repo-url>`, Inhalt des Ordners hineinkopieren, `git add .`, `git commit -m "Version 0.5.0"`, `git push`.

## 2. Actions erlauben

1. Reiter **Actions** öffnen. Falls GitHub fragt, die Workflows zu aktivieren: **I understand my workflows, go ahead and enable them**.
2. **Settings → Actions → General → Workflow permissions → „Read and write permissions“ → Save.**

## 3. Erste Version veröffentlichen (baut den Installer)

1. Rechts im Repository auf **Releases → Create a new release**.
2. **Choose a tag** → `v0.5.0` eintippen → **Create new tag: v0.5.0 on publish**.
3. **Publish release.**
4. Reiter **Actions** → Lauf „Release“. Er dauert etwa 10–15 Minuten. Grüner Haken = fertig.
5. Unter **Releases** hängen jetzt `AnimeAstralMonitor-Setup-0.5.0.exe` und `SHA256SUMS.txt`.

Die Versionsnummer kommt aus dem Tag – im Code musst du nichts ändern.

## 4. Installer testen

1. Setup herunterladen und starten. Bei „Windows hat den Computer geschützt“: **Weitere Informationen → Trotzdem ausführen**.
2. Installiert wird nach `%LOCALAPPDATA%\Programs\Anime Astral Monitor` (keine Administratorrechte nötig), mit Startmenü-Eintrag
   und optionaler Desktop-Verknüpfung. Deine bisherigen Einstellungen und der Verlauf bleiben erhalten
   (liegen in `%APPDATA%\AnimeAstralMonitor`).
3. Den alten selbst gebauten Programmordner kannst du danach löschen.

## 5. Automatisches Update testen

1. Ändere etwas im Repository (oder lade die nächste Programmversion hoch) und veröffentliche ein Release `v0.5.1` (Schritt 3).
2. Öffne die **installierte** Version 0.5.0 → **Einstellungen → Updates → „Jetzt nach Updates suchen“**.
   Es erscheint „Version 0.5.1 ist verfügbar“ mit den Versionshinweisen → **Jetzt aktualisieren**.
3. Das Programm lädt den Installer, prüft die Prüfsumme, installiert leise und startet neu.

Automatisch fragt das Programm beim Start (nach ca. 6 Sekunden), höchstens alle 6 Stunden. „Diese Version überspringen“ merkt sich die Wahl.
Die selbst gebaute Version (`build_exe.bat`) hat keine Update-Quelle; nur Installer-Builds von GitHub aktualisieren sich.

## 6. Freunde

Schick ihnen den Link `https://github.com/<DEIN-NAME>/AnimeAstral/releases/latest`. Profile (Referenzbilder) lassen sich unter
**Raids → Exportieren/Importieren** als Datei teilen.

## 7. Discord-Profilstatus (optional)

1. <https://discord.com/developers/applications> → **New Application** → Name z. B. „Anime Astral Monitor“.
2. **Application ID** kopieren (General Information).
3. Im Programm: **Einstellungen → Discord-Profilstatus** die ID eintragen und aktivieren. Jeder Nutzer trägt seine **eigene**
   ID ein – im Repository und im Build ist absichtlich keine hinterlegt. Kein Bot, keine Server-Einladung nötig.
4. Die Discord-Desktop-App muss auf dem PC laufen; unter Discord → **Einstellungen → Aktivitäts-Privatsphäre** muss das
   Teilen der Aktivität eingeschaltet sein. Als Bild wird automatisch das Spiel-Thumbnail von Roblox verwendet.

## 8. Wenn etwas rot wird

**Actions → den roten Lauf öffnen → den roten Schritt aufklappen** → Text kopieren und mir schicken.

## 9. Lizenz

Ohne Lizenzdatei gilt „alle Rechte vorbehalten“ – Freunde dürfen das Programm dann streng genommen nur nutzen, nicht weitergeben.
Wähle bei Bedarf: **Add file → Create new file → `LICENSE`** → „Choose a license template“ (z. B. MIT).
