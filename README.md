# Mo Betta Crafts

An always-on-top crafting helper for Monsters & Memories. It uses no addons, doesn't read game memory, and doesn't inject anything into the game.
It knows about 1,400 tradeskill recipes from the community wiki, and it keeps track of the materials you tell it you have.

## Install

1. Unzip `MoBettaCrafts-win64.zip` anywhere and run `install.bat`. It copies the app to
   `%LOCALAPPDATA%\MoBettaCrafts`, adds a Start Menu shortcut, asks whether to start with Windows, and launches it.
2. Windows SmartScreen will warn you the first time because the exe isn't code-signed. Click **More info**, then **Run anyway**.
3. Look for the gold anvil icon in the system tray. **Ctrl+Shift+K** shows or hides the overlay.
   This works while the game has focus if the game is windowed or borderless.

`uninstall.bat` (in the install folder) removes everything and asks whether to keep your pinned recipes.
If you'd rather skip the installer, run `MoBettaCrafts.exe` from anywhere. It keeps its files next to itself.

## Using it

- **Search** by what you want to make, *or* by an ingredient you have. For example, "copper ore" shows everything that uses it.
  The dropdown on the right browses a single skill.
- **Click ☆** to pin a recipe to your crafting list. Use **+ / −** to set how many you plan to make, and **✕** to unpin.
- **have / need**: click the *have* number, type how many you've got, and press Enter. Green means you have enough, orange means you're short.
  The game keeps your bags on its server, so no file on your PC says what you're carrying. That's why you enter the counts yourself.
- **✓ made 1**: press it after each combine. It takes that recipe's ingredients off your counts, adds what you made, and counts the pin down by one.
- Counts are saved per character.
- **▸ next to an ingredient** means you can craft that ingredient too. Click it to see its recipe and how many combines would cover what you're short.
- 🔧 marks tools (hammer, pliers, …). They're needed but not used up.
- The overlay follows whichever character you're playing, based on whose files the game wrote to most recently.

**Tray icon** (right-click): *Update recipes from wiki* pulls the latest recipes. The menu also has *Start with Windows*, *Open log*, and *Quit*.
Drag the title bar to move the overlay. The **–** button collapses it and **×** hides it.

## Where the recipes come from

The recipes come from the community wiki at https://monstersandmemories.miraheze.org (content under CC BY-SA). Thanks to everyone who edits it.
Players write the wiki, so some recipes may be missing or wrong. Fix them on the wiki and everyone's copy gets better next time they update.
Some skills have no recipes on the wiki yet, including Brewing, Fermenting, Pottery, Masonry, Spinning, and Farming.
