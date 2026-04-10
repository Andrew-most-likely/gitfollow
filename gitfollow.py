"""
GitFollow - Automated GitHub follow/unfollow tool.

Strategy:
  1. Unfollow anyone followed 24+ hours ago who hasn't followed back.
  2. Optionally unfollow existing follows that fail quality criteria (QUALITY_UNFOLLOW=true).
  3. Follow new users sourced via GitHub search, filtered by quality criteria.
  4. Commit updated state back to the repo (when run via GitHub Actions).

Quality criteria for a follow candidate:
  - Must be a regular User (not an Organization or bot)
  - Must have at least MIN_FOLLOWERS followers
  - Must have pushed a commit within the last ACTIVITY_DAYS days

Quality check results are cached in state.json for CACHE_DAYS days to avoid
re-checking the same accounts on every run.

Required env vars:
  GH_TOKEN        - GitHub personal access token (user:follow scope)
  GH_USERNAME     - Your GitHub username

Optional env vars:
  FOLLOW_LIMIT      - Max new follows per run (default: 400)
  UNFOLLOW_HOURS    - Hours before unfollowing non-followers (default: 24)
  WHITELIST         - Comma-separated usernames to never unfollow
  STATE_FILE        - Path to state JSON file (default: data/state.json)
  ACTIVITY_DAYS     - Days of inactivity before skipping a candidate (default: 30)
  MIN_FOLLOWERS     - Minimum followers a candidate must have (default: 1)
  CACHE_DAYS        - How long to cache quality check results (default: 7)
  QUALITY_UNFOLLOW  - Set to "true" to unfollow existing follows that fail quality criteria
"""

import os
import json
import time
import random
import logging
import threading
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

TOKEN        = os.environ["GH_TOKEN"]
USERNAME     = os.environ["GH_USERNAME"]
FOLLOW_LIMIT      = int(os.environ.get("FOLLOW_LIMIT", 150))
UNFOLLOW_HRS      = int(os.environ.get("UNFOLLOW_HOURS", 24))
WHITELIST         = {u.strip().lower() for u in os.environ.get("WHITELIST", "").split(",") if u.strip()}
STATE_FILE        = Path(os.environ.get("STATE_FILE", "data/state.json"))
ACTIVITY_DAYS     = int(os.environ.get("ACTIVITY_DAYS", 30))
MIN_FOLLOWERS     = int(os.environ.get("MIN_FOLLOWERS", 1))
CACHE_DAYS        = int(os.environ.get("CACHE_DAYS", 7))
QUALITY_UNFOLLOW  = os.environ.get("QUALITY_UNFOLLOW", "false").lower() == "true"

HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "GitFollow/1.5 (+https://github.com/Andrew-most-likely/gitfollow)",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Set by the GUI to request a graceful stop between operations.
# Reset to a fresh Event on each run via importlib.reload.
stop_event = threading.Event()

# ── State helpers ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "following": {},
        "whitelist": [],
        "quality_cache": {},
        "stats": {"followed": 0, "unfollowed": 0, "mutual": 0},
    }


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
            log.warning("Rate limited -sleeping %.0fs", wait)
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
            log.warning("Secondary rate limit hit -sleeping %ds", retry_after)
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


def is_quality_candidate(login: str) -> tuple:
    """
    Returns (True, "") if the user is worth following, else (False, reason).
    Criteria: real User (not Org), has at least MIN_FOLLOWERS followers, pushed
    a commit within the last ACTIVITY_DAYS days.
    """
    resp = api_get(f"https://api.github.com/users/{login}")
    if resp.status_code != 200:
        return False, "profile fetch failed"
    data = resp.json()

    if data.get("type", "User") != "User":
        return False, "organization/bot"

    if data.get("followers", 0) < MIN_FOLLOWERS:
        return False, f"fewer than {MIN_FOLLOWERS} followers"

    cutoff = datetime.now(timezone.utc) - timedelta(days=ACTIVITY_DAYS)

    # Fast path: profile updated_at older than cutoff means no activity -skip events fetch
    updated_at_str = data.get("updated_at", "")
    if updated_at_str:
        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        if updated_at < cutoff:
            return False, f"no activity in last {ACTIVITY_DAYS} days"

    # Confirm recent activity is a push (not just a profile edit)
    events = paginate(f"https://api.github.com/users/{login}/events/public", max_pages=1)
    for event in events:
        if event.get("type") == "PushEvent":
            ts = event.get("created_at", "")
            if ts:
                created_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if created_at >= cutoff:
                    return True, ""

    return False, f"no commits in last {ACTIVITY_DAYS} days"


def cached_quality_check(login: str, cache: dict) -> tuple:
    """
    Returns (ok, reason) from cache if fresh, otherwise calls is_quality_candidate
    and stores the result.
    """
    cache_cutoff = datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS)
    entry = cache.get(login)
    if entry:
        checked_at = datetime.fromisoformat(entry["checked_at"])
        if checked_at >= cache_cutoff:
            return entry["ok"], entry["reason"]

    ok, reason = is_quality_candidate(login)
    cache[login] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ok": ok,
        "reason": reason,
    }
    return ok, reason

# ── Core logic ────────────────────────────────────────────────────────────────

def do_unfollows(state: dict, my_followers: set):
    """Unfollow people who haven't followed back after UNFOLLOW_HRS hours."""
    cutoff  = datetime.now(timezone.utc) - timedelta(hours=UNFOLLOW_HRS)
    to_drop = []

    for login, info in state["following"].items():
        if login.lower() in WHITELIST:
            continue
        if login.lower() in my_followers:
            # They followed back -mark mutual, keep following
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
            log.warning("Unfollow failed for %s -HTTP %s", login, code)
        time.sleep(0.5)


def candidate_pool(already_in_state: set, my_following: set) -> list:
    """
    Pull candidates via GitHub user search, pre-filtered to users with followers
    and repos. Varies sort order each run for diversity.
    Falls back to the global /users list if search fails.
    """
    skip = already_in_state | my_following | {USERNAME.lower()}
    candidates = []

    # Vary sort order each run so we don't always get the same accounts
    sort, order = random.choice([
        ("joined", "desc"),
        ("joined", "asc"),
        ("repositories", "desc"),
        ("followers", "desc"),
    ])
    query = f"type:user followers:>={MIN_FOLLOWERS} repos:>=1"
    pages_needed = min((FOLLOW_LIMIT // 100) + 3, 10)  # Search API caps at 10 pages / 1000 results

    log.info("Searching for candidates (sort=%s order=%s) ...", sort, order)
    for page in range(1, pages_needed + 1):
        if stop_event.is_set():
            log.info("Stop requested - halting candidate search.")
            break
        log.info("Fetching search page %d/%d ...", page, pages_needed)
        resp = api_get("https://api.github.com/search/users", {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": 100,
            "page": page,
        })
        if resp.status_code != 200:
            log.warning("Search API returned %s - falling back to /users", resp.status_code)
            break
        items = resp.json().get("items", [])
        if not items:
            break
        before = len(candidates)
        for u in items:
            login = u["login"].lower()
            if login not in skip:
                candidates.append(login)
                skip.add(login)
        log.info("Page %d: %d new candidates (total so far: %d)", page, len(candidates) - before, len(candidates))
        time.sleep(2)  # Search API rate limit: 30 req/min authenticated

    # Fallback: global /users list if search yielded nothing
    if not candidates:
        since = random.randint(0, 5_000_000)
        log.info("Falling back to global users since id=%d …", since)
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
    pool  = candidate_pool(already_tracked, my_following)
    cache = state.setdefault("quality_cache", {})

    followed  = 0
    checked   = 0
    now_iso   = datetime.now(timezone.utc).isoformat()
    pool_size = len(pool)
    log.info("Checking quality of %d candidates ...", pool_size)

    for login in pool:
        if stop_event.is_set():
            log.info("Stop requested - halting follow pass.")
            break
        if followed >= FOLLOW_LIMIT:
            break
        if checks_remaining() < 50:
            log.warning("API quota nearly exhausted - stopping follows early")
            break

        # Skip if they already follow us (no point in the follow-back game)
        if login in my_followers:
            state["following"][login] = {"followed_at": now_iso, "mutual": True}
            state["stats"]["mutual"] += 1
            continue

        # Quality gate (cached)
        ok, reason = cached_quality_check(login, cache)
        checked += 1
        if not ok:
            log.info("  [%d/%d] Skipping %s: %s", checked, pool_size, login, reason)
            continue

        code = api_put(f"https://api.github.com/user/following/{login}")
        if code in (204, 200):
            log.info("[%d/%d] Followed: %s", followed + 1, FOLLOW_LIMIT, login)
            state["following"][login] = {"followed_at": now_iso, "mutual": False}
            state["stats"]["followed"] += 1
            followed += 1
        else:
            log.warning("Follow failed for %s -HTTP %s", login, code)

        # Polite delay -avoid secondary rate limits
        time.sleep(random.uniform(2.0, 4.0))

    log.info("Followed %d new users this run", followed)


def do_quality_unfollows(state: dict, my_following: set):
    """
    Unfollow accounts we currently follow that fail quality criteria:
    orgs/corporations, users with too few followers, or users inactive for
    more than ACTIVITY_DAYS days.  Mutual follows and whitelisted accounts
    are always skipped.  Results are cached to avoid redundant API calls.
    """
    cache = state.setdefault("quality_cache", {})
    to_drop = []
    candidates = [
        l for l in my_following
        if l not in WHITELIST and not state["following"].get(l, {}).get("mutual")
    ]
    quota = checks_remaining()
    cache_hits = 0

    for i, login in enumerate(candidates):
        if stop_event.is_set():
            log.info("Stop requested - halting quality unfollow pass.")
            break
        # Re-check quota every 50 users instead of every user
        if i % 50 == 0:
            quota = checks_remaining()
        if quota < 150:
            log.warning("API quota low -stopping quality-unfollow checks early")
            break

        # cached_quality_check skips the API entirely if a fresh result exists
        was_cached = login in cache
        ok, reason = cached_quality_check(login, cache)
        if was_cached:
            cache_hits += 1
        if not ok:
            to_drop.append((login, reason))

        # Read-only pass -no secondary rate limit risk, short sleep is fine
        time.sleep(0.1)

    log.info(
        "Quality unfollow: evaluated=%d  cache_hits=%d  queued_to_drop=%d",
        len(candidates), cache_hits, len(to_drop),
    )

    for login, reason in to_drop:
        code = api_delete(f"https://api.github.com/user/following/{login}")
        if code in (204, 404):
            log.info("Quality-unfollowed %s (%s)", login, reason)
            state["following"].pop(login, None)
            state["stats"]["unfollowed"] += 1
        else:
            log.warning("Quality-unfollow failed for %s -HTTP %s", login, code)
        time.sleep(0.5)

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    log.info("=== GitFollow starting | user=%s ===", USERNAME)

    # Verify the token identity
    resp = api_get("https://api.github.com/user")
    if resp.status_code != 200:
        log.error("Token is invalid or unauthenticated -HTTP %s", resp.status_code)
        return
    authed_as = resp.json().get("login", "unknown")
    log.info("Token authenticated as: %s", authed_as)
    if authed_as.lower() != USERNAME.lower():
        log.error("Token user (%s) does not match GH_USERNAME (%s) -aborting", authed_as, USERNAME)
        return

    remaining = checks_remaining()
    log.info("API quota remaining: %d", remaining)
    if remaining < 100:
        log.error("Quota too low to proceed safely -aborting")
        return

    state        = load_state()
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

    # 2b. Unfollow existing follows that fail quality criteria (opt-in)
    if QUALITY_UNFOLLOW:
        log.info("Quality-unfollow pass enabled (QUALITY_UNFOLLOW=true)")
        do_quality_unfollows(state, my_following)

    # 3. Follow new candidates
    do_follows(state, my_following, my_followers)

    # 4. Persist
    save_state(state)

    stats = state["stats"]
    log.info("=== Done | total_followed=%d  unfollowed=%d  mutual=%d ===",
             stats["followed"], stats["unfollowed"], stats["mutual"])


if __name__ == "__main__":
    main()
