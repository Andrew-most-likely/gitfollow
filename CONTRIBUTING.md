# Contributing to GitFollow

Thanks for your interest in contributing!

## Reporting bugs

Use the [Bug Report](https://github.com/Andrew-most-likely/gitfollow/issues/new?template=bug_report.yml) issue template. Include your OS, version, and the relevant output from the log window.

## Suggesting features

Use the [Feature Request](https://github.com/Andrew-most-likely/gitfollow/issues/new?template=feature_request.yml) template. Check open issues first to avoid duplicates.

## Pull requests

1. Fork the repo and create a branch from `master`
2. Keep changes focused — one feature or fix per PR
3. Test with `python gui.py` before submitting
4. The exe is built automatically by CI on tag push — no need to include a built binary

## Project structure

| File | Purpose |
|------|---------|
| `gui.py` | Tkinter desktop UI — all pages, navigation, threading |
| `gitfollow.py` | Core follow/unfollow logic, GitHub API calls, state management |
| `data/state.json` | Local state (gitignored) — follow history, quality cache, stats |
| `.env` | Credentials (gitignored) — GH_TOKEN, GH_USERNAME, and settings |
| `.github/workflows/build-exe.yml` | PyInstaller build + release pipeline |

## Running from source

```bash
pip install -r requirements.txt
cp .env.example .env   # add your token and username
python gui.py
```
