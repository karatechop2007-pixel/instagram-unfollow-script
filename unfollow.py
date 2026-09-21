#!/usr/bin/env python3
"""
Instagram "unfollow everyone who doesn't follow me back" script.

Usage (after `pip install -r requirements.txt`):

    python unfollow.py               # shows the list, asks before unfollowing
    python unfollow.py --dry-run     # only shows the list, unfollows nobody
    python unfollow.py --yes         # skips the confirmation prompt
    python unfollow.py --max 50      # unfollow at most 50 accounts this run

The first run asks for your username and password and saves a session to
session.json so later runs don't need to log in again.

Accounts listed in whitelist.txt (one username per line) are never unfollowed.
"""

import argparse
import getpass
import os
import random
import sys
import time
from pathlib import Path

try:
    from instagrapi import Client
    from instagrapi.exceptions import (
        BadPassword,
        ChallengeRequired,
        FeedbackRequired,
        LoginRequired,
        PleaseWaitFewMinutes,
        RateLimitError,
        TwoFactorRequired,
    )
except ImportError:
    print("instagrapi is not installed. Run:  pip install -r requirements.txt")
    sys.exit(1)

HERE = Path(__file__).resolve().parent
SESSION_FILE = HERE / "session.json"
WHITELIST_FILE = HERE / "whitelist.txt"
REPORT_FILE = HERE / "not_following_back.txt"

# Delay between unfollows, in seconds. Instagram temporarily blocks accounts
# that unfollow too fast, so keep these generous.
MIN_DELAY = 30
MAX_DELAY = 90
DEFAULT_MAX_PER_RUN = 100


def load_whitelist() -> set:
    if not WHITELIST_FILE.exists():
        return set()
    names = set()
    for line in WHITELIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip().lstrip("@").lower()
        if line and not line.startswith("#"):
            names.add(line)
    return names


def login() -> Client:
    cl = Client()
    cl.delay_range = [2, 5]  # small random pause between API calls

    username = os.environ.get("IG_USERNAME") or input("Instagram username: ").strip()
    password = os.environ.get("IG_PASSWORD") or getpass.getpass("Instagram password: ")

    if SESSION_FILE.exists():
        try:
            cl.load_settings(SESSION_FILE)
            cl.login(username, password)
            cl.get_timeline_feed()  # verifies the saved session still works
            print("Logged in using saved session.")
            return cl
        except Exception:
            print("Saved session no longer valid, logging in fresh...")
            cl = Client()
            cl.delay_range = [2, 5]

    try:
        cl.login(username, password)
    except TwoFactorRequired:
        code = input("Two-factor code from your authenticator app / SMS: ").strip()
        cl.login(username, password, verification_code=code)
    except BadPassword:
        print("Wrong username or password.")
        sys.exit(1)
    except ChallengeRequired:
        print(
            "Instagram wants you to verify it's you. Open the Instagram app, "
            "approve the login / 'It was me' prompt, then run this script again."
        )
        sys.exit(1)

    cl.dump_settings(SESSION_FILE)
    print(f"Logged in. Session saved to {SESSION_FILE.name}.")
    return cl


def fetch_lists(cl: Client):
    me = cl.user_id
    print("Fetching who you follow... (can take a minute for big accounts)")
    following = cl.user_following(me, amount=0)
    print(f"  you follow {len(following)} accounts")
    print("Fetching your followers...")
    followers = cl.user_followers(me, amount=0)
    print(f"  {len(followers)} accounts follow you")
    return following, followers


def main() -> int:
    parser = argparse.ArgumentParser(description="Unfollow Instagram accounts that don't follow you back.")
    parser.add_argument("--dry-run", action="store_true", help="only list accounts, don't unfollow")
    parser.add_argument("--yes", "-y", action="store_true", help="don't ask for confirmation")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX_PER_RUN,
                        help=f"max accounts to unfollow this run (default {DEFAULT_MAX_PER_RUN})")
    parser.add_argument("--keep-verified", action="store_true",
                        help="don't unfollow verified (blue check) accounts")
    args = parser.parse_args()

    whitelist = load_whitelist()
    if whitelist:
        print(f"Whitelist loaded: {len(whitelist)} account(s) will be kept.")

    cl = login()
    following, followers = fetch_lists(cl)

    targets = []
    for pk, user in following.items():
        if pk in followers:
            continue
        if user.username.lower() in whitelist:
            continue
        if args.keep_verified and user.is_verified:
            continue
        targets.append(user)
    targets.sort(key=lambda u: u.username.lower())

    REPORT_FILE.write_text("\n".join(u.username for u in targets) + "\n", encoding="utf-8")

    print()
    print(f"{len(targets)} account(s) you follow don't follow you back:")
    for u in targets:
        flag = " (verified)" if u.is_verified else ""
        print(f"  @{u.username}{flag}")
    print(f"\nFull list saved to {REPORT_FILE.name}")

    if not targets:
        print("Nothing to do.")
        return 0

    if args.dry_run:
        print("\nDry run, nobody was unfollowed.")
        return 0

    batch = targets[: args.max]
    if len(batch) < len(targets):
        print(f"\nWill unfollow {len(batch)} of them this run (--max {args.max}). "
              f"Run the script again later for the rest.")

    if not args.yes:
        answer = input(f"\nUnfollow {len(batch)} account(s)? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return 0

    est_minutes = len(batch) * (MIN_DELAY + MAX_DELAY) / 2 / 60
    print(f"\nStarting. Waiting {MIN_DELAY}-{MAX_DELAY}s between each unfollow, "
          f"about {est_minutes:.0f} minutes total. Press Ctrl+C to stop any time.\n")

    done = 0
    try:
        for i, u in enumerate(batch, 1):
            try:
                ok = cl.user_unfollow(u.pk)
            except (PleaseWaitFewMinutes, RateLimitError, FeedbackRequired) as e:
                print(f"\nInstagram is rate-limiting you ({e.__class__.__name__}). "
                      f"Stopping now. Wait a few hours and run the script again.")
                break
            except LoginRequired:
                print("\nSession expired. Delete session.json and run again.")
                break
            except Exception as e:  # noqa: BLE001
                print(f"[{i}/{len(batch)}] could not unfollow @{u.username}: {e}")
                continue

            if ok:
                done += 1
                print(f"[{i}/{len(batch)}] unfollowed @{u.username}")
            else:
                print(f"[{i}/{len(batch)}] Instagram refused to unfollow @{u.username}")

            if i < len(batch):
                time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    except KeyboardInterrupt:
        print("\nStopped by you.")

    print(f"\nDone. Unfollowed {done} account(s).")
    remaining = len(targets) - done
    if remaining > 0:
        print(f"{remaining} still don't follow you back. Run the script again to continue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
