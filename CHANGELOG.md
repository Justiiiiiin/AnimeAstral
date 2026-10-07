# Änderungen

Neueste Version oben. Kurze Stichpunkte, keine Erklärungen (die stehen im Programm hinter dem ⓘ).
Der Abschnitt einer Version wird beim Veröffentlichen automatisch als Versionshinweis übernommen
(`tools/release_notes.py`) und ist im Programm unter Einstellungen → Updates → „Alle Versionen“ lesbar.

## 0.9.5-beta.4

### ✨ Neu (Beta)
- Makro-Warteschlange: Aufgaben nacheinander, auf Wunsch in Schleife
- Aufgaben: Menü öffnen, Pets rollen, Menü schließen, Warten
- Während „Warten“ läuft das Anti-AFK weiter

### 🔧 Verbessert
- Start/Stopp, Pause und Status-Knopf links oben in der Kopfzeile
- Startseite ohne Titel, Fenster-Info und Raid-Auswahl
- Ereignisse als Debug-Karte unter Einstellungen → Programm

## 0.9.5-beta.3

### 🐞 Behoben (Beta)
- Makro scrollt im Teleporter (Maus vor dem Mausrad bewegen)
- Bewegt das Mausrad nichts, zieht das Makro den Scrollbalken
- Makro-Schritte stehen im Protokoll (Fehlersuche)

## 0.9.5-beta.2

### ✨ Neu (Beta)
- „Automatik“ heißt jetzt Makro und sitzt auf der Startseite
- Pets rollen: nach „Auto!“ schließt das Menü gleich wieder
- Anti-AFK neu: alle Roblox-Fenster, 4× Esc, ohne Wartezeit
- Minimiertes Roblox bleibt danach offen (Erkennung läuft)
- Anti-AFK leert danach den Roblox-Arbeitsspeicher

### 🔧 Verbessert
- Startseite neu: links Makro + Ereignisse, rechts Live + Quests
- Ereignisse und Quests kompakt, je eine Zeile
- Live-Erkennung ohne Vorschaubild
- Größeres Fenster: Startseite ohne Scrollen

## 0.9.5-beta.1

### ✨ Neu (Beta)
- Automatik (Beta) unter Einstellungen → Roblox, standardmäßig aus
- Menüs per Karte öffnen: Teleporter, zur Welt scrollen, Symbol
- Pets rollen: Roll-Menü der Welt öffnen und „Auto!“ drücken
- Not-Aus: Maus bewegen oder Esc
- Kein Laufen, kein Teleportieren

## 0.9.1

### 🐞 Behoben (Hotfix)
- Raids mit 30, 50 oder bis 2000 Wellen werden wieder erkannt
- Modi ohne Gesamtzahl („Wave 542“) werden erkannt und gezählt

## 0.9.0

### 🔧 Verbessert
- Erkennung fest eingebaut – keine Bereiche mehr einzustellen
- Immer Fenster-Aufnahme, Raid-Ende bei 100/100
- Gleichmäßiger Takt (alle 0,5 s) statt „heißem“ Takt
- Größerer Quest-Bereich: alle Quests samt Fortschritt
- Raids verwalten unter Einstellungen → Roblox
- Nur noch vier Seiten in der Symbolleiste
- Alle Verbesserungen aus 0.8.1-beta.1

### 🗑️ Entfernt
- Seite „Erkennung“ (Bereiche, Auslöser, Bestätigungen)
- Seite „Raids“ mit Auslöser und Notiz je Raid
- Screenshots bei Raid-Meldungen
- Alte Funktionen gibt es weiter in 0.8.1 und älter

## 0.8.1-beta.1

### 🔧 Verbessert
- Start schneller: Seiten werden erst beim ersten Öffnen gebaut
- Design- und Farbwechsel etwa doppelt so schnell
- Statistik rechnet im Hintergrund – nie mehr Hänger
- Auswertungen bis zu 160× schneller, Verlauf lädt ~4× schneller
- Statistik-Karten werden im Hintergrund gezeichnet
- Saison-Deko flüssiger (20 Bilder/s) ohne Mehrlast
- Seitenwechsel knackiger

## 0.8.0

### ✨ Neu
- Einstellungen mit Reitern und Suchfeld
- Dein Roblox-Profil: Avatar in Seitenleiste und auf Karten
- Persönliche Rekorde in der Statistik
- Statistik archivieren und neu beginnen
- Designs „Bubble“ (rund) und „OLED“ (echtes Schwarz)
- Saison-Designs Silvester, Kirschblüte und Sommer
- Saison-Deko: Blätter, Kürbisse, Schnee, Feuerwerk, Blüten
- Kürbisnacht-Überraschung (abschaltbar)
- Nachrichtenstil „Kompakt“ für Discord
- Akzentfarbe aus dem Hintergrundbild
- „Was ist neu“ nach Updates und „Neu“-Punkte
- „Fehler melden“ ganz unten in den Einstellungen

### 🔧 Verbessert
- Statistik auch mit großem Verlauf flüssig
- Versuche und Quest-Ziele kurz mit k (Wellen bleiben genau)
- Zuletzt benutzte Raids stehen oben
- Kräftigere Saison-Farben
- Leere Bereiche mit kleiner Illustration
- Logo-Animation beim Start zuverlässig sichtbar

## 0.7.5.1

### 🐞 Behoben
- Windows zeigt an Verknüpfungen das neue Logo
- Quest-Titel vollständiger (Text nach der Zahl bleibt)
- Zerteilte Raid-Namen in Quests repariert („Conv oy“)
- Quest-Fortschritt „1/90“ wird erkannt
- Quests in derselben Reihenfolge wie im Spiel

## 0.7.5

### ✨ Neu
- Monatsrückblick als Karte (speichern oder an Discord)
- Wochenüberblick: Farmzeit je Tag (Statistik → Woche)
- Raid-Meldungen als Tages-Beitrag im Forum-Kanal
- Eigene Embed-Farbe je Ereignis
- Server-Favoriten per Code mit Freunden teilen
- Akzentfarbe frei wählbar
- Eigenes Hintergrundbild (abdunkelbar)
- Saison-Designs „Kürbisnacht“ und „Frost“
- Logo-Animation beim Start (abschaltbar)
- Abgesicherter Start (Umschalt halten)
- Beta-Kanal für Vorabversionen

### 🔧 Verbessert
- Wellenzahl färbt sich nahe der Bestwelle
- Schalter „Animationen reduzieren“
- Speicher-Übersicht mit Aufräumen
- Diagnose-Paket ohne IDs, Links und Benutzername

## 0.7.1

### 🔧 Verbessert
- Kein „Fehlversuch“ mehr: jeder Raid zählt normal
- Raid-Meldung zeigt die erreichte Welle
- Live-Status neu: Fortschrittsbalken, Symbole, Logo
- Logo als Profilbild der Discord-Nachrichten
- Programm aufgeräumt (alter Updater entfernt)

## 0.7.0

### ✨ Neu
- Design „Nebula“: schmale Symbolleiste, Status-Pille
- Auto-Start: Überwachung startet/stoppt mit Anime Astral
- Einstellungen exportieren/importieren (mit Passwort)
- Alle Versionshinweise im Programm lesbar
- Ältere Version installieren (Downgrade)
- Neues Logo

### 🔧 Verbessert
- Webhook & Server-Links verschlüsselt gespeichert
- Erklärungen hinter ⓘ statt als Text
- Versionshinweise als Text im Update-Fenster

## 0.6.5

### ✨ Neu
- Design „Astral“ mit Symbolen und Zahnrad
- Hell-, Dunkel- oder Windows-Modus
- UI-Größe 50–200 %
- Altes Design als „Klassisch“ wählbar

### 🔧 Verbessert
- Statistik übersichtlicher, Diagramm lesbar

## 0.6.4

### ✨ Neu
- Server-Favoriten (anlegen, ändern, löschen)
- Raid-Auswahl auf der Startseite
- Raids umbenennen

### 🔧 Verbessert
- Einstellungen neu sortiert, feste Speichern-Leiste
- Disconnect-Alarm genauer (ohne Bilderkennung)

### 🗑️ Entfernt
- Raid-Erkennung per Bild

## 0.6.3

### ✨ Neu
- Auto-Rejoin nach Disconnect, Kick oder Absturz

## 0.6.2

### ✨ Neu
- Privaten Server ohne Browser betreten

## 0.6.1

### ✨ Neu
- Anti-AFK per Schalter

### 🔧 Verbessert
- Raid-Liste kompakter (max. 8 sichtbar)

## 0.6.0

### ✨ Neu
- Wand-Erkennung (Boss-Welle)
- Tray-Symbol: läuft im Hintergrund
- Englische Oberfläche
- Oberfläche skaliert mit dem Fenster

### 🔧 Verbessert
- Weniger Arbeitsspeicher

## 0.5.2

### 🔧 Verbessert
- Kleine Updates (nur geänderte Dateien)
- Weniger CPU und Speicher

## 0.5.1

### 🔧 Verbessert
- Jeder Versuch zählt gleich
- Sortierbare Tabellen
- Eigene Discord-ID für den Profilstatus

### 🐞 Behoben
- Kurzer Zählerrückgang zählt nicht mehr als Neustart

## 0.5.0

### ✨ Neu
- Erste Version: Wellenzähler, Statistik, Discord-Meldungen, Updates
