# CLAUDE.md – handover for Claude Code

This document describes the project **Anime Astral Monitor** so you can keep working without ramp-up.
The early development happened in a long chat (Claude in the browser) where **nothing could be tested on Windows, with
real Roblox, a real UI or a real GitHub run**. Everything listed under “Untested” is therefore the most important work
for you: **run it yourself, read the errors, fix them.**

## What the program is

Windows desktop app (Python 3.13, PySide6) that watches the Roblox window of the game **Anime Astral Simulator** via
screen capture. It reads the wave counter (“Wave 12/100”) and the quest list with text recognition, counts **attempts
and waves**, keeps statistics per raid and reports via **Discord webhook** (raid end, alerts, a self-updating status
message, stats cards). It doesn't touch the Roblox process and **sends no input to Roblox – the only exception is the
optional Anti-AFK** (`antiafk.py`, off by default, switch in the header, explicit wish of the owner 06.10.2026): every N
minutes bring Roblox to the front briefly, press a key, go back. Roblox only accepts keys in the foreground (tested:
`PostMessage` to the background window has no effect). **Since 0.9.5-beta.2**, following the owner's AutoHotkey script:
all Roblox clients (process RobloxPlayerBeta.exe), restore minimized ones and leave them open (otherwise no capture),
4× Esc + 1× Esc directly to the window, then `EmptyWorkingSet` on Roblox; **no waiting** for the user to be idle, only
paused while the macro clicks. **Since 0.9.5-beta.1 a second exception: the macro (beta)** (`automation.py`, off by
default, enabled only after a warning about the Roblox rules; owner's wish 07.10.2026, goal 1.0.0): opens menus using
the UI map (`uimap.py` + `astral_monitor/uimap/`, recognition `vision.py`) – open the teleporter, scroll to the world
with the mouse wheel, click the icon, check the title; press the pets roll “Auto!” and close the menu right away
(auto roll keeps running in the background – never wait for the rolling). **UI since 0.9.9-beta.7:** no separate macro
card anymore; `ui/macro_controller.py` (`MainWindow.macro`) holds the map, navigator and the **macro log**
(`ui/macro_log.py`, compact with times, under Settings → Macro; on the start page only with `settings.macro_log_home`).
“Allow macro”, stop and explore: Settings → Macro. Start page: on the left the **farm routine** (until beta.6 “macro
queue”; `ui/macro_queue_card.py`, “What?/Where?” + options in a fixed stack – the width doesn't jump;
`Navigator.run_queue`, running step via `Navigator.queue_pos`; tasks `automation.TASK_KINDS`, saved in
`settings.macro_queue`/`macro_loop`; during “Pause” `_ACTIVE` is off so the Anti-AFK can run), on the right live,
quests and at the very bottom **“Auto collect”** (`ui/extras_card.py`).
Steps: **Farm raid / defense** (Create/Join, end after N raids / M min. / never, Auto Leave from wave; starts the
monitoring itself, sets the raid for the statistics; already in the same raid = don't restart; **leave only if a
different raid/mode follows** – `automation.leave_before`), Auto Roll, Pause (Progressions only as a button under
“Auto collect”; old steps keep working).
Auto collect (switches, not steps): **Fixer Gigs** (Claim, “Send Pets” → scroll the pets window down, click one of the
last `GIGS_PETS` pets – grid `automation.pet_tiles` – clicking = sent, no confirmation, one gig at a time; the three
slots are read on their own at fixed places in the window (`GIG_SLOT_BOXES`, `automation.gig_cards`: running / done /
needs a pet / empty – owner 09.10.2026: running gigs whose header wasn't read had been missed); the kind QUICK 20
min/STANDARD 1 h/BIG JOB 3 h is random, remaining time read exactly from the digits `_read_timer`, empty slots wait
for “NEW GIGS IN …” (`gig_refresh_box`), next visit `gig_next_due` = whichever comes first; the pets list bottom is
detected with `scrolled_box` and two still reads; “FINISH NOW” costs currency – never press it), **guild missions**
(Guild → Missions → Personal + Guild Weekly “Claim”, once per **PC day** – `guild_next_time`, state `guild_day`; nothing
claimed = try again after `GUILD_RETRY` 3 h), Progressions: Auto All as a one-off button. Times survive restarts
(`extras_state.json`). Errors: retry once, then skip; a user stop (`UserStop`) ends the routine. Unknown steps: image
`debug/makro_*.jpg`. Older tasks (raid_farm/leave/create/join/navigate/close) still run but can't be chosen anymore
(“Navigate there”/“Close menu” removed – test only). Research InformaalFrog/Faxi: see memory.
**Explore (since 0.9.7-beta.1, `explorer.py`, knowledge in `knowledge.py`):** takes over Roblox for a few minutes, goes
through the teleporter, opens every icon once in new worlds and for icons without a window, classifies it (title +
words read), closes it (X, template close or “Close”/“Exit” for full screens) – **since 0.9.9-beta.7 the worlds first**
(pets, crafting, raids, gachas have priority, owner), then the buttons at the screen edge (`extra.hud`, fixed position
with an image check). Never click action buttons (`knowledge.ACTION_WORDS`). Result: `uimap_local.json` in the data
folder (the bundled map takes precedence) + `explore/<time>/report.json` with images. If the map lacks world windows
(e.g. after “Forget what was learned”), `explorer.restore_from_reports` restores them from the reports at startup (only
reports after `explore/forgot_at`). **“Don't press”** (`extra.avoid` in the map, image comparison
`vision.same_icon`): gates (W5) and the skull/MaxTac Call (W21) are time-based modes – a click closes the teleporter.
Scroll probing: `PROBE_NOTCHES` with undo (otherwise the camera zooms into first person), at most `PROBE_MAX` spots
with content; checked windows only scroll marked lists. W3/W9 have no slot 8 (`EMPTY_SLOTS`).
**Raid controls (since 0.9.7-beta.2):** the gear at the top right next to wave/timer (`uimap_static/raid_gear.png`,
searched at several sizes, clicked only once the wave counter is visible and the position is stable – `_stable_gear`)
opens “Auto Retry”/“Auto Leave” + field “Wave N”; the switch state comes from the button color (largest green vs. pink
blob, `vision.toggle_state` – “Wave cleared!” messages often lie on top). With Auto Retry on you can't leave:
`_leave_raid` = Auto Retry off, then “LEAVE!”. The task “Farm raid” waits for N raid ends of the monitoring
(`engine.stats.snapshot().total_attempts`). Header: start/stop/pause/status only as drawn icons
(`widgets.media_icon`, `discord_icon`), countdowns small above the switches (`MainWindow._stacked`).
**Start page since 0.9.5-beta.4:** no title/window info; start/pause/status as buttons on the left of the header
(`MainWindow._mount_controls`); events as a debug card under Settings → Program (`ui/events_card.py`, collected in
`MainWindow.event_log`). Input via SendInput only with Roblox in the foreground, emergency stop on mouse movement/Esc.
**No walking/teleporting** (TELEPORT! buttons are not used – owner's wish). Beyond that, automate nothing without
asking.
**UI map:** maintained in the private developer tool (`_dev/calibrate.py`: capture, tree, templates), exported for the
program with `_dev/library.export_for_program()` -> `astral_monitor/uimap/` (index.json + only the needed recognition
images as JPG/PNG). The link “button opens window” goes through `opened_by_id` (an ID), not the name – “Crafting
Unit”, “Progression” exist in every world. Menus in the teleporter frame are recognized by the pink X at the top right
and the title in the slanted banner; special menus (pets roll) via a template with a recognition feature.
**Private server** (`roblox_join.py`): share link or classic link -> `roblox://` protocol link, `os.startfile` (no
browser, no cookie/password). The link stays local (diagnostics black it out) – never into the repo.
**Auto-rejoin** (`rejoin.py`, off by default, switch in the header, owner's wish 06.10.2026): every 3 s reads only new
lines of the client logs (`%LOCALAPPDATA%\Roblox\logs\*_Player_*.log`): “! Joining game … place N” = in the game;
“Disconnection Notification. Reason: N” etc. = lost, except 264/273/276/285 (left yourself / other device) – then never
bring back; process gone without “left” = crash. After 15 s (teleports rejoin by themselves) end the client and rejoin
(link, otherwise publicly the same place), 5 tries with pauses. The same thread delivers the **guard's disconnect
alert** (runs while the guard or auto-rejoin is on; alert only after the waiting time, once per drop). The earlier OCR
search for the dialog in the window center (`disconnect_check`) was removed in 0.6.4. Note: starting a join while a
client is running makes the running client take over the join (tested).
**Discord bot** (`discord_bot.py`, `ui/bot_bridge.py`, off by default): every user creates their own bot; slash
commands /status, /start, /stop, /pause, /screenshot, /raid, /macro, /antiafk, /autorejoin, /join, /pc, /help. Command
names are fixed English words (Discord doesn't translate them); descriptions go through `tr()`.
**UI:** pages with settings set `SAVES = True` and get a fixed save bar at the bottom from
`main_window._with_savebar` (no own save buttons, no nested scroll areas). Building blocks in `widgets.py`:
`section()`, `columns()` (cards side by side), `form_grid()`, `short_field()`; number fields are limited to
`FIELD_WIDTH`. The uptime interval is under “Alerts” (only active without live status); `total_offset` is still
applied but has no input field anymore. Settings tabs: the group keys are the English section names (“Roblox”,
“Macro”, “Discord bot”, “Monitoring”, “Appearance”, “Program”, “Debug”), shown via `tr()` – `newdots` uses `tab:<key>`.

The user is the owner (German, Windows 11); friends and international users should use it too (“full release 1.0.0”).
**The UI and messages exist in English and German** (Settings → Appearance → Sprache / Language, applies after a
restart; **English is the default since 0.9.9**). Texts are written **in English** in the code and go through `tr()`
from `i18n.py` (placeholders: `tr("Wave {wave}", wave=3)`); mark texts in lists/constants with `N_()` and apply `tr()`
when displaying; numbers with `i18n.dec()`/`thousands()`. The German translations are in `i18n_de.py`
(`DE = {English: German}`). Always write new texts with `tr()`. **Betas are English only** (owner 09.10.2026): add
German (or other languages) only for a full release – `tests/test_i18n.py` skips the “missing”/“stale” checks while
`version.py` contains “-beta”; for a full version it fails if a text has no German translation or `i18n_de.py` has
stale entries, so translate everything before tagging it. Placeholder and “no umlauts in keys” checks always run.
Code, comments, docs, the log (monitor.log) and identifiers are English. Exceptions (data, don't
translate): stored values like the raid placeholder `stats.UNKNOWN = "Unbekannt"` and result `"abgebrochen"` in old
CSV rows, the map kinds “Knopf”/“Fenster / Bereich”, name suffixes “… Fenster” of older explore runs, the debug
image names `debug/makro_*.jpg`. Tests that check German output set the language per module (`setUpModule`);
`tests/_env.py` sets English.

## Commands

```
pip install -r requirements.txt           # Windows; windows-capture only there
python run.py                             # start the program (UI)
.venv\Scripts\python.exe -m unittest discover -s tests -v   # 188 tests, run without Qt/Tesseract/network
python -m astral_monitor.selftest image.png   # check the recognition on a screenshot (needs Tesseract)
python build_exe.py [--no-zip] [--no-bundle-tesseract]   # EXE (PyInstaller, folder variant) + bundle Tesseract
```

Data folder at runtime: `%APPDATA%\AnimeAstralMonitor` (the environment variable `ASTRAL_DATA_DIR` overrides it, the
tests use that). In it: `settings.json`, `raid_history.csv`, `monitor.log`, `profiles/`, `status_message.json`,
`ui_state.json`, `rpc_icon.json`, `updates/`, `debug/`, `explore/`, `uimap_local.json`, `extras_state.json`.

## Architecture (package `astral_monitor/`)

| File | Purpose |
|---|---|
| `engine.py` | Central monitoring loop (own thread), holds the state (`EngineState`), connects all parts, event queue to the UI |
| `capture.py` | Image sources: `WgcSource` (Windows Graphics Capture via the package `windows-capture`, works with a covered window) and `ScreenSource` (fallback). Delivers only the requested crops |
| `wave.py` | **Find and read** the wave counter: searches “Wave x/y” in the search area by itself (Tesseract with word positions), remembers the place, then reads only a narrow area; cache per image |
| `tracker.py` | State machine of the waves: run start/end, restart detection (2 matching reads), **plausibility filter** (impossible jumps up are ignored), raid end at 100/100 (fixed) |
| `quests.py` | Quest list (title + progress) via OCR, `QuestTracker` in `tracker.py` |
| `stats.py` | `StatsStore` (CSV `raid_history.csv`), all metrics, raids per day, trend, records |
| `profiles.py` | Raids as a list of names (add, rename, delete) – since 0.9.0 without settings per raid |
| `guard.py` | Guard: Roblox process, stall, RAM/CPU (disconnects: `rejoin.py`) |
| `status.py` | **Live status message**: one Discord message edited via `PATCH`; “resend at the bottom” = `DELETE` + `POST` |
| `discord_client.py`, `messages.py` | Sending (own thread, retry on 429) and embeds |
| `report_card.py` | Stats card as PNG (Pillow, no Qt) |
| `presence.py` | Discord profile status (pypresence), game thumbnail from Roblox as the image |
| `updater.py` | Update check via GitHub releases, download with SHA256 check, silent installer start |
| `ocr.py` | Tesseract binding; the **bundled** Tesseract (`tesseract/` next to the EXE) takes precedence |
| `uimap.py`, `vision.py`, `automation.py`, `explorer.py`, `knowledge.py`, `review.py`, `autosuggest.py` | Macro (beta): read the UI map, recognize rows/menus, walk paths (own thread, own OCR instance), explore, check findings; UI `ui/macro_controller.py`, `macro_queue_card.py`, `extras_card.py`, `macro_log.py`, `explore_review.py` |
| `discord_bot.py` | Own Discord bot for remote control; handler in `ui/bot_bridge.py` |
| `settings.py` | `Settings` dataclass (JSON), `Roi`, event definitions, migration via `settings_version` |
| `debuglog.py` | Debug tab: `BUFFER` only hangs on the logger with `settings.debug_view` (off by default), preloads the end of monitor.log; display `ui/events_card.py` |
| `search.py` | Settings search: umlauts/hyphens don't matter, small typos allowed (difflib); Ctrl+F = `MainWindow.open_search` |
| `i18n.py`, `i18n_de.py` | Language: `tr()`, `N_()`, number format; German texts |
| `hotkeys.py`, `winapi.py`, `imaging.py`, `diagnostics.py`, `app_paths.py` | Helpers (global hotkeys via `RegisterHotKey`, window search via ctypes, image processing, diagnostics ZIP, paths) |
| `ui/` | PySide6 UI: `main_window.py` (sidebar, hotkeys, update start, wizard), pages `page_*.py`, `wizard.py` (setup), `update_dialog.py`, `widgets.py` (building blocks, **tables** `make_table`/`SortItem`), `theme.py` (QSS designs) |

Important design decisions:

- **The UI scales with the window size** (design 1180 × 800 = factor 1, 0.7–1.3): `theme.set_scale()` converts all
  px/pt in the stylesheet; fixed sizes in code only via `theme.track_margins/_spacing/_min_height/_fixed_width …`
  (never `setMinimumHeight(320)` directly or similar). The main window sets the factor 150 ms after resizing.
  Factor = **UI size** (`ui_zoom` 50–200 %, default 75 %) × optionally window fitting (`ui_auto_fit`), see
  `theme.factor_for`.
- **Auto-start** (`automonitor.py`, switch in the header, off by default): pure decision logic
  (`AutoMonitor.tick` → start/pause/resume/stop), game state from `rejoin.py` (the log thread also runs just for
  auto-start). Only **transitions** trigger: stopped yourself in the game → stays off until the next time you enter;
  started yourself outside → isn't stopped; disconnect → pause (same session), leaving → stop after 20 s.
  Carried out in `MainWindow._auto_tick` (also runs while the window is in the tray).
- **Secrets** (`secure.py`): `settings.json` stores `SECRET_FIELDS` and favorite links with Windows DPAPI
  (“dpapi:…”, `Settings.to_dict(protect=True)`); old plain-text files still load, on another PC the values become
  empty. Moving PCs: export/import as `.astralsettings` with a password (AES-256-GCM, scrypt; `cryptography` pinned,
  a hidden import in the build). No server/account – on purpose.
- **Explanations belong in ⓘ** (`Card(title, info)`, `InfoButton`), not as running text on the page; pages only have
  controls and status lines (owner's wish: less cluttered).
- **Design “Night City”** (since 0.9.9-beta.7, default; migration settings_version 12 switches Nebula): matching the
  game – violet-black, neon yellow/magenta, card borders magenta → cyan, angular; template `_NIGHTCITY` = Nebula +
  overrides, dark only.
- **Design “Nebula”** (since 0.7.0, default until 0.9.9-beta.6): derived from the logo; layout flag `rail` = slim icon
  bar (76 px, logo at the top, names as tooltips), status as a pill in the header, hints at the top (`top_toast`).
  Template = Astral + overrides (`_NEBULA`). Logo: `tools/make_icon.py`.
- **Since 0.9.0 – recognition without settings** (owner's wish): no “Detection” and “Raids” pages anymore (icon bar:
  Monitor, Statistics, Alerts, Settings; `PAGE_*` constants in `main_window.py`). `settings.fix_detection()` always sets
  the fixed values when loading (`FIXED_DETECTION`: raid end at 100/100 with one reading, window capture, default
  areas) – the fields only stay in the file for downgrades. Areas come from `astral_monitor/regions.json` (if missing:
  `DEFAULT_*_ROI`). **No “hot” tick** anymore: `PRESETS[…]["interval"]` (default 0.5 s; 100/100 shows for ~1 s).
  **Raid messages without a screenshot.** Developer tool (private, `_dev/`, never in the repo via `.git/info/exclude`):
  `_dev/calibrate.py` shows the Roblox window with the areas, sets them and writes `regions.json`; image library
  (`_dev/library/`, raids/upgrade shops with name and position) as groundwork for the macro.
- **Since 0.8.0:** settings with tabs (sections = `section()` headings, `_assign_groups`) and search; seasonal designs
  with decoration (`ui/seasonal.py`, painted by `ui/backdrop.py`, cards slightly translucent via `cardGlass` tokens,
  15 fps only while the window is visible); pumpkin night surprise (`ui/spooky.py`, at most 1×/h); Roblox profile
  (`roblox_profile.py`, public API only, name in `SECRET_FIELDS`); statistics values cached via `@_cached` until the
  next raid (measured with 120,000 raids); “New” dots per version in `ui/newdots.py` (maintain `NEW_FEATURES` with
  every release). Wave numbers always exact, other amounts with k (`messages.fmt_k`). A glass/mica effect was
  discarded: Qt draws windows with a Windows frame opaque.
- **Designs** (`theme.DESIGNS`, Settings → Appearance, `ui_design`/`ui_mode`): “Astral” (since 0.6.5: icons from the
  Windows symbol font, gear at the bottom left, cross-fade on page change, light/dark/like Windows) and “Classic”
  (since 0.5.0, dark only, unchanged). **Never delete old designs** – a new design = a new entry with a `since`
  version. Colors only as `@token` in the templates or `theme.color("token")` in code (no fixed hex values in the
  pages), otherwise light mode and design changes break. Switching applies right away (`MainWindow.set_appearance`,
  `theme.on_change` for painted content). Check images of all variants: `_shots/shots.ps1`, switch test:
  `_shots/look_test.py`.
- **Tray:** closing the window = keep running in the background (setting `close_to_tray`), quit via the tray menu. A
  second program start writes `show.request` into the data folder and exits; the running instance then shows its
  window. No autostart (owner's wish).
- **Wall:** `StatsStore.wall(raid)` – the wave where ≥ 60 % of the last 20 attempts of a raid end (e.g. a boss); shown
  in monitor/statistics/status message, alert “Wall broken” (event `wall`).
- **Engine and UI are separate.** The engine runs in a thread; the UI reads `engine.state` via a timer and events from
  `engine.events`. Touch widgets only in the GUI thread (`MainWindow.post(callable)` for callbacks from threads).
- **There are no failed attempts** (since 0.7.1, owner's wish): in Anime Astral a raid doesn't fail, you just get
  differently far, and every wave gives rewards. Every raid end goes through `Engine._finish_run` (same message “Raid
  finished · wave X/100”, raid number = all attempts). New CSV rows always have `ok`; old rows with `abgebrochen`
  count the same. Don't reintroduce a success rate or “made it to the end”. Time/rate metrics only use **measured**
  durations; estimated ones (note “geschätzt”, shown with `~`) don't count. **The final wave doesn't matter much**
  (owner 09.10.2026: most raids go to 100) – the statistics chart shows **raids per day** (`stats.daily`) instead of a
  final-wave distribution; don't bring that back.
- **The wave counter search area is large** (default top center), the program finds the counter by itself. Earlier
  narrow areas didn't work in windowed mode (title bar).
- **Performance is intentional** (goal: weak PCs too): no OCR without an image change, caches, adaptive tick, low
  process priority. Measured 06.10.2026 with real Roblox (raid running): **~1.6 % of a core, ~120 MB private**
  (before: 6.6 % + Tesseract processes, 706 MB). The levers – don't undo them:
  - WGC with `minimum_update_interval` (half the “hot” tick): unthrottled, Windows delivers up to 60 frames/s and the
    library copies each into RAM (~7 % CPU just for that).
  - Tesseract **directly via `libtesseract`** (ctypes, `ocr._TessLib`), the model stays loaded: ~5 instead of ~65 ms
    per reading, no process starts. Fallback `tesseract.exe` via pytesseract if the DLL can't be loaded.
  - `astral_monitor/__init__.py` sets `OPENBLAS_NUM_THREADS=1` etc. **before** the numpy import (OpenBLAS otherwise
    allocates buffers per core: 257 instead of 32 MB), `cv2.setNumThreads(1)`.
  - The UI doesn't draw while the window is minimized.
  - Memory: `winapi.trim_memory()` 30 s after the start, every 10 min and when minimizing. The working set otherwise
    contains startup leftovers and shared pages of graphics drivers (WGC loads AMD and NVIDIA drivers, ~370 MB) and
    fonts; measured 178 MB → permanently ~50 MB (own share/USS ~36 MB). “This program” shows the working set.
  - Update downloads are deleted at startup (`updater.cleanup_downloads`), otherwise ~60 MB would stay behind.
- **Raid statistics per raid or in total** (choice “All raids (total)”). Raids are just **names** (`profiles.py`;
  managed under Settings → Roblox, `ui/raids_card.py`). The current raid is chosen on the start page
  (`settings.current_raid`, `Engine.set_current_raid` – applies right away, also for the running attempt). Renaming
  (`Engine.rename_raid`) renames the folder, CSV history and selection too; deleting keeps the statistics.
- **Server favorites** (`settings.server_favorites`, max. 20; `private_server_link` = the marked one, used for “Join
  server” and auto-rejoin). Changes are saved right away (`MainWindow.set_server_favorites`), not via the save bar.
  Header button with an arrow menu and tray submenu. Diagnostics black out the links.
- **Times:** the engine uses `time.monotonic()` for tick/duration; tests partly set the clock artificially.
- **Since 0.9.7-beta.4/0.9.8 – pages without scrolling** (owner's wish): page header `widgets.page_header` (title + ⓘ +
  controls in one row), statistics lists as tabs, alerts in two columns, settings with tabs
  Roblox/Macro/Discord bot/Monitoring/Appearance/Program/Debug (`_assign_groups` packs card rows into widgets so hidden
  rows leave no gap). Check: `_shots/pages_fit.py [width height]` (reports scrolling per page/tab; env `AA_LANG`,
  `AA_DESIGN`, `AA_DEMO`, `AA_ALL`, `AA_ANON` – **`AA_ANON=1` for every public screenshot**, it clears name, favorites,
  links, IDs, tokens and webhooks). Header buttons are refreshed by `MonitorPage.refresh_controls` on every page.
- **Recognition (0.9.7-beta.4):** `WaveTracker` treats “4” after “53/54” (front digit covered, `_cut_digits`) as a
  restart only after `CUT_CONFIRM` s; while the macro clicks (`antiafk._macro_busy`), the engine only calls
  `tracker.hold()` and doesn't read quests. Macro image recognition: row search only in the strip `X_BAND` around the
  row start (~4× faster), titles are straightened before text recognition (`read_title`), words of a title line are
  joined (`_join_words`); check `_shots/title_regress.py` (136 real titles), run time `_shots/bench_vision.py`.
  RapidOCR was compared and discarded (not more accurate, 18× slower, +60 MB).

## Release process (GitHub, this repository – the build reads the name itself from `github.repository`)

1. Commit and push changes (default branch `main`).
2. Publish a version: create a release with the tag `vX.Y.Z` **or** Actions → “Release” → *Run workflow* with `X.Y.Z`.
   Betas: `vX.Y.Z-beta.N`. **Run the tests before tagging** – a changelog line over 70 characters fails the build.
3. `.github/workflows/release.yml` (Windows runner): version from the tag/input, `pip install`, **Tesseract via
   Chocolatey**, tests, `tools/write_build_info.py` (writes the version, `GITHUB_REPO`, `RPC_CLIENT_ID` from a
   repository variable), PyInstaller (`build_exe.py --no-zip`, bundles Tesseract), **Inno Setup**
   (`installer/AnimeAstralMonitor.iss`), SHA256 file, publishing via `softprops/action-gh-release`.
4. Result on the release: `AnimeAstralMonitor-Setup-X.Y.Z.exe`, `files-X.Y.Z.json` (checksum of every program file),
   `AnimeAstralMonitor-Update-X.Y.Z.zip` (only the files changed since the previous version, `tools/make_patch.py`)
   and `SHA256SUMS.txt` over all of them. Installed programs check `releases/latest` at startup (after ~6 s, at most
   every 6 h). **Small update:** if the package matches the installed state (`files.json` in the program folder,
   `updater.plan_patch`), only those files are downloaded, each checked by checksum and swapped after quitting by a
   PowerShell script (`updater.APPLY_SCRIPT`: backs up first, restores everything on error, restarts). Otherwise
   (version skipped, folder not writable …) the full installer runs silently (`/SILENT … /relaunch=1`). Only installer
   builds have an update source (`build_info.GITHUB_REPO` empty = no check). To keep packages small, CI builds with
   **pinned versions** from `requirements-build.txt` (raise them on purpose). Program size: `build_exe.py` only packs
   the Tesseract DLLs that are actually loaded and removes unused Qt/OpenCV/Pillow parts (`PRUNE`, with a check that no
   remaining file needs them): 380 → 228 MB installed.

The version number is in `astral_monitor/version.py` and is overwritten by the build from the tag. Count upwards.
The release notes come from the matching `## X.Y.Z` section in `CHANGELOG.md` (English, short bullets, ≤ 70
characters per line); work in progress goes under `## Unreleased` and is renamed on release. `build_exe.bat` builds
locally (the old ZIP updater `update.py` was removed in 0.7.1).

## Untested – please check first

As of 06.10.2026 (Claude Code on Windows): items 1, 3 and 5 done, 2 and 4 partly.

1. ~~**Whole UI**~~ – checked (all pages at 1180×800 and 980×680, wizard, update dialog, statistics: sorting,
   remembering column widths via `ui_state.json`). Fixed: statistics and raids page too wide in a small window, main
   buttons in cards unreadable (QSS rule `QFrame#card QWidget` overrode `QPushButton#primary`), the update dialog now
   shows release notes as Markdown with readable links. Open: real click-through by the owner.
2. **Window capture (`WgcSource`):** runs stable for hours with real Roblox (v0.5.0, `windows-capture` 2.0.1, read
   time ~81 ms). A covered window keeps delivering images and values; minimized, no images arrive (reported, then
   continues automatically). When switching (F11) frozen images arrive briefly – “25” was read as “29” and counted as a
   failed attempt; fixed in the tracker (a small drop = correction instead of restart). Check helper:
   `_shots/capture_probe.py` (not in the repo). Windowed ↔ full screen (F11): recognition works in both.
   **Yellow frame:** appears despite `draw_border=False` (accepted without error by `windows-capture` 2.0.1, but
   ignored by Windows 11 25H2). Not a code bug; Windows only allows hiding it via a privacy setting. The frame is only
   visual, not in the images.
3. ~~**GitHub build**~~ – run of 05.10.2026 successful, release `v0.5.0` with installer + `SHA256SUMS.txt`.
4. ~~**Installer**~~ – update 0.5.0 → 0.5.1 via the app including automatic restart successful (06.10.2026).
5. ~~**Bundled Tesseract**~~ – finds `tessdata` next to itself without `TESSDATA_PREFIX`, TSV output works.
6. **Discord profile status (`presence.py`):** every user enters their **own** application ID in the settings.
   **No personal IDs/numbers in the repository or the build** (owner's wish; the repo is public and passed on to
   friends) – the repository variable `RPC_CLIENT_ID` stays empty. Game: place `102072869879193` = universe
   `10502841145` “[CYBER] Anime Astral Simulator” (read from the running Roblox client); the old default `9797806474`
   was invalid and is replaced by a migration (settings_version 6). The connection to the Discord app and the thumbnail
   download work, but in the owner's profile the activity was **not visible** in the first test – cause still open.
7. ~~**Status message formatting**~~ – `##` and `-#` render correctly in embeds (owner's screenshot).
8. ~~**Hotkeys**~~ – work according to the owner. There is still no autostart.
9. **Disconnect detection** (since 0.6.4 via the Roblox log): reasons 276 (“other device”) and 285 (left yourself)
   checked on real logs. Real kicks (277, 278 = 20 min idle, 279, 267, 268) not yet seen live – they count as “lost”
   and trigger the alert/rejoin.

## Known weaknesses / ideas

- The wave evaluation expects all runs as “Wave x/y” with an allowed total (setting `allowed_totals`: round totals
  20–2000) or modes without a total (“Wave 542”). **Other raid formats** may need parser/search changes – the owner
  delivers screenshots.
- Plausibility filter in the tracker: allowed jump `UP_BASE + UP_PER_SECOND * seconds` (4 + 1.5/s). Fits about one wave
  every 3.7 s. Faster modes might need adjusting (simulations set `UP_BASE` high because they run 100× faster).
- **No raid detection by scenery image anymore** (since 0.6.4, owner's wish): the in-game camera can be moved freely
  and sometimes shows nothing to save resources – the ORB comparison (until 0.6.3) was unreliable. Don't bring it back
  without asking. Raids are detected from the raid window and unique drops (`raidsense.py`); the wave counter text
  recognition stays of course.
- **Planned for version 1.0** (proposals, not built yet; order to be agreed with the owner): overnight endurance test
  and crash restart, help page in the program, push via ntfy, license/“About” page, browser view on the home network
  (phone), daily/weekly goals, period comparison, Excel export/backup, several Roblox windows. An Android app is
  **not** sensibly possible (Windows capture, MediaProjection limits). An account switcher with stored Roblox logins
  was declined (no cookies/passwords stored – on purpose).
- The owner values: a **modern, clean, dark design**, short understandable explanations, low system load, calm Discord
  channels (one status message instead of many alerts; pings only for real problems).

## Way of working

- **Python on the owner's PC is the Microsoft Store version:** it redirects `%APPDATA%` (sees an old copy there instead
  of the real data) and fails with a global `pip install` on long paths. So always use the virtual environment
  `.venv` in the project folder (`.venv\Scripts\python.exe`).
- Create a Git commit before larger changes. Run `python -m unittest discover -s tests` after every change.
- Keep new logic **free of Qt** where possible so it stays testable in `tests/` (pattern: `tests/_env.py` sets
  `ASTRAL_DATA_DIR`).
- Extending settings: field in `Settings` + page `load()`/`apply()` + a migration via `settings_version` if needed.
- New Discord events go into `settings.EVENT_DEFS` (they show up under “Alerts” automatically).
- No webhook URL, no tokens, no personal data (IDs, links, names) in code or the repository – grep staged diffs before
  committing. The update check only accepts downloads from the own repository and checks SHA256 – don't weaken these
  protections. Commit with explicit paths (`git add astral_monitor tests …`), never stray downloads in the project
  folder.
- User screenshots/logs: the “Diagnostics package” button (Settings → Program or Debug) creates a ZIP (without webhook) with the
  log, value history, system info and window image – ideal for troubleshooting.
