#!/usr/bin/env python3
"""
Instagram: unfollow everyone who doesn't follow you back.

How it works
  1. Opens a browser window on instagram.com. You log in there like normal.
     The login is remembered (in the browser_profile folder) for next time.
  2. Reads your "following" and "followers" lists through Instagram's own
     website API, the same calls the site makes when you scroll those lists.
  3. Unfollows everyone who doesn't follow you back, 30-40 seconds apart,
     and keeps going until nobody is left.

Usage (after `pip install -r requirements.txt`):
    python unfollow.py                  # shows the list, asks before unfollowing
    python unfollow.py --dry-run        # only shows the list, unfollows nobody
    python unfollow.py --yes            # skips the confirmation prompt
    python unfollow.py --max 50         # optional: stop after 50 this run
    python unfollow.py --keep-verified  # never unfollow blue-check accounts

Accounts listed in whitelist.txt (one username per line) are never unfollowed.
"""

import argparse
import itertools
import json
import os
import random
import sys
import threading
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright is not installed. Run:  pip install -r requirements.txt")
    sys.exit(1)

HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / "browser_profile"
WHITELIST_FILE = HERE / "whitelist.txt"
REPORT_FILE = HERE / "not_following_back.txt"

IG = os.environ.get("IG_BASE_URL", "https://www.instagram.com").rstrip("/")  # env is test-only
IG_APP_ID = "936619743392459"  # the id the instagram.com website itself sends

# Random wait between each unfollow, in seconds.
MIN_DELAY = 30
MAX_DELAY = 40

# If Instagram rate-limits us, wait this long and then keep going.
# Doubles on each repeat hit, up to the max.
BACKOFF_START = 10 * 60
BACKOFF_MAX = 2 * 60 * 60

# Pause between list pages while fetching following/followers.
PAGE_PAUSE = (0.3, 0.8)


# --------------------------------------------------------------------------
# Terminal helpers
# --------------------------------------------------------------------------

class Spinner:
    """Animated 'Doing something.  ..  ...' line so the script never looks frozen.

    Use as a context manager. `label` can be a string or a function returning
    the current text (handy for countdowns).
    """

    FRAMES = [".", "..", "..."]

    def __init__(self, label, interval=0.4):
        self.label = label
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._width = 0

    def _text(self):
        return self.label() if callable(self.label) else self.label

    def _run(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                return
            line = f"{self._text()}{frame}"
            pad = max(self._width - len(line), 0)
            sys.stdout.write("\r" + line + " " * pad)
            sys.stdout.flush()
            self._width = max(self._width, len(line))
            self._stop.wait(self.interval)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        sys.stdout.write("\r" + " " * self._width + "\r")
        sys.stdout.flush()
        return False


def countdown(seconds, label):
    """Sleep `seconds` while showing e.g. 'Next unfollow in 34s...'."""
    end = time.time() + seconds

    def text():
        left = max(int(round(end - time.time())), 0)
        return f"{label} {left}s"

    with Spinner(text):
        while time.time() < end:
            time.sleep(0.2)


def load_whitelist():
    if not WHITELIST_FILE.exists():
        return set()
    names = set()
    for line in WHITELIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip().lstrip("@").lower()
        if line and not line.startswith("#"):
            names.add(line)
    return names


# --------------------------------------------------------------------------
# Instagram web API, driven through a real browser
# --------------------------------------------------------------------------

class LoginRequired(Exception):
    pass


class CheckpointRequired(Exception):
    def __init__(self, url=None):
        super().__init__(url)
        self.url = url


class RateLimited(Exception):
    pass


class BrowserClosed(RuntimeError):
    pass


JS_FETCH = """
async ({url, method, body, csrf}) => {
  const headers = {
    "x-ig-app-id": "%s",
    "x-csrftoken": csrf,
    "x-requested-with": "XMLHttpRequest",
    "x-instagram-ajax": "1",
    "x-asbd-id": "129477",
  };
  const opts = {method, headers, credentials: "include"};
  if (body) {
    headers["content-type"] = "application/x-www-form-urlencoded";
    opts.body = body;
  }
  const r = await fetch(url, opts);
  return {status: r.status, text: await r.text()};
}
""" % IG_APP_ID


class InstagramWeb:
    def __init__(self, profile_dir, headless=False):
        self.profile_dir = Path(profile_dir)
        self.headless = headless
        self._pw = None
        self.context = None
        self.page = None
        self.user_id = None
        self.username = None

    # -- browser lifecycle -------------------------------------------------

    def start(self):
        self.profile_dir.mkdir(exist_ok=True)
        self._pw = sync_playwright().start()
        errors = []
        # Prefer a browser that's already on the PC (Chrome, then Edge, which
        # every Windows machine has), otherwise Playwright's own Chromium.
        # IG_BROWSER=<path to a chrome/chromium exe> forces a specific one.
        custom = os.environ.get("IG_BROWSER")
        channels = ["custom"] if custom else ["chrome", "msedge", None]
        for channel in channels:
            kwargs = dict(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                ignore_default_args=["--enable-automation"],
                chromium_sandbox=(os.geteuid() != 0) if hasattr(os, "geteuid") else True,
                no_viewport=not self.headless,
                # only for automated tests behind an intercepting proxy
                ignore_https_errors=bool(os.environ.get("IG_IGNORE_TLS")),
            )
            if channel == "custom":
                kwargs["executable_path"] = custom
            elif channel:
                kwargs["channel"] = channel
            try:
                self.context = self._pw.chromium.launch_persistent_context(**kwargs)
                break
            except Exception as e:  # noqa: BLE001
                errors.append(f"  {channel or 'chromium'}: {str(e).splitlines()[0]}")
        if self.context is None:
            self._pw.stop()
            raise RuntimeError(
                "Could not start a browser. Tried:\n" + "\n".join(errors) +
                "\n\nFix: run this once in the script folder and try again:\n"
                "    venv\\Scripts\\playwright install chromium      (Windows)\n"
                "    venv/bin/playwright install chromium           (Mac/Linux)"
            )
        # Plain Chrome reports navigator.webdriver as undefined; Playwright's build sets
        # it to true. Put it back to normal, without the command-line flag that makes
        # Chrome/Edge show a yellow "unsupported flag" banner.
        self.context.add_init_script(
            "Object.defineProperty(Navigator.prototype, 'webdriver', {get: () => undefined});"
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(60_000)

    def close(self):
        try:
            if self.context:
                self.context.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass

    def _check_open(self):
        if self.page is None or self.page.is_closed():
            raise BrowserClosed("The browser window was closed. Run the script again.")

    def _goto(self, url):
        self._check_open()
        last = None
        for attempt in range(3):
            try:
                self.page.goto(url, wait_until="domcontentloaded")
                return
            except Exception as e:  # noqa: BLE001
                last = str(e).splitlines()[0]
                if "Timeout" in last and self.page.url.startswith(IG):
                    return  # page is slow but we're on instagram.com, which is all we need
                time.sleep(3 * (attempt + 1))
        if "RESPONSE_CODE_FAILURE" in last or "429" in last:
            raise RuntimeError(
                "Instagram is refusing connections from your network right now "
                "(too many requests). Wait 15-30 minutes and try again. "
                "VPNs and shared/office networks trigger this a lot."
            )
        raise RuntimeError(f"Could not open {url}: {last}")

    # -- cookies / login ---------------------------------------------------

    def _cookie(self, name):
        for c in self.context.cookies(IG):
            if c["name"] == name and c["value"]:
                return c["value"]
        return None

    def _has_session_cookies(self):
        return bool(self._cookie("sessionid")) and bool(self._cookie("ds_user_id"))

    def _session_is_valid(self):
        self.user_id = self._cookie("ds_user_id")
        try:
            status, data, _ = self.api("GET", f"friendships/{self.user_id}/following/?count=1")
        except LoginRequired:
            return False
        return status == 200 and isinstance(data, dict) and data.get("status") == "ok"

    def _wait_for_checkpoint(self, url=None):
        print("\nInstagram is showing a security check (for example \"Your email may not be "
              "secure\"). This happens on logins from a new device, and it is a one-time thing.")
        print("Complete it in the browser window, then come back here.")
        target = url if url and url.startswith("http") else IG + (url or "/")
        try:
            self._goto(target)
        except RuntimeError:
            pass
        input("Press Enter once you've done that... ")

    def _wait_for_login_cookies(self):
        self.context.clear_cookies()
        self._goto(IG + "/accounts/login/")
        print()
        with Spinner("Log in to Instagram in the browser window that just opened. Waiting for you"):
            while not self._has_session_cookies():
                self._check_open()
                time.sleep(1)
        time.sleep(2)  # let the post-login redirect settle

    def ensure_logged_in(self):
        self._goto(IG + "/")
        if not self._has_session_cookies():
            self._wait_for_login_cookies()
        while True:
            try:
                valid = self._session_is_valid()
            except CheckpointRequired as e:
                self._wait_for_checkpoint(e.url)
                continue
            if valid:
                self._fetch_username()
                return
            # cookies exist but Instagram doesn't accept them: log in again
            self._wait_for_login_cookies()

    def _fetch_username(self):
        for path in (f"users/{self.user_id}/info/", "accounts/edit/web_form_data/"):
            try:
                _, data, _ = self.api("GET", path)
                name = (data or {}).get("user", {}).get("username") or \
                       (data or {}).get("form_data", {}).get("username")
                if name:
                    self.username = name
                    return
            except Exception:  # noqa: BLE001
                continue

    # -- low level request -------------------------------------------------

    def api(self, method, path, body=None):
        """Call https://www.instagram.com/api/v1/<path> from inside the page.

        Returns (http_status, parsed_json_or_None, raw_text).
        Raises LoginRequired / CheckpointRequired / RateLimited when Instagram says so.
        """
        self._check_open()
        url = f"{IG}/api/v1/{path}"
        payload = {"url": url, "method": method, "body": body, "csrf": self._cookie("csrftoken") or ""}
        last_err = None
        for _ in range(3):
            # fetch() only works from a page on instagram.com itself
            if not (self.page.url or "").startswith(IG):
                self._goto(IG + "/")
            try:
                res = self.page.evaluate(JS_FETCH, payload)
                break
            except Exception as e:  # noqa: BLE001  (page navigated mid-call, etc.)
                last_err = str(e).splitlines()[0]
                time.sleep(1)
        else:
            raise RuntimeError(f"Browser request failed: {last_err}")

        status, text = res["status"], res["text"]
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        msg = str((data or {}).get("message", "")).lower() if isinstance(data, dict) else ""

        if msg == "login_required" or status == 401:
            raise LoginRequired()
        if msg in ("checkpoint_required", "challenge_required") or \
                (isinstance(data, dict) and data.get("checkpoint_url")):
            raise CheckpointRequired((data or {}).get("checkpoint_url"))
        if status == 429 or msg == "feedback_required" or "wait a few minutes" in msg or \
                (isinstance(data, dict) and data.get("spam")):
            d = data if isinstance(data, dict) else {}
            raise RateLimited(d.get("feedback_message") or d.get("message") or f"HTTP {status}")
        if status == 403 and data is None:
            raise LoginRequired()
        return status, data, text

    # -- high level --------------------------------------------------------

    def get_list(self, kind, on_progress=None):
        """kind = 'following' or 'followers'. Returns {pk: user_dict}."""
        users = {}
        max_id = ""
        page_sizes = [200, 100, 50, 25]
        while True:
            extra = "&search_surface=follow_list_page" if kind == "followers" else ""
            data = None
            for size in list(page_sizes):
                path = f"friendships/{self.user_id}/{kind}/?count={size}{extra}"
                if max_id:
                    path += f"&max_id={max_id}"
                status, data, text = self.api("GET", path)
                if status == 200 and isinstance(data, dict) and "users" in data:
                    break
                # Instagram didn't like that page size, try a smaller one.
                page_sizes.remove(size)
                data = None
            if data is None:
                raise RuntimeError(f"Could not read your {kind} list (HTTP {status}): {text[:200]}")
            for u in data.get("users", []):
                users[str(u.get("pk") or u.get("pk_id") or u.get("id"))] = u
            if on_progress:
                on_progress(len(users))
            max_id = data.get("next_max_id")
            if not max_id or not data.get("users"):
                break
            time.sleep(random.uniform(*PAGE_PAUSE))
        return users

    def unfollow(self, pk):
        status, data, text = self.api("POST", f"friendships/destroy/{pk}/", body=f"user_id={pk}")
        if status == 200 and isinstance(data, dict) and data.get("status") == "ok":
            return True
        raise RuntimeError(f"HTTP {status}: {text[:200]}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def fetch_lists(ig):
    fetch_lists.n = 0
    with Spinner(lambda: f"Fetching who you follow ({fetch_lists.n} so far)"):
        following = ig.get_list("following", on_progress=lambda n: setattr(fetch_lists, "n", n))
    print(f"You follow {len(following)} accounts")
    fetch_lists.n = 0
    with Spinner(lambda: f"Fetching your followers ({fetch_lists.n} so far)"):
        followers = ig.get_list("followers", on_progress=lambda n: setattr(fetch_lists, "n", n))
    print(f"{len(followers)} accounts follow you")
    return following, followers


def run(ig, args, whitelist):
    with Spinner("Starting browser"):
        ig.start()
    print("Browser started")
    ig.ensure_logged_in()
    print(f"Logged in as @{ig.username}" if ig.username else "Logged in")
    print()

    while True:
        try:
            following, followers = fetch_lists(ig)
            break
        except CheckpointRequired as e:
            ig._wait_for_checkpoint(e.url)
        except LoginRequired:
            print("Instagram logged you out. Please log in again in the browser window.")
            ig.ensure_logged_in()

    targets = []
    for pk, u in following.items():
        if pk in followers:
            continue
        if u.get("username", "").lower() in whitelist:
            continue
        if args.keep_verified and u.get("is_verified"):
            continue
        targets.append(u)
    targets.sort(key=lambda u: u.get("username", "").lower())

    REPORT_FILE.write_text("\n".join(u.get("username", "") for u in targets) + "\n", encoding="utf-8")

    print()
    print(f"{len(targets)} account(s) you follow don't follow you back:")
    for u in targets:
        flag = " (verified)" if u.get("is_verified") else ""
        print(f"  @{u.get('username')}{flag}")
    print(f"\nFull list saved to {REPORT_FILE.name}")

    if not targets:
        print("Nothing to do.")
        return

    if args.dry_run:
        print("\nDry run, nobody was unfollowed.")
        return

    batch = targets[: args.max] if args.max > 0 else targets
    if len(batch) < len(targets):
        print(f"\nWill unfollow {len(batch)} of them this run (--max {args.max}). "
              f"Run the script again later for the rest.")

    if not args.yes:
        answer = input(f"\nUnfollow {len(batch)} account(s)? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return

    est_minutes = len(batch) * (MIN_DELAY + MAX_DELAY) / 2 / 60
    print(f"\nStarting. Waiting {MIN_DELAY}-{MAX_DELAY}s between each unfollow, "
          f"about {est_minutes:.0f} minutes total if Instagram doesn't slow us down. "
          f"Leave the browser window open (minimized is fine). Press Ctrl+C to stop any time.\n")

    done = 0
    backoff = BACKOFF_START
    i = 0
    while i < len(batch):
        u = batch[i]
        name = u.get("username")
        try:
            with Spinner(f"[{i + 1}/{len(batch)}] unfollowing @{name}"):
                ig.unfollow(str(u.get("pk") or u.get("pk_id")))
        except RateLimited as e:
            print(f"Instagram is rate-limiting you ({e}).")
            countdown(backoff, "Waiting it out, then continuing. Resuming in")
            backoff = min(backoff * 2, BACKOFF_MAX)
            continue  # retry the same account
        except LoginRequired:
            print("Instagram logged you out. Please log in again in the browser window.")
            ig.ensure_logged_in()
            continue
        except CheckpointRequired as e:
            ig._wait_for_checkpoint(e.url)
            continue
        except BrowserClosed:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[{i + 1}/{len(batch)}] could not unfollow @{name}: {e}")
            i += 1
            continue

        backoff = BACKOFF_START
        done += 1
        i += 1
        print(f"[{i}/{len(batch)}] unfollowed @{name}")
        if i < len(batch):
            countdown(random.uniform(MIN_DELAY, MAX_DELAY), "Next unfollow in")

    print(f"\nDone. Unfollowed {done} account(s).")
    remaining = len(targets) - done
    if remaining > 0:
        print(f"{remaining} still don't follow you back. Run the script again to continue.")


def main():
    parser = argparse.ArgumentParser(description="Unfollow Instagram accounts that don't follow you back.")
    parser.add_argument("--dry-run", action="store_true", help="only list accounts, don't unfollow")
    parser.add_argument("--yes", "-y", action="store_true", help="don't ask for confirmation")
    parser.add_argument("--max", type=int, default=0,
                        help="stop after this many unfollows (default: no limit, keeps going until done)")
    parser.add_argument("--keep-verified", action="store_true",
                        help="don't unfollow verified (blue check) accounts")
    args = parser.parse_args()

    whitelist = load_whitelist()
    if whitelist:
        print(f"Whitelist loaded: {len(whitelist)} account(s) will be kept.")

    ig = InstagramWeb(PROFILE_DIR)
    try:
        run(ig, args, whitelist)
    except KeyboardInterrupt:
        print("\nStopped by you. Run the script again any time to continue.")
    except RuntimeError as e:
        print(f"\nError: {e}")
        return 1
    finally:
        ig.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
