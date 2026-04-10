# GitFollow

> A GitHub community discovery tool. Find and connect with active developers who share your interests.

[![Build](https://github.com/Andrew-most-likely/gitfollow/actions/workflows/build-exe.yml/badge.svg)](https://github.com/Andrew-most-likely/gitfollow/actions/workflows/build-exe.yml)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/Andrew-most-likely/gitfollow)](https://github.com/Andrew-most-likely/gitfollow/releases/latest)

<img width="958" height="665" alt="image" src="https://github.com/user-attachments/assets/22641d3c-2742-4133-ab60-8d10c1ba6225" />

GitFollow helps you discover and connect with active GitHub developers. It identifies real, recently active users who are likely to engage with your work, follows them on your behalf, and cleans up connections that never became mutual. All API usage is rate-limited, politely delayed, and fully identified to GitHub via a proper User-Agent header in compliance with the [GitHub API Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service).

---

## Features

- **Smart candidate sourcing** -searches GitHub for real users with followers and recent repos, not random IDs
- **Activity filtering** -skips anyone who hasn't pushed a commit in the last 30 days
- **Org/bot detection** -never follows organizations or accounts flagged as non-users
- **Auto-unfollow** -unfollows non-reciprocators after a configurable time window
- **Quality cleanup** -optional weekly pass to unfollow existing follows that have gone inactive
- **Quality cache** -remembers check results for 7 days to minimize API usage on repeat runs
- **Desktop GUI** -setup wizard, live stats dashboard, and run controls -no terminal needed

---

## Getting Started

### Option 1 -Download the GUI (easiest, no Python needed)

1. Go to [**Releases**](https://github.com/Andrew-most-likely/gitfollow/releases) and download `GitFollow.exe`
2. Double-click it -no install required
3. Open the **Settings** tab, enter your GitHub token and username, click **Save Settings**
4. Open the **Setup** tab and click **Re-check** to confirm everything is ready
5. Click **Run → Run Follow** to start

> **Need a token?** Click the "Create GitHub Token →" button in the Setup tab, or go to
> [github.com/settings/tokens](https://github.com/settings/tokens/new?scopes=user%3Afollow&description=GitFollow)
> Only the `user:follow` scope is required.

---

### Option 2 -Run from source

```bash
git clone https://github.com/Andrew-most-likely/gitfollow
cd gitfollow
pip install -r requirements.txt
cp .env.example .env        # fill in your token and username
python gui.py               # launch the GUI
# or headless:
python gitfollow.py
```

---

## Configuration

All settings are available in the GUI Settings tab. When running headlessly, set them as environment variables or in a `.env` file.

| Variable | Default | Description |
|----------|---------|-------------|
| `GH_TOKEN` | **required** | GitHub personal access token (`user:follow` scope) |
| `GH_USERNAME` | **required** | Your GitHub username |
| `FOLLOW_LIMIT` | `150` | Max new follows per run. Keep at or below 150/day for responsible use. |
| `UNFOLLOW_HOURS` | `24` | Hours before unfollowing a non-reciprocator |
| `ACTIVITY_DAYS` | `30` | Max days since last commit to consider a user active |
| `MIN_FOLLOWERS` | `1` | Minimum follower count a candidate must have |
| `CACHE_DAYS` | `7` | Days to cache quality check results |
| `QUALITY_UNFOLLOW` | `false` | Set to `true` to unfollow existing follows failing quality criteria |
| `WHITELIST` | -| Comma-separated usernames to never unfollow |
| `STATE_FILE` | `data/state.json` | Path to the state file |

---

## How it works

### Follow pass (daily)
1. Queries GitHub search for real users with at least `MIN_FOLLOWERS` followers and at least one repo
2. For each candidate, checks their profile -skips orgs, users with too few followers, and profiles with no recent activity
3. Fetches the last 100 public events to confirm a `PushEvent` within `ACTIVITY_DAYS`
4. Caches the result for `CACHE_DAYS` days -repeated runs skip already-checked accounts entirely
5. Follows up to `FOLLOW_LIMIT` qualifying users with a polite delay between each

### Unfollow pass (daily, same run)
1. Checks every account followed through this tool
2. Unfollows anyone who hasn't followed back after `UNFOLLOW_HOURS` hours
3. Never unfollows mutual follows or whitelisted accounts

### Quality unfollow pass (weekly, opt-in)
1. Scans your entire following list against quality criteria
2. Unfollows orgs, inactive users, and users with no followers
3. Uses cached results -after the first run (which is slow) subsequent passes take minutes

---

## Scheduled workflows

| Workflow | Schedule | What it does |
|----------|----------|-------------|
| `build-exe.yml` | On tag push / manual | Builds `GitFollow.exe` and attaches to the release |

The workflow can be triggered manually from **Actions → Build Windows Exe → Run workflow**.

---

## Building the exe yourself

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name GitFollow --add-data "gitfollow.py;." gui.py
# Output: dist/GitFollow.exe
```

Or trigger the **Build Windows Exe** workflow from the Actions tab -the `.exe` is uploaded as a downloadable artifact.

---

## State file

`data/state.json` tracks:
- Every account followed through this tool (with timestamp and mutual status)
- Quality check cache (so accounts aren't re-evaluated every run)
- Lifetime stats (total followed, unfollowed, mutual)

The file is excluded from git (`.gitignore`) and never committed to the repo. State persists between runs via GitHub Actions cache.

---

## FAQ

**Does this comply with GitHub's Terms of Service?**
Automated follow/unfollow is explicitly covered by GitHub's [Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies) (Section 4 - spam and inauthentic activity) and the [Disrupting the Experience of Other Users](https://docs.github.com/en/site-policy/acceptable-use-policies/github-disrupting-the-experience-of-other-users) policy, which prohibits "starring and/or following accounts or repositories in large volume in a short period of time."

GitFollow does respect all rate limits, identifies itself via a proper `User-Agent` header, and targets only real active developers - but the core follow/unfollow mechanic still falls under those policies. Use it at your own risk and keep limits conservative.

**How long does the quality unfollow pass take on first run?**
Roughly 2 minutes of sleep time per 1,000 accounts (evaluation is read-only, uses a short 0.1s delay). Results are cached so subsequent weekly runs are near-instant.

**Can I use this on macOS or Linux?**
`gitfollow.py` and the GitHub Actions workflows work on any OS. The GUI (`gui.py`) also works cross-platform via Python. The pre-built `.exe` is Windows only -Mac/Linux users should run `python gui.py`.

**The token field is masked -how do I edit it?**
Clear the field and type your new token. The masking is display-only.
