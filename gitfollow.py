"""
GitFollow - Automated GitHub follow/unfollow tool.

Strategy:
  1. Unfollow anyone followed 24+ hours ago who hasn't followed back.
  2. Optionally unfollow existing follows that fail quality criteria (QUALITY_UNFOLLOW=true).
  3. Follow new users sourced via GitHub search, filtered by quality criteria.
  4. Commit updated state back to the repo (when run via GitHub Actions).

Quality criteria for a follow candidate:
  - Username must not match bot/mirror/archive/numeric-only patterns
  - Must be a regular User (not an Organization or bot)
  - Must have at least MIN_FOLLOWERS followers
  - Must have fewer than MAX_REPOS public repos (filters mass-forking bots)
  - following/followers ratio must be below MAX_FF_RATIO (filters follow-farmers)
  - Account must be at least MIN_ACCOUNT_AGE_DAYS old (filters throwaway accounts)
  - Must have at least one of: name, bio, or email set (filters unconfigured bots)
  - Must have pushed a commit within the last ACTIVITY_DAYS days

Quality check results are cached in state.json for CACHE_DAYS days to avoid
re-checking the same accounts on every run.

Required env vars:
  GH_TOKEN        - GitHub personal access token (user:follow scope)
  GH_USERNAME     - Your GitHub username

Optional env vars:
  FOLLOW_LIMIT      - Max new follows per run (default: 150)
  UNFOLLOW_HOURS    - Hours before unfollowing non-followers (default: 24)
  WHITELIST         - Comma-separated usernames to never unfollow
  STATE_FILE        - Path to state JSON file (default: data/state.json)
  ACTIVITY_DAYS        - Days of inactivity before skipping a candidate (default: 30)
  MIN_FOLLOWERS        - Minimum followers a candidate must have (default: 1)
  MAX_REPOS            - Skip accounts with more public repos than this (default: 500)
  MAX_FF_RATIO         - Skip accounts whose following/followers ratio exceeds this (default: 10.0)
  MIN_ACCOUNT_AGE_DAYS - Skip accounts newer than this many days (default: 30)
  CACHE_DAYS           - How long to cache quality check results (default: 7)
  QUALITY_UNFOLLOW     - Set to "true" to unfollow existing follows that fail quality criteria
  SEARCH_MIN_FOLLOWERS - Pre-filter search: min followers in query, avoids fetching ghost accounts (default: 10)
  SEARCH_MAX_FOLLOWERS - Pre-filter search: max followers in query, skips high-follower accounts unlikely to follow back (default: 1000)
"""

import os
import re
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
ACTIVITY_DAYS        = int(os.environ.get("ACTIVITY_DAYS", 30))
MIN_FOLLOWERS        = int(os.environ.get("MIN_FOLLOWERS", 1))
MAX_REPOS            = int(os.environ.get("MAX_REPOS", 500))
MAX_FF_RATIO         = float(os.environ.get("MAX_FF_RATIO", 10.0))
MIN_ACCOUNT_AGE_DAYS = int(os.environ.get("MIN_ACCOUNT_AGE_DAYS", 30))
CACHE_DAYS           = int(os.environ.get("CACHE_DAYS", 7))
QUALITY_UNFOLLOW     = os.environ.get("QUALITY_UNFOLLOW", "false").lower() == "true"
SEARCH_MIN_FOLLOWERS = int(os.environ.get("SEARCH_MIN_FOLLOWERS", 10))
SEARCH_MAX_FOLLOWERS = int(os.environ.get("SEARCH_MAX_FOLLOWERS", 1000))

# Bot-like username patterns: all-numeric, or keywords common in automated accounts
_BOT_NAME_RE = re.compile(r'^\d+$|[\-_]?(bot|mirror|backup|clone|archive|crawler|scraper)[\-_]?', re.I)

HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "GitFollow/2.0 (+https://github.com/Andrew-most-likely/gitfollow)",
}

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
    Free pre-checks run before any API call; profile checks use the single
    /users/{login} response; push-event check is the only extra API call.
    """
    # Free pre-check: bot-like username patterns (no API call)
    if _BOT_NAME_RE.search(login):
        return False, "bot-like username"

    resp = api_get(f"https://api.github.com/users/{login}")
    if resp.status_code != 200:
        return False, "profile fetch failed"
    data = resp.json()

    if data.get("type", "User") != "User":
        return False, "organization/bot"

    followers = data.get("followers", 0)
    if followers < MIN_FOLLOWERS:
        return False, f"fewer than {MIN_FOLLOWERS} followers"

    # Mass-forking / mirror bot: too many repos
    public_repos = data.get("public_repos", 0)
    if public_repos > MAX_REPOS:
        return False, f"too many repos ({public_repos})"

    # Follow-farmer: following far more people than follow them back
    following = data.get("following", 0)
    if followers == 0 and following > 50:
        return False, f"follow-farmer (following={following}, followers=0)"
    if followers > 0 and following / followers > MAX_FF_RATIO:
        return False, f"follow-farmer ratio {following}:{followers}"

    # Account too new: throwaway/spam accounts
    created_at_str = data.get("created_at", "")
    if created_at_str:
        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - created_at).days
        if age_days < MIN_ACCOUNT_AGE_DAYS:
            return False, f"account too new ({age_days}d old)"

    # No profile info: unconfigured / bot account
    if not any([data.get("name"), data.get("bio"), data.get("email")]):
        return False, "no profile info (name/bio/email all empty)"

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
    Pull candidates from two high-signal sources:
      1. Stargazers of popular repos in curated tech topics (primary).
         People who star real projects are almost always real developers.
      2. GitHub user search sorted by followers/repos (fallback).
         Never sorts by join date — that heavily favours brand-new bot accounts.
    """
    skip = already_in_state | my_following | {USERNAME.lower()}
    candidates = []
    target = FOLLOW_LIMIT * 4  # gather ~4× the limit so quality filter has room to work

    # ── Source 1: stargazers of popular repos in curated topics ───────────────
    topics = random.sample([
        "python", "javascript", "typescript", "rust", "go", "java",
        "machine-learning", "web-development", "open-source", "devops",
        "cli", "api", "data-science", "game-development", "security",
    ], k=3)

    for topic in topics:
        if stop_event.is_set():
            break
        if len(candidates) >= target:
            break

        log.info("Finding popular repos in topic: %s ...", topic)
        resp = api_get("https://api.github.com/search/repositories", {
            "q": f"topic:{topic} stars:>500",
            "sort": "stars",
            "order": "desc",
            "per_page": 5,
            "page": random.randint(1, 4),
        })
        if resp.status_code != 200:
            log.warning("Repo search failed for topic %s (%s)", topic, resp.status_code)
            time.sleep(1)
            continue

        repos = resp.json().get("items", [])
        time.sleep(1)

        for repo in repos:
            if stop_event.is_set():
                break
            if len(candidates) >= target:
                break
            full_name = repo["full_name"]
            log.info("Pulling stargazers from %s ...", full_name)
            # Pick a random page of stargazers so we don't always get the same early followers
            page = random.randint(1, max(1, repo["stargazers_count"] // 100))
            page = min(page, 400)  # API won't serve beyond page ~400
            resp2 = api_get(f"https://api.github.com/repos/{full_name}/stargazers", {
                "per_page": 100,
                "page": page,
            })
            if resp2.status_code != 200:
                time.sleep(1)
                continue
            for u in resp2.json():
                login = u["login"].lower()
                if login not in skip:
                    candidates.append(login)
                    skip.add(login)
            log.info("  Got %d candidates so far", len(candidates))
            time.sleep(1)

    # ── Source 2: user search fallback (no join-date sort — attracts new bots) ─
    if len(candidates) < target:
        sort, order = random.choice([
            ("repositories", "desc"),
            ("followers", "desc"),
            ("followers", "asc"),
        ])
        query = f"type:user followers:{SEARCH_MIN_FOLLOWERS}..{SEARCH_MAX_FOLLOWERS} repos:2..200"
        pages_needed = min(((target - len(candidates)) // 100) + 2, 10)
        log.info("User search fallback (sort=%s %s) ...", sort, order)
        for page in range(1, pages_needed + 1):
            if stop_event.is_set():
                break
            resp = api_get("https://api.github.com/search/users", {
                "q": query,
                "sort": sort,
                "order": order,
                "per_page": 100,
                "page": page,
            })
            if resp.status_code != 200:
                log.warning("User search returned %s", resp.status_code)
                break
            items = resp.json().get("items", [])
            if not items:
                break
            for u in items:
                login = u["login"].lower()
                if login not in skip:
                    candidates.append(login)
                    skip.add(login)
            log.info("Search page %d: %d total candidates", page, len(candidates))
            time.sleep(2)

    # ── Last resort: global /users list ───────────────────────────────────────
    if not candidates:
        since = random.randint(0, 5_000_000)
        log.info("Last-resort fallback to global /users since id=%d ...", since)
        for _ in range(5):
            if stop_event.is_set():
                break
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
            time.sleep(1)

    random.shuffle(candidates)
    log.info("Candidate pool ready: %d accounts", len(candidates))
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
    quota     = checks_remaining()
    log.info("Checking quality of %d candidates (quota=%d) ...", pool_size, quota)

    for login in pool:
        if stop_event.is_set():
            log.info("Stop requested - halting follow pass.")
            break
        if followed >= FOLLOW_LIMIT:
            break
        if checked % 50 == 0 and checked > 0:
            quota = checks_remaining()
        if quota < 50:
            log.warning("API quota nearly exhausted - stopping follows early")
            break

        # Skip if they already follow us (no point in the follow-back game)
        if login in my_followers:
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
    total = len(candidates)
    quota = checks_remaining()
    cache_hits = 0

    log.info("Scanning %d followed accounts for quality (quota=%d) ...", total, quota)

    # Phase 1: scan the full list, log each result, build to_drop
    for i, login in enumerate(candidates, 1):
        if stop_event.is_set():
            log.info("Stop requested - halting quality unfollow scan.")
            break
        if i % 50 == 1 and i > 1:
            quota = checks_remaining()
        if quota < 150:
            log.warning("API quota low - stopping quality-unfollow checks early")
            break

        was_cached = login in cache
        ok, reason = cached_quality_check(login, cache)
        if was_cached:
            cache_hits += 1

        if ok:
            log.info("  [%d/%d] Keeping %s (good quality)", i, total, login)
            time.sleep(0.1)
        else:
            log.info("  [%d/%d] Queued to unfollow %s: %s", i, total, login, reason)
            to_drop.append((login, reason))
            time.sleep(0.1)

    log.info(
        "Scan complete: evaluated=%d  cache_hits=%d  to_unfollow=%d",
        total, cache_hits, len(to_drop),
    )

    # Phase 2: unfollow the queued accounts
    unfollowed = 0
    for login, reason in to_drop:
        if stop_event.is_set():
            log.info("Stop requested - halting quality unfollow pass.")
            break
        code = api_delete(f"https://api.github.com/user/following/{login}")
        if code in (204, 404):
            log.info("Quality-unfollowed %s (%s)", login, reason)
            state["following"].pop(login, None)
            state["stats"]["unfollowed"] += 1
            unfollowed += 1
        else:
            log.warning("Quality-unfollow failed for %s -HTTP %s", login, code)
        time.sleep(0.5)

    log.info("Quality unfollow complete: unfollowed=%d", unfollowed)

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Configure root logger once — guard prevents duplicate handlers on module reload
    if not logging.root.handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)

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

    # Prune stale quality-cache entries so state.json doesn't grow forever
    cache = state.setdefault("quality_cache", {})
    cache_cutoff = datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS)
    stale = [k for k, v in cache.items()
             if datetime.fromisoformat(v["checked_at"]) < cache_cutoff]
    if stale:
        for k in stale:
            del cache[k]
        log.info("Pruned %d stale cache entries", len(stale))

    my_following = get_my_following()
    my_followers = get_my_followers()

    log.info("Currently following=%d  followers=%d  tracked=%d",
             len(my_following), len(my_followers), len(state["following"]))

    # 1. Sync state: remove entries for accounts we're no longer following
    #    (manually unfollowed outside this tool)
    ghost_entries = [l for l in list(state["following"]) if l not in my_following]
    for l in ghost_entries:
        del state["following"][l]

    # 1b. Backfill anyone followed outside the app (no timestamp yet)
    now_iso = datetime.now(timezone.utc).isoformat()
    backfilled = 0
    for login in my_following:
        if login not in state["following"]:
            state["following"][login] = {"followed_at": now_iso, "mutual": False}
            backfilled += 1
    if backfilled:
        log.info("Backfilled %d externally-followed accounts with current timestamp", backfilled)

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
