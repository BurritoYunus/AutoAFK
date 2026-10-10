# AutoAFK

Automated bot for AFK Arena. It runs your dailies, arena, guild hunts, store, events and more on an Android emulator over ADB, and can play newer modes such as **Misty Valley** and **Shadow Realm** by reading the screen.

Fork of [Hammanek/AutoAFK](https://github.com/Hammanek/AutoAFK), maintained at [BurritoYunus/AutoAFK](https://github.com/BurritoYunus/AutoAFK). Updates are published from this repository.

## Features

### Dailies (one button, or `--dailies`)
- ✅ AFK rewards, fast rewards, mail, companion points, mercenaries
- ✅ Fountain of Time, King's Tower, Oak Inn, bag consumables, level up, summons
- ✅ **Guild Hunts** – works with the new guild *island* layout (falls back to the old one); Wrizz, Soren and optional Soren activation on chosen days
- ✅ **Twisted Realm** – via Hellscape on the guild island
- ✅ **Store** – purchases and refreshes (quick-buy or item by item)
- ✅ **Collect Merchants** – redesigned store: opens only emporiums and tabs with a red **!**, takes only items marked **Free** (never taps a price), claims reached pass rewards (Champions of Esperia, Twisted Bounties, Regal Rewards); old store flow kept as a fallback
- ✅ Arena of Heroes, Temporal Rift and Gladiator collection
- ✅ Bounty board (solo, team and event bounties)
- ✅ Arcane Labyrinth, quests

### Activities (Run Activity panel)
- ✅ **Misty Valley** – clears every open stage: reads each stage's challenges with text recognition, builds teams with the faction and class filters (strongest heroes first) and does Silver and Gold where possible
- ✅ **Shadow Realm** – Golden Frontier → Realm of Shadows: collects rewards, uses every team's attempts on the open floors, kills the boss every 20 floors
- ✅ Arena of Heroes, Arcane Labyrinth, Fight of Fates, Battle of Blood, Heroes of Esperia, Guild Hunts

### Auto Push
- ✅ Campaign and every tower open today, with formation choice and formation cycling

### App
- ✅ Resizable Dailies Configuration window that scrolls, with Save always visible
- ✅ Colour-coded log with per-stage summaries
- ✅ Headless mode for [Task Scheduler](#scheduling-with-task-scheduler) (`--dailies`, `--shadowrealm`, `--tower`)
- ✅ Auto-update from this repository's releases
- ✅ Discord / Telegram notifications
- ✅ Debug screenshots when something isn't found

## Quick Start

1. **Download** the latest `AutoAFK.zip` from [Releases](https://github.com/BurritoYunus/AutoAFK/releases/latest).
2. **Extract** the whole folder somewhere, e.g. your Desktop.
3. **Configure:** rename `settings.ini.example` to `settings.ini`. Set your emulator's ADB `port` and `emulatorpath` (see [Advanced](#advanced)).
4. **Run** `AutoAFK.exe`.

## Requirements

- Windows 10/11 (64-bit)
- An Android emulator (e.g. BlueStacks, MuMu) with **ADB enabled**
- Resolution **1080×1920 (portrait)**
- Game language **English**
- ADB is included in the release. No Python needed for `AutoAFK.exe`.

Running from source instead: Python 3.11/3.12, then `install.bat` and `start.bat` (or `pip install -r requirements.txt` and `python main.py`).

## Misty Valley

Run Activity → **Misty Valley**.

1. **Getting in:** the bot goes Campaign → Events → Adventure → Misty Valley → Continue Adventure. The camera centres on the cart.
2. **Each stage:** it opens the stage and reads the stage number and the challenge text, then works out a team:
   - *Win with N <faction> heroes*, *N different factions*, *Frontline/Backline must be <class>*, *same class*, *without any <class>* → team rules. Silver and Gold are combined into one battle when possible, otherwise done in separate battles.
   - Time limits, no deaths, ultimates → just win with the strongest team.
   - *Victorious Team Contains* (specific heroes) → skipped.
3. **Building the team:** remove all, then pick heroes with the faction filter, plus the class filter only when a challenge needs it. Heroes are taken from the top-left (strongest), and the first 2 placed are the frontline.
4. **Defeats:** after a loss it drops that challenge and wins the stage with the strongest heroes. It stops after 2 defeats on one stage.
5. **Moving on:** it drags the map up and sideways to the next stage. When nothing is visible, it nudges the map, or backs out once and re-enters.
6. **Stopping:** it stops at a stage with an *Opens in* timer or at the top of the map, prints a summary, and goes back to the campaign.

Because the challenges are read from the screen, a new month's challenges work without code changes.

## Shadow Realm

Run Activity → **Shadow Realm**, or `AutoAFK.exe --shadowrealm`.

1. **Getting in:** Campaign → **Golden Frontier**. If the leaderboard opens, the bot taps Return once. Then the Shadow Realm shortcut → **Go**.
2. **Floor limit:** it reads **Highest explorable floor** when it first enters and never goes past it.
3. **Rewards:** it taps every **Receive**, then closes the rewards popup once per floor.
4. **Battles:** it takes the **Challenge** buttons top to bottom and left to right, scrolling for lower floors. Each battle uses the team with the most attempts left (e.g. `4/6`). Teams that are *Recovering Blessed Flames* are skipped.
5. **Bosses:** every 20 floors there is a boss with one Challenge button. The bot kills it like any other node. The next floors only open once enough of the guild has beaten it (the tracker next to the boss).
6. **Stopping:** it stops when every team is out of attempts, when the boss is done and the guild tracker shows with no Challenge left, or at the highest explorable floor. If no Challenge is visible, it goes back to the map and in again once to make sure. Then it returns to the campaign.

### Shadow Realm on a schedule

Each attempt takes about **1 h 50 min** to come back, up to **6 per team**, so a team is full again after ~11 hours. Run it every **11 h 10 min** (`670 minutes`) so no attempts are wasted. See [Scheduling with Task Scheduler](#scheduling-with-task-scheduler) for the setup.

## Configuration

Edit `settings.ini`, or use **Configure Dailies**, **Store Options** and **Advanced Options** in the app.

### Daily Activities
```ini
[DAILIES]
collectrewards = True       # AFK rewards
collectmail = True          # Collect mail
deletemail = True           # Delete read mail
fastrewards = 1             # Fast rewards count (0 = off)
companionpoints = True      # Companion points
lendmercs = True            # Lend mercenaries
attemptcampaign = False     # Attempt a campaign battle
fountainoftime = True       # Fountain of Time
kingstower = True           # King's Tower attempt
collectinn = True           # Oak Inn gifts
guildhunt = True            # Guild Hunts (Hunting Fields, Wrizz, Soren)
storepurchases = True       # Store purchases
shoprefreshes = 2           # Store refreshes
twistedrealm = True         # Twisted Realm
collectquests = True        # Quest rewards
collectmerchants = True     # Free merchant deals and pass rewards
runlab = True               # Arcane Labyrinth
usebagconsumables = True    # Use bag consumables
levelup = True              # Level up heroes
summonhero = False          # Free summons
sorenactivate = False       # Activate Soren...
sorenactivate_days = 1,3,5,6,7   # ...on these days (1 = Monday)
hibernate = False           # Hibernate the PC when done
```

### Arena
```ini
[ARENA]
battlearena = True          # Arena of Heroes battles
arenabattles = 8            # Number of battles
arenaopponent = 4
tscollect = True            # Temporal Rift rewards
gladiatorcollect = True     # Gladiator coins
```

### Bounties
```ini
[BOUNTIES]
dispatchsolobounties = True
dispatchteambounties = True
dispatcheventbounties = True
dispatchdust = True
dispatchdiamonds = True
dispatchshards = True
dispatchjuice = True
refreshes = 3               # Bounty refreshes
remaining = 2               # Leave this many undispatched
```

### Store
```ini
[SHOP]
quick = True                # Use Quick Buy when available
arcanestaffs = True
cores = False
timegazer = True
baits = False
dust_gold = True
shards_gold = True
dust_diamond = True
elite_soulstone = False
superb_soulstone = False
silver_emblem = False
gold_emblem = False
poe = True
```

### Events
```ini
[EVENTS]
fightoffates = False
battleofblood = False
circustour = False
heroesofesperia = False
```

### Auto Push
```ini
[PUSH]
formation = 1               # Formation to copy (1-5), also set in the app
useartifacts = True         # Copy artifacts with the formation
cycleformation = 30         # Switch formation every N minutes (0 = off)
```

### Advanced
```ini
[ADVANCED]
port = 7555                 # Emulator ADB port (0 = auto-detect)
emulatorpath = C:\Program Files\BlueStacks_nxt\HD-Player.exe   # Started if not running
emulatorargs =              # Extra launch options, e.g. --instance Pie64_1 (MuMu gets -v 0 automatically)
loadingmuliplier = 2        # Slower PC/emulator? Increase (waits are multiplied)
debug = False               # Save debug screenshots / more logging
adbrestart = True           # Restart ADB on connect
ignoreformations = False    # Auto Push: keep the current team instead of copying a formation
popularformations = False   # Auto Push: copy from the Popular formations tab
autoupdate = True           # Update automatically on startup
```

### Notifications
```ini
[DISCORD]
enable = False
channel_id =
token =

[TELEGRAM]
enable = False
chat_id =
token =
```

## Headless Mode

Run without the window, e.g. from Task Scheduler.

```batch
AutoAFK.exe --dailies          # All enabled dailies
AutoAFK.exe --shadowrealm      # Shadow Realm attempts
AutoAFK.exe --autotower        # Push every tower open today
AutoAFK.exe --tower c          # Push one tower: kt, lb, m, w, gb, c, h
```

All arguments:
```
-c, --config FILE       Use a different config file (default: settings.ini)
-d, --dailies           Run dailies
-sr, --shadowrealm      Run Shadow Realm
-at, --autotower        Push all towers
-t, --tower NAME        Push one tower (kt, lb, m, w, gb, c, h)
-l, --logging           Enable file logging
```

### Seeing the output in PowerShell

Headless runs print their log to the terminal that started them, in colour. PowerShell needs `.\` for programs in the current folder, and doesn't wait for AutoAFK.exe by default. To keep the prompt until the run is done, start it like this:

```powershell
Start-Process .\AutoAFK.exe -ArgumentList '--shadowrealm' -NoNewWindow -Wait
```

Every run is also logged to the `logs` folder.

## Scheduling with Task Scheduler

Let Windows start AutoAFK for you. The bot opens the emulator if it's closed, starts AFK Arena itself and goes back to the campaign when done, so you don't need to open anything first.

**Before you start**, set these in `settings.ini`:
```ini
[ADVANCED]
port = 0                                                  # or your emulator's ADB port
emulatorpath = C:\Program Files\BlueStacks_nxt\HD-Player.exe
```
Point `emulatorpath` at the emulator's `.exe`, not a desktop shortcut (`.lnk`).

**Create the task** (open *Task Scheduler* → **Create Task…**, not *Create Basic Task*):

1. **General**
   - Name: e.g. `AutoAFK Shadow Realm`
   - Keep **Run only when user is logged on** (the emulator needs your desktop)
   - Configure for: **Windows 10**
2. **Triggers** → New…
   - Shadow Realm: Begin the task **At log on**, tick **Delay task for** `2 minutes`, tick **Repeat task every** and type `670 minutes`, duration **Indefinitely**. It runs shortly after you log in, then every 11 h 10 min.
   - Dailies: Begin the task **On a schedule** → **Daily**, at a time shortly after the daily reset.
3. **Actions** → New… → *Start a program*
   - Program/script: `C:\path\to\AutoAFK\AutoAFK.exe`
   - Add arguments: `--shadowrealm` (or `--dailies`)
   - Start in: `C:\path\to\AutoAFK` (the folder only, no `\AutoAFK.exe`, otherwise `settings.ini` isn't found)
4. **Conditions**: untick **Start the task only if the computer is on AC power** if you're on a laptop.
5. **Settings**
   - Tick **Run task as soon as possible after a scheduled start is missed**
   - If the task is already running: **Do not start a new instance**

Make one task per activity. Don't let two tasks overlap, they would fight over the game.

**Check it works:** close the emulator, right-click the task → **Run**. The emulator opens, AFK Arena starts about 30 s later and the bot gets going (the emulator window is minimized; open it to watch). Task Scheduler shows no console, so read the newest file in the `logs` folder. When it's done the task goes back to **Ready** with Last Run Result **(0x0)** (press F5 to refresh).

## Updating

- **Automatic:** with `autoupdate = True`, the app checks [Releases](https://github.com/BurritoYunus/AutoAFK/releases) on startup, installs a newer version and restarts. `settings.ini` is always kept.
- **Manual:** run `update.bat`, or download the latest `AutoAFK.zip` and replace everything except `settings.ini`.
- **Source installs** update from the latest release, or from `master` when there is none. A git clone is updated with `git pull --ff-only`.

### Publishing a release (maintainers)

1. Merge your changes to `master`.
2. Publish a release with a new tag, e.g. `v2.2.0`. The **Build Executable** workflow builds `AutoAFK.zip`, sets the version from the tag and attaches the zip to the release.
3. If the workflow doesn't start by itself, run it from **Actions → Build Executable → Run workflow** on the tag.

## Troubleshooting

### Bot doesn't connect
1. In the AutoAFK folder, run `.\adb.exe devices`. Your emulator should be listed.
2. Make sure ADB is enabled in the emulator settings.
3. Set the right `port` in `settings.ini` (BlueStacks shows it in its ADB settings, often `5555`).
4. Restart ADB: `.\adb.exe kill-server`, then `.\adb.exe start-server`.

### An activity stops or taps the wrong thing
1. Check the emulator is **1080×1920 portrait** and the game is in English.
2. Increase `loadingmuliplier` on a slow PC.
3. Set `debug = True`, run again, and look in the `debug` folder: there's a screenshot of every screen the bot didn't recognise.
4. Check the newest file in `logs`.

### Update failed
1. If the updater window looks stuck, click it and press Enter.
2. Otherwise, download `AutoAFK.zip` from [Releases](https://github.com/BurritoYunus/AutoAFK/releases/latest) and replace everything except `settings.ini`.

## Support

- Report issues: [GitHub Issues](https://github.com/BurritoYunus/AutoAFK/issues)
- Include the log from `logs` and any screenshots from `debug`.

## Disclaimer

This bot is for educational purposes only. Automating the game may be against its terms of service. Use at your own risk. The authors are not responsible for any consequences of using this bot.
