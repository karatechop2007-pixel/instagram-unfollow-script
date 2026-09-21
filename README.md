# Instagram unfollow script

Unfollows everyone you follow on Instagram who doesn't follow you back.
Runs on your own PC, no website or app needed.

## Setup (once)

1. Install Python from https://www.python.org/downloads/ (on Windows tick **"Add python.exe to PATH"** in the installer).
2. Download this repo (green **Code** button → **Download ZIP**) and unzip it somewhere.

## Run it

- **Windows:** double-click `run.bat`
- **Mac / Linux:** open a terminal in the folder and run `./run.sh`

The first time it installs what it needs, then asks for your Instagram username and password
(the password isn't shown while typing). If you have two-factor auth on, it asks for the code.
Your login is saved to `session.json` in the folder so you don't have to log in again next time.

It then shows the list of accounts that don't follow you back and asks
`Unfollow N account(s)? [y/N]`. Type `y` and it starts.

## Options

Run from a terminal with extra flags, for example `python unfollow.py --dry-run`:

| Flag | What it does |
|------|--------------|
| `--dry-run` | Only shows the list, unfollows nobody |
| `--yes` | Skips the confirmation question |
| `--max 50` | Stop after 50 this run (default: no limit, runs until everyone is unfollowed) |
| `--keep-verified` | Never unfollow blue-check accounts |

## Keeping certain accounts

Put usernames in `whitelist.txt`, one per line. Those are never unfollowed.

## Things to know

- The script waits a random 30–40 seconds between each unfollow and keeps going until
  nobody is left. For a few hundred accounts that's a few hours, so just leave it running.
- If Instagram rate-limits you mid-run, the script waits 10 minutes (longer if it keeps happening)
  and then carries on by itself. You don't need to do anything.
- If it gets really stuck, Ctrl+C stops it. Running it again later picks up where it left off.
- If Instagram asks you to confirm "it was me" in the app, do that, then run the script again.
- If login stops working, delete `session.json` and run again.
- Instagram's terms don't officially allow automation, so there's always some risk of a
  temporary action block. Using the default delays keeps that risk low but not zero.
- Your password is never stored. Only the session file is, so don't share `session.json`.
