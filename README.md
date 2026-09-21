# Instagram unfollow script

Unfollows everyone you follow on Instagram who doesn't follow you back.
Runs on your own PC. It opens a real browser window (Chrome or Edge), you log in to
Instagram there like normal, and the script does the rest from the terminal.

## Setup (once)

1. Install Python from https://www.python.org/downloads/ (on Windows tick **"Add python.exe to PATH"** in the installer).
2. Download this repo (green **Code** button → **Download ZIP**) and unzip it somewhere.

## Run it

- **Windows:** double-click `run.bat`
- **Mac / Linux:** open a terminal in the folder and run `./run.sh`

What happens:

1. First time only, it installs what it needs (about a minute).
2. A browser window opens on Instagram's login page. **Log in there**, including any
   two-factor code. The script waits for you. Your login is remembered in the
   `browser_profile` folder, so next time it skips straight past this.
3. It fetches who you follow and who follows you, then shows the list of accounts
   that don't follow you back and asks `Unfollow N account(s)? [y/N]`.
4. Type `y`. It unfollows one account every 30–40 seconds and keeps going until nobody
   is left. Leave the browser window open (minimized is fine). Press Ctrl+C to stop any time.

## Options

Run from a terminal with extra flags, for example `venv\Scripts\python unfollow.py --dry-run`
(Windows) or `venv/bin/python unfollow.py --dry-run` (Mac/Linux):

| Flag | What it does |
|------|--------------|
| `--dry-run` | Only shows the list, unfollows nobody |
| `--yes` | Skips the confirmation question |
| `--max 50` | Stop after 50 this run (default: no limit, runs until everyone is unfollowed) |
| `--keep-verified` | Never unfollow blue-check accounts |

## Keeping certain accounts

Put usernames in `whitelist.txt`, one per line. Those are never unfollowed.
The full list of who doesn't follow you back is also saved to `not_following_back.txt` each run.

## Staying out of trouble with Instagram

No script can promise Instagram won't notice, but this one is built to look like a person:

- It uses a real Chrome/Edge window on your own internet connection and your normal
  logged-in session, and sends the exact same requests the Instagram website sends
  when you click Unfollow. There is no fake app or fake phone involved.
- It waits a random 30–40 seconds between unfollows, and only fetches your lists the
  way the site does when you scroll them.
- If Instagram does throw a temporary "try again later" block, the script waits 10 minutes
  (longer if it keeps happening) and carries on by itself. These blocks are temporary,
  not bans, and going slower is the only real fix. If you want to be extra careful,
  run with `--max 150` once a day instead of all at once.

## If something goes wrong

- **The window flashes and closes:** open the folder, click the address bar in File Explorer,
  type `cmd`, press Enter, then type `run.bat` and press Enter. The error stays on screen.
- **"Could not start a browser":** run `venv\Scripts\playwright install chromium` in that
  same cmd window, then try again.
- **"Instagram is refusing connections from your network":** wait 15–30 minutes. VPNs and
  shared networks trigger this.
- **Instagram asks you to confirm it's you:** do that in the browser window, then press
  Enter in the terminal. The script picks up where it left off.
- **Login stopped working:** delete the `browser_profile` folder and run again.
- Instagram's terms don't officially allow automation. Using the default pace keeps the
  risk low, but it is never zero.
