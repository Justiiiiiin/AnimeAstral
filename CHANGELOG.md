# Changes

Newest version at the top. Short bullet points, no explanations (those are in the program behind the ⓘ).
A version's section becomes its release notes automatically when it is published
(`tools/release_notes.py`) and can be read in the program under Settings → Program → “All versions”.

## 0.9.9-beta.13

### ✨ New
- English is now the default language (German under Appearance)
- Statistics: “Raids per day” replaces the final-wave chart
- Discord bot: commands /macro and /help (were /makro and /hilfe)

### 🔧 Improved
- Raid/defense: gear clicked after the loading screen, more precisely
- Guild missions: the “Personal” tab is collected again
- Settings tabs work in both languages

## 0.9.9-beta.12

### 🔧 Improved
- Fixer Gigs: pets list already at the bottom – no endless scrolling

## 0.9.9-beta.11

### 🔧 Improved
- Mana Contract (W19) recognized on bright backgrounds too
- Farm routine: “Progressions” step removed (button under collect)
- Auto collect: switches also work after saving
- Auto collect: clicking the text toggles the switch
- Texts in the program reworded to sound more natural
- Start page no longer works while the window is minimized

## 0.9.9-beta.10

### 🔧 Improved
- Explore: world names found despite misreads (“2 City” = “Z City”)
- Explore: no world skipped anymore (searches in both directions)
- Explore recognizes sideways scrollable lists
- Smaller windows (Mana Contract) are recognized more reliably
- W3/W9: the empty slot 8 is no longer clicked

## 0.9.9-beta.9

### 🔧 Improved
- Progressions: the macro presses “Auto All” (instead of “Roll All”)
- Window names as in the game: misreads corrected (“Craft Genos”)
- Explore: scroll probe only at up to 4 spots with content
- A mouse wheel without effect is turned back (camera no longer zooms)
- First-person view (cursor held) is detected and left
- Checked windows: only marked lists scroll, raids never
- Raid windows: the title “Raid” is no longer tested as a button
- Teleporter instead of a window in the image: not saved as a finding

## 0.9.9-beta.8

### 🔧 Improved
- Fixer Gigs: clicking a pet sends it, one gig at a time
- The macro no longer stops when the game moves the cursor
- Explore doesn't reopen checked windows
- “Don't open” in the description is respected while exploring
- Duplicate entries in “Check findings” merged
- Window titles read more reliably (grey banners, full-screen windows)

## 0.9.9-beta.7

### ✨ New
- New start page: farm routine on the left, collect bottom right
- Farm routine instead of the queue, the running step is marked
- Macro log with times under Settings → Macro
- Progressions: Roll All as a button under “Auto collect”
- New design “Night City” matching the game (Nebula stays selectable)

### 🔧 Improved
- Fixer Gigs: the time of every card is read (20 min / 1 h / 3 h)
- Collect times survive a restart
- Guild missions only once a day
- Explore: the worlds first, then shop & co.
- Learned windows brought back from earlier explore runs
- Raid selection shows all explored raids and defense modes
- “Navigate there” and “Close menu” removed
- The routine no longer changes its width when switching

## 0.9.9-beta.4

### ✨ New (beta)
- Check findings: large window image, draw and label boxes
- Kinds: button, never press, switch, value, list, tab, info
- Enter a description and name per window yourself
- “Never press” becomes a no-go zone, “List” is scrolled on purpose
- Explore opens every window once until it has been checked

### 🔧 Improved
- Values like “514δU / MAX” are read together

## 0.9.9-beta.3

### ✨ New (beta)
- Check findings: confirm every window after exploring
- Explore opens every window only once (unless asked to recheck)

### 🔧 Improved
- Explore finds scrollable lists by itself (no longer blind)
- Timers and animations no longer count as scrolling
- Global Quests: only scroll down to the first finished quest
- Guild tabs recognized in the large guild window too
- Windows that open late are waited for, Boosts recognized
- A second try when the capture stutters briefly

## 0.9.9-beta.2

### ✨ New (beta)
- Discord bot: control the program with slash commands (own bot)
- /pc: shut down/restart the PC (switch, 60 s, can be cancelled)
- Progressions: Roll All as a button and a task
- Settings → Macro: explore with duration and options

### 🔧 Improved
- Explore never presses Leave & co. – no hovering there either
- Explore: tabs recognized strictly, scrolls, tests view buttons
- Explore only reopens windows that had problems
- The guild window is recognized (larger than other menus)
- Target lists sorted by world, Progression only once
- UI size 75 % by default

## 0.9.9-beta.1

### ✨ New (beta)
- Queue: one “Raid” task that ends after N raids/minutes
- A raid is only left when a different raid follows
- Auto collect: Fixer Gigs (1 pet per gig) and guild
- Raid selection as a dropdown in the live card
- The raid is recognized from the raid window (also when you play)
- The raid is recognized from unique drops (e.g. auto-join)
- Explore opens everything and clicks through tabs on the left
- Buttons at the screen edge are found at any GUI size

### 🎨 Design
- The start page shows almost only the macro
- UI size 50 % by default

## 0.9.8

### ✨ New since 0.9.1 (summary of the betas)
- Macro (beta, start page): open menus, Auto Roll, raids
- Macro queue with loop: Auto Roll, farm raids, wait
- Farm raids: set Auto Retry/Auto Leave, leave afterwards
- Explore: the macro learns worlds and menus by itself
- New Anti-AFK (all Roblox windows, 4× Esc), pauses for the macro
- All pages without scrolling, statistics and alerts reorganized
- Debug tab: the whole log live, off by default

### 🔧 Improved in this version
- Window titles are straightened before reading (21 of 136 better)
- Titles with several words are read completely
- Row search in the teleporter ~4× faster
- Quests aren't read while the macro opens menus
- Explore reads every window only once (saves ~150 ms)
- Settings search forgives umlauts and typos
- Ctrl+F opens the settings search from every page

## 0.9.7-beta.6

### 🔧 Improved
- Explore turns Anti-AFK off and back on afterwards

## 0.9.7-beta.5

### ✨ New
- Debug tab: switch “Debug on” (off by default, saves load)
- Debug shows the whole log live, like in the diagnostics package
- Debug: filter, copy, clear and diagnostics package

### 🐞 Fixed
- Start/pause icons at the top left were missing on other pages

## 0.9.7-beta.4

### 🎨 Design
- All pages fit without scrolling
- Statistics: recent attempts, raid comparison and records as tabs
- Alerts in two columns
- Settings reorganized, debug as its own tab
- Title and controls in one row, explanations in the ⓘ
- More compact queue, fields matching the task

### 🔧 Improved
- A covered digit (“4” instead of “54”) no longer ends a raid
- While the macro opens menus, the detection evaluates nothing
- The debug list shows whole sentences
- Explore waits less after clicks

## 0.9.7-beta.3

### 🔧 Improved
- Explore doesn't click empty slots after the last icon
- Smaller windows are recognized (Passives, Equip Best …)
- Grey or bright window titles are read better
- Raids are named by their name (“Holy Grail War” instead of “Raid”)
- Newly classified: shrines, passives, Fixer Gigs, display only
- “Magecraft Progression” is no longer crafting
- Slots without a window are remembered and not clicked again
- Explore: 10 minutes by default, at most 30

## 0.9.7-beta.2

### ✨ New (beta)
- Queue: “Farm raid” – start, N raids, then leave
- The macro sets Auto Retry and Auto Leave (from wave N) itself
- “Leave raid”: first Auto Retry off, then LEAVE!
- Explore skips gates and the skull (time-based modes)

### 🔧 Improved
- Explore: teleporter closed? Open it again and continue
- Windows are named like your buttons (“Ninja Raid” instead of “Raid”)
- Newly recognized: quests, inventory, achievements, index, ranks …
- Claim buttons are counted in the report (never clicked)
- Header: start/stop, pause and status only as icons
- Anti-AFK countdown small above the switch

## 0.9.7-beta.1

### ✨ New (beta)
- Explore: the macro opens new worlds and menus by itself (3 min)
- Built-in knowledge: gacha, titans, pets, crafting, artifacts …
- Reads Equip Best, Guild and the buttons at the screen edge
- Findings go into the map – selectable right away afterwards
- While exploring only open/close, never Roll, Buy or Claim
- Queue: Auto Roll, start raid, join raid
- Macro card: “Auto Roll” for every target (also pets roll)

## 0.9.5-beta.4

### ✨ New (beta)
- Macro queue: tasks one after another, in a loop if you want
- Tasks: open menu, roll pets, close menu, wait
- During “Wait” the Anti-AFK keeps running

### 🔧 Improved
- Start/stop, pause and status button at the top left of the header
- Start page without title, window info and raid selection
- Events as a debug card under Settings → Program

## 0.9.5-beta.3

### 🐞 Fixed (beta)
- The macro scrolls in the teleporter (moves the mouse first)
- If the mouse wheel moves nothing, the macro drags the scroll bar
- Macro steps are in the log (troubleshooting)

## 0.9.5-beta.2

### ✨ New (beta)
- “Automation” is now called macro and sits on the start page
- Roll pets: after “Auto!” the menu closes right away
- New Anti-AFK: all Roblox windows, 4× Esc, no waiting
- A minimized Roblox stays open afterwards (detection keeps running)
- Anti-AFK frees Roblox's memory afterwards

### 🔧 Improved
- New start page: macro + events on the left, live + quests right
- Events and quests compact, one line each
- Live detection without a preview image
- Larger window: start page without scrolling

## 0.9.5-beta.1

### ✨ New (beta)
- Automation (beta) under Settings → Roblox, off by default
- Open menus via the map: teleporter, scroll to the world, icon
- Roll pets: open the world's roll menu and press “Auto!”
- Emergency stop: move the mouse or press Esc
- No walking, no teleporting

## 0.9.1

### 🐞 Fixed (hotfix)
- Raids with 30, 50 or up to 2000 waves are recognized again
- Modes without a total (“Wave 542”) are recognized and counted

## 0.9.0

### 🔧 Improved
- Detection built in – no more areas to set up
- Always window capture, raid end at 100/100
- Even tick (every 0.5 s) instead of a “hot” tick
- Larger quest area: all quests including progress
- Manage raids under Settings → Roblox
- Only four pages in the icon bar
- All improvements from 0.8.1-beta.1

### 🗑️ Removed
- “Detection” page (areas, triggers, confirmations)
- “Raids” page with a trigger and note per raid
- Screenshots in raid messages
- The old features are still available in 0.8.1 and older

## 0.8.1-beta.1

### 🔧 Improved
- Faster start: pages are only built when first opened
- Design and color changes about twice as fast
- Statistics are calculated in the background – no more freezes
- Analyses up to 160× faster, history loads ~4× faster
- Stats cards are drawn in the background
- Smoother seasonal decoration (20 fps) without extra load
- Snappier page switching

## 0.8.0

### ✨ New
- Settings with tabs and a search field
- Your Roblox profile: avatar in the sidebar and on cards
- Personal records in the statistics
- Archive the statistics and start over
- Designs “Bubble” (round) and “OLED” (true black)
- Seasonal designs New Year's Eve, cherry blossom and summer
- Seasonal decoration: leaves, pumpkins, snow, fireworks, blossoms
- Pumpkin night surprise (can be turned off)
- Message style “Compact” for Discord
- Accent color from the background image
- “What's new” after updates and “New” dots
- “Report a problem” at the very bottom of the settings

### 🔧 Improved
- Statistics stay smooth with a large history
- Attempts and quest goals shortened with k (waves stay exact)
- Recently used raids at the top
- Stronger seasonal colors
- Empty areas with a small illustration
- Logo animation at startup reliably visible

## 0.7.5.1

### 🐞 Fixed
- Windows shows the new logo on shortcuts
- Quest titles more complete (text after the number stays)
- Split raid names in quests repaired (“Conv oy”)
- Quest progress “1/90” is recognized
- Quests in the same order as in the game

## 0.7.5

### ✨ New
- Monthly recap as a card (save or send to Discord)
- Weekly overview: farming time per day (Statistics → Week)
- Raid messages as a daily post in a forum channel
- Own embed color per event
- Share server favorites with friends via a code
- Free choice of accent color
- Own background image (can be dimmed)
- Seasonal designs “Pumpkin night” and “Frost”
- Logo animation at startup (can be turned off)
- Safe start (hold Shift)
- Beta channel for pre-releases

### 🔧 Improved
- The wave number changes color near the best wave
- Switch “Reduce animations”
- Storage overview with cleanup
- Diagnostics package without IDs, links and user name

## 0.7.1

### 🔧 Improved
- No more “failed attempt”: every raid counts normally
- The raid message shows the wave reached
- New live status: progress bar, icons, logo
- Logo as the avatar of the Discord messages
- Program cleaned up (old updater removed)

## 0.7.0

### ✨ New
- Design “Nebula”: slim icon bar, status pill
- Auto-start: monitoring starts/stops with Anime Astral
- Export/import settings (with a password)
- All release notes readable in the program
- Install an older version (downgrade)
- New logo

### 🔧 Improved
- Webhook & server links stored encrypted
- Explanations behind ⓘ instead of as text
- Release notes as text in the update window

## 0.6.5

### ✨ New
- Design “Astral” with icons and a gear
- Light, dark or Windows mode
- UI size 50–200 %
- The old design selectable as “Classic”

### 🔧 Improved
- Clearer statistics, readable chart

## 0.6.4

### ✨ New
- Server favorites (add, edit, delete)
- Raid selection on the start page
- Rename raids

### 🔧 Improved
- Settings reorganized, fixed save bar
- More precise disconnect alert (without image recognition)

### 🗑️ Removed
- Raid detection by image

## 0.6.3

### ✨ New
- Auto-rejoin after a disconnect, kick or crash

## 0.6.2

### ✨ New
- Join a private server without a browser

## 0.6.1

### ✨ New
- Anti-AFK switch

### 🔧 Improved
- More compact raid list (max. 8 visible)

## 0.6.0

### ✨ New
- Wall detection (boss wave)
- Tray icon: keeps running in the background
- English interface
- The interface scales with the window

### 🔧 Improved
- Less memory

## 0.5.2

### 🔧 Improved
- Small updates (only changed files)
- Less CPU and memory

## 0.5.1

### 🔧 Improved
- Every attempt counts the same
- Sortable tables
- Own Discord ID for the profile status

### 🐞 Fixed
- A short drop of the counter no longer counts as a restart

## 0.5.0

### ✨ New
- First version: wave counter, statistics, Discord alerts, updates
