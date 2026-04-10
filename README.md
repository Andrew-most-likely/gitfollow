# GitFollow

> Discover and connect with active GitHub developers who share your interests.

[![Build](https://github.com/Andrew-most-likely/gitfollow/actions/workflows/build-exe.yml/badge.svg)](https://github.com/Andrew-most-likely/gitfollow/actions/workflows/build-exe.yml)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/Andrew-most-likely/gitfollow)](https://github.com/Andrew-most-likely/gitfollow/releases/latest)

<img width="1906" height="1272" alt="Dashboard" src="https://github.com/user-attachments/assets/9dc5cc74-64f2-42df-989d-9bdf76813310" />

GitFollow is a desktop app that finds real, recently active GitHub developers in your areas of interest, follows them on your behalf, and automatically cleans up connections that never became mutual. Every candidate passes an 8-signal quality filter before being followed — no bots, no follow-farmers, no inactive accounts.

> **ToS notice:** Automated following falls under GitHub's [Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies). GitFollow respects all rate limits and identifies itself via a proper `User-Agent` header, but the follow/unfollow mechanic is still subject to those policies. Use conservatively and at your own risk.

---

## Quick Start

**Windows — no Python needed:**

1. Download `GitFollow.exe` from [**Releases**](https://github.com/Andrew-most-likely/gitfollow/releases/latest)
2. Double-click — no install required
3. Open **Settings**, enter your GitHub token and username, click **Save Settings**
4. Open **Setup** and click **Re-check** to confirm everything is ready
5. Click **Run → Run Follow**

> Need a token? Click **Create Token** in the Setup tab, or visit [github.com/settings/tokens](https://github.com/settings/tokens/new?scopes=user%3Afollow&description=GitFollow) — only the `user:follow` scope is required.

<img width="1906" height="1270" alt="Setup" src="https://github.com/user-attachments/assets/e5a78d6a-a70b-4c20-83bd-c5825c1b75b9" />

**macOS / Linux — run from source:**

```bash
git clone https://github.com/Andrew-most-likely/gitfollow
cd gitfollow
pip install -r requirements.txt
cp .env.example .env   # fill in GH_TOKEN and GH_USERNAME
python gui.py          # launch the desktop app
# or headless:
python gitfollow.py
```

---

## Features

- **Smart candidate sourcing** — pulls stargazers from popular repos in your chosen topics; people who star real projects are almost always real developers
- **8-signal quality filter** — screens every candidate before following (see below)
- **7-day quality cache** — results are stored locally so repeat runs skip already-checked accounts entirely, preserving API quota
- **Auto-unfollow** — unfollows non-reciprocators after a configurable window (default 24 hours)
- **Quality cleanup** — optional pass to unfollow existing follows that have gone inactive or botty
- **People tab** — browse your following and followers with timestamps, mutual status, and multi-select unfollow
- **Mutual follow tracking** — never unfollows someone who follows you back
- **Whitelist** — specific accounts that are always protected from unfollowing
- **Desktop GUI** — setup wizard, live stats dashboard, run controls, no terminal needed
- **Windows exe** — single download, zero Python required

---

## Quality Filtering

This is what separates GitFollow from simpler scripts. Before following anyone, every candidate is checked against 8 independent signals:

| Signal | What it catches |
|--------|----------------|
| Bot-like username pattern | All-numeric names, accounts with `bot`, `mirror`, `crawler`, `scraper` etc. |
| Account type | Organizations and GitHub-flagged bots are skipped |
| Minimum followers | Accounts with no social presence |
| Maximum repo count | Mass-forking mirror bots with hundreds of auto-cloned repos |
| Following/followers ratio | Follow-farmers who follow thousands but have few followers back |
| Minimum account age | Throwaway and spam accounts less than 30 days old |
| Profile completeness | Accounts with no name, bio, or email — almost always unconfigured bots |
| Recent push event | Confirms the account actually committed code recently — not just a profile edit |

Results are **cached for 7 days** in `state.json`. A quality-checked account is never re-evaluated until the cache expires, keeping API usage minimal on repeat runs.

---

## People Tab

Browse and manage your network without running a full pass.

- **Following** — full list with relative timestamps showing how long ago you followed each account
- **Followers** — everyone who follows you, with mutual accounts surfaced to the top
- **Multi-select unfollow** — checkboxes, Select All / Deselect All, confirm and unfollow in bulk
- **Paginated** — 50 accounts per page for fast rendering even with large lists
- Usernames are clickable links that open the GitHub profile in your browser

<img width="1904" height="1274" alt="Run" src="https://github.com/user-attachments/assets/b086a540-87de-4994-84f6-93ca448d7bde" />

---

## Configuration

All settings are available in the GUI Settings tab. When running headlessly, set them as environment variables or in a `.env` file.

| Variable | Default | Description |
|----------|---------|-------------|
| `GH_TOKEN` | **required** | GitHub personal access token (`user:follow` scope) |
| `GH_USERNAME` | **required** | Your GitHub username |
| `FOLLOW_LIMIT` | `150` | Max new follows per run. Keep at or below 150/day. |
| `UNFOLLOW_HOURS` | `24` | Hours before unfollowing a non-reciprocator |
| `ACTIVITY_DAYS` | `30` | Max days since last commit to consider a user active |
| `MIN_FOLLOWERS` | `1` | Minimum follower count a candidate must have |
| `MAX_REPOS` | `500` | Skip accounts with more public repos than this |
| `MAX_FF_RATIO` | `10.0` | Skip accounts whose following/followers ratio exceeds this |
| `MIN_ACCOUNT_AGE_DAYS` | `30` | Skip accounts newer than this many days |
| `CACHE_DAYS` | `7` | Days to cache quality check results |
| `QUALITY_UNFOLLOW` | `false` | Set to `true` to unfollow existing follows failing quality criteria |
| `WHITELIST` | — | Comma-separated usernames to never unfollow |
| `STATE_FILE` | `data/state.json` | Path to the state file |

---

## How it works

### Follow pass
1. Queries GitHub for popular repos in curated tech topics (python, rust, go, ML, etc.)
2. Pulls stargazers from those repos at random pages — avoiding the same early followers every run
3. Falls back to GitHub user search if the stargazer pool is thin
4. Runs every candidate through the 8-signal quality filter (with caching)
5. Follows up to `FOLLOW_LIMIT` qualifying users with a polite delay between each

### Unfollow pass (runs after follow)
1. Checks every account followed through this tool
2. Unfollows anyone who hasn't followed back after `UNFOLLOW_HOURS` hours
3. Never unfollows mutual follows or whitelisted accounts

### Quality unfollow pass (opt-in)
1. Scans your entire following list against quality criteria
2. Unfollows orgs, inactive accounts, and follow-farmers
3. Skips mutual follows and whitelisted accounts
4. Uses the cache — after the first run, subsequent passes take minutes not hours

---

## Building the exe yourself

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name GitFollow --add-data "gitfollow.py;." gui.py
# Output: dist/GitFollow.exe
```

Or trigger the **Build Windows Exe** workflow from the Actions tab — the `.exe` is attached to the release automatically.

---

## State file

`data/state.json` tracks:
- Every account followed through this tool (with timestamp and mutual status)
- Quality check cache (so accounts aren't re-evaluated every run)
- Lifetime stats (total followed, unfollowed, mutual)

The file is excluded from git and never committed to the repo.

---

## FAQ

**How long does the quality unfollow pass take on first run?**
Roughly 2 minutes per 1,000 accounts (0.1s delay between checks). Results are cached so subsequent passes are near-instant.

**Can I use this on macOS or Linux?**
`gitfollow.py` runs on any OS. The GUI (`gui.py`) also works cross-platform via Python. The pre-built `.exe` is Windows only.

**The token field is masked — how do I edit it?**
Clear the field and type your new token. The masking is display-only.

**Does the app need to stay open while running?**
Yes — the current version runs locally. Close the window and the run stops. Use the Stop button for a clean halt.
