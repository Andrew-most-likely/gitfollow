"""
GitFollow - Automated GitHub follow/unfollow tool.

Strategy:
  1. Unfollow anyone followed 24+ hours ago who hasn't followed back.
  2. Follow new users sourced from followers of configured target accounts.
  3. Commit updated state back to the repo (when run via GitHub Actions).

Required env vars:
  GH_TOKEN        - GitHub personal access token (user:follow scope)
  GH_USERNAME     - Your GitHub username

Optional env vars:
  FOLLOW_LIMIT    - Max new follows per run (default: 400)
  UNFOLLOW_HOURS  - Hours before unfollowing non-followers (default: 24)
  WHITELIST       - Comma-separated usernames to never unfollow
  STATE_FILE      - Path to state JSON file (default: data/state.json)
"""

import os
import json
import time
import random
import logging
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

TOKEN        = os.environ["GH_TOKEN"]
USERNAME     = os.environ["GH_USERNAME"]
FOLLOW_LIMIT = int(os.environ.get("FOLLOW_LIMIT", 400))
UNFOLLOW_HRS = int(os.environ.get("UNFOLLOW_HOURS", 24))
WHITELIST    = {u.strip().lower() for u in os.environ.get("WHITELIST", "").split(",") if u.strip()}
STATE_FILE   = Path(os.environ.get("STATE_FILE", "data/state.json"))

HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── State helpers ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"following": {}, "whitelist": [], "stats": {"followed": 0, "unfollowed": 0, "mutual": 0}}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    log.info("State saved → %s", STATE_FILE)

# ── GitHub API helpers ────────────────────────────────────────────────────────

def api_get(url: str, params: dict = None) -> requests.Response:
    """GET with automatic rate-limit back-off."""
    while True:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if resp.status_code == 429 or (resp.status_code == 403 and "rate limit" in resp.text.lower()):
            reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait  = max(reset - time.time(), 1)
            log.warning("Rate limited — sleeping %.0fs", wait)
            time.sleep(wait)
            continue
        return resp


def api_write(method: str, url: str) -> int:
    """PUT/DELETE with secondary rate-limit back-off."""
    while True:
        resp = requests.request(method, url, headers=HEADERS, timeout=30)
        if resp.status_code == 429 or (
            resp.status_code == 403 and (
                "rate limit" in resp.text.lower() or
                "secondary" in resp.text.lower()
            )
        ):
            retry_after = int(resp.headers.get("Retry-After", 60))
            log.warning("Secondary rate limit hit — sleeping %ds", retry_after)
            time.sleep(retry_after)
            continue
        return resp.status_code


def api_put(url: str) -> int:
    return api_write("PUT", url)


def api_delete(url: str) -> int:
    return api_write("DELETE", url)


def paginate(url: str, params: dict = None, max_pages: int = 10) -> list:
    """Collect all items from a paginated GitHub list endpoint."""
    items, page = [], 1
    p = {"per_page": 100, **(params or {})}
    while page <= max_pages:
        p["page"] = page
        resp = api_get(url, p)
        if resp.status_code != 200:
            break
        batch = resp.json()
        if not batch:
            break
        items.extend(batch)
        page += 1
    return items


def get_my_following() -> set:
    items = paginate(f"https://api.github.com/users/{USERNAME}/following", max_pages=50)
    return {u["login"].lower() for u in items}


def get_my_followers() -> set:
    items = paginate(f"https://api.github.com/users/{USERNAME}/followers", max_pages=50)
    return {u["login"].lower() for u in items}


def checks_remaining() -> int:
    resp = api_get("https://api.github.com/rate_limit")
    if resp.status_code == 200:
        return resp.json()["resources"]["core"]["remaining"]
    return 0


def is_bot_or_org(login: str) -> bool:
    """Quick heuristic — skip accounts that look like bots/orgs."""
    resp = api_get(f"https://api.github.com/users/{login}")
    if resp.status_code != 200:
        return True
    data = resp.json()
    if data.get("type", "User") != "User":
        return True
    # Skip zero-activity accounts
    if data.get("public_repos", 0) == 0 and data.get("followers", 0) == 0:
        return True
    return False

# ── Core logic ────────────────────────────────────────────────────────────────

def do_unfollows(state: dict, my_followers: set):
    """Unfollow people who haven't followed back after UNFOLLOW_HRS hours."""
    cutoff  = datetime.now(timezone.utc) - timedelta(hours=UNFOLLOW_HRS)
    to_drop = []

    for login, info in state["following"].items():
        if login.lower() in WHITELIST:
            continue
        if login.lower() in my_followers:
            # They followed back — mark mutual, keep following
            if not info.get("mutual"):
                info["mutual"] = True
                state["stats"]["mutual"] += 1
                log.info("Mutual follow: %s", login)
            continue
        followed_at = datetime.fromisoformat(info["followed_at"])
        if followed_at <= cutoff:
            to_drop.append(login)

    for login in to_drop:
        code = api_delete(f"https://api.github.com/user/following/{login}")
        if code in (204, 404):
            log.info("Unfollowed: %s", login)
            del state["following"][login]
            state["stats"]["unfollowed"] += 1
        else:
            log.warning("Unfollow failed for %s — HTTP %s", login, code)
        time.sleep(0.5)


def candidate_pool(already_in_state: set, my_following: set) -> list:
    """
    Pull users from GitHub's global user list starting at a random offset.
    Returns a shuffled list of logins not already tracked/followed.
    """
    skip = already_in_state | my_following | {USERNAME.lower()}
    candidates = []

    # GitHub's /users endpoint paginates by `since` (last seen user ID).
    # Start at a random ID so we don't always hit the same accounts.
    since = random.randint(0, 5_000_000)

    log.info("Fetching global users since id=%d …", since)
    # Each page returns up to 100 users; grab enough to fill the follow limit
    pages_needed = (FOLLOW_LIMIT // 100) + 3
    for _ in range(pages_needed):
        resp = api_get("https://api.github.com/users", {"since": since, "per_page": 100})
        if resp.status_code != 200:
            break
        batch = resp.json()
        if not batch:
            break
        for u in batch:
            login = u["login"].lower()
            if login not in skip:
                candidates.append(login)
                skip.add(login)
        since = batch[-1]["id"]

    random.shuffle(candidates)
    return candidates


def do_follows(state: dict, my_following: set, my_followers: set):
    """Follow up to FOLLOW_LIMIT new users."""
    already_tracked = set(state["following"].keys())
    pool = candidate_pool(already_tracked, my_following)

    followed = 0
    now_iso  = datetime.now(timezone.utc).isoformat()

    for login in pool:
        if followed >= FOLLOW_LIMIT:
            break
        if checks_remaining() < 50:
            log.warning("API quota nearly exhausted — stopping follows early")
            break

        # Skip if they already follow us (no point in the follow-back game)
        if login in my_followers:
            state["following"][login] = {"followed_at": now_iso, "mutual": True}
            state["stats"]["mutual"] += 1
            continue

        code = api_put(f"https://api.github.com/user/following/{login}")
        if code in (204, 200):
            log.info("[%d/%d] Followed: %s", followed + 1, FOLLOW_LIMIT, login)
            state["following"][login] = {"followed_at": now_iso, "mutual": False}
            state["stats"]["followed"] += 1
            followed += 1
        else:
            log.warning("Follow failed for %s — HTTP %s", login, code)

        # Polite delay — avoid secondary rate limits
        time.sleep(random.uniform(2.0, 4.0))

    log.info("Followed %d new users this run", followed)

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    log.info("=== GitFollow starting | user=%s ===", USERNAME)

    # Verify the token identity
    resp = api_get("https://api.github.com/user")
    if resp.status_code != 200:
        log.error("Token is invalid or unauthenticated — HTTP %s", resp.status_code)
        return
    authed_as = resp.json().get("login", "unknown")
    log.info("Token authenticated as: %s", authed_as)
    if authed_as.lower() != USERNAME.lower():
        log.error("Token user (%s) does not match GH_USERNAME (%s) — aborting", authed_as, USERNAME)
        return

    remaining = checks_remaining()
    log.info("API quota remaining: %d", remaining)
    if remaining < 100:
        log.error("Quota too low to proceed safely — aborting")
        return

    state      = load_state()
    my_following = get_my_following()
    my_followers = get_my_followers()

    log.info("Currently following=%d  followers=%d  tracked=%d",
             len(my_following), len(my_followers), len(state["following"]))

    # 1. Sync state: remove entries for accounts we're no longer following
    #    (manually unfollowed outside this tool)
    ghost_entries = [l for l in list(state["following"]) if l not in my_following]
    for l in ghost_entries:
        del state["following"][l]

    # 2. Unfollow non-reciprocators
    do_unfollows(state, my_followers)

    # 3. Follow new candidates
    do_follows(state, my_following, my_followers)

    # 4. Persist
    save_state(state)

    stats = state["stats"]
    log.info("=== Done | total_followed=%d  unfollowed=%d  mutual=%d ===",
             stats["followed"], stats["unfollowed"], stats["mutual"])


if __name__ == "__main__":
    main()
