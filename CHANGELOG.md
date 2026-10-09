# Changes

Newest version at the top. Short bullet points, no explanations (those are in the program behind the ⓘ).
A version's section becomes its release notes automatically when it is published
(`tools/release_notes.py`) and can be read in the program under Settings → Program → “All versions”.
Each section covers the whole line (e.g. 0.6.0 = everything from 0.6.0 to 0.6.5).

## Unreleased

### 🔧 Improved
- Counter jumps read consistently are accepted (no stuck counter)
- Monitoring started before Roblox waits for its window
- Settings: cards keep their size, no more empty boxes
- Discord bot tab lists all slash commands
- Start page: quests use the free space, wider Progressions button

## 0.9.11

### 🔧 Improved
- Several Auto Rolls in a row: the teleporter stays open in between
- Macro and monitoring share one text recognition (less RAM)
- Memory is released right after every macro run

## 0.9.10

### ✨ New
- English is the default language (German under Appearance)
- Farm routine: farm raids/defense, Auto Roll – rolls run in the raid
- Auto collect: Fixer Gigs (one pill per gig) and guild missions
- Fixer Gigs: every slot read on its own, refilled when done
- Guild missions once per PC day, retry after 3 h if nothing yet
- Raid settings: Auto Retry/Auto Leave set even under messages
- Explore all worlds; check findings with the marking tool
- Discord bot: /status, /start, /screenshot, /macro, /join, /pc …
- Design “Night City” as the new default
- Statistics: raids per day, raids today, time per raid
- Monitoring works without a Discord webhook
- Updates are much smaller (often only a few KB)

### 🔧 Improved
- Clicks hit precisely in windowed mode (title bar)
- Raid start faster, gear clicked again during the loading screen
- Auto Leave: wave entered first, then switched on
- Much less CPU in the lobby and while the macro collects
- Low priority from the start; weak PCs start with fewer animations
- Hotkeys with English key names (same keys)
- Automatic checks on every change, more tests

### 🗑️ Removed
- Design “Classic” (incomplete) – switches to Night City
- Final-wave statistics (how far a raid gets doesn't matter)

## 0.9.0

### ✨ New
- Detection built in – no areas to set up anymore
- Macro (beta): open menus, Auto Roll, farm raids, emergency stop
- Macro queue with loop; Anti-AFK pauses for the macro
- Explore: the macro learns worlds and menus by itself
- Raids with 30, 50 up to 2000 waves and modes without a total
- Debug tab with the whole log live
- Settings search (Ctrl+F) forgives umlauts and typos

### 🔧 Improved
- All pages without scrolling, only four pages in the icon bar
- Window titles and teleporter rows read faster and more reliably
- Quests aren't read while the macro opens menus
- A covered digit no longer ends a raid

### 🗑️ Removed
- Pages “Detection” and “Raids” (built in / under Settings)
- Screenshots in raid messages

## 0.8.0

### ✨ New
- Settings with tabs and a search field
- Your Roblox profile: avatar in the sidebar and on cards
- Personal records; archive the statistics and start over
- Designs “Bubble” and “OLED”; seasonal designs with decoration
- Message style “Compact” for Discord
- “What's new” after updates, “New” dots, “Report a problem”

### 🔧 Improved
- Much faster start, design changes and statistics
- Statistics calculated and cards drawn in the background
- Attempts and quest goals shortened with k (waves stay exact)

## 0.7.0

### ✨ New
- Design “Nebula”; auto-start with Anime Astral
- Export/import settings with a password
- All release notes in the program; install an older version
- Monthly recap and weekly overview
- Daily posts in a forum channel; own embed color per event
- Share server favorites; own accent color and background image
- Seasonal designs “Pumpkin night” and “Frost”, logo animation
- Safe start (hold Shift), beta channel for pre-releases

### 🔧 Improved
- No more “failed attempt”: every raid counts normally
- New live status with progress bar; logo on Discord messages
- Webhook and server links stored encrypted
- Explanations behind ⓘ; quest titles and progress read better

## 0.6.0

### ✨ New
- Wall detection (boss wave); tray icon
- English interface; the interface scales with the window
- Anti-AFK, private server without a browser, auto-rejoin
- Server favorites; raid selection on the start page
- Design “Astral” with light/dark mode and UI size 50–200 %

### 🔧 Improved
- Less memory; clearer statistics with a readable chart
- Disconnect alert from the Roblox log (no image recognition)

### 🗑️ Removed
- Raid detection by image

## 0.5.0

### ✨ New
- First version: wave counter, statistics, Discord alerts, updates
- Small updates (only changed files)

### 🔧 Improved
- Every attempt counts the same; sortable tables
- Less CPU and memory

### 🐞 Fixed
- A short drop of the counter no longer counts as a restart
