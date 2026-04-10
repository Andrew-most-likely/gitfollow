"""
GitFollow GUI — Desktop interface for GitFollow.
Run: python gui.py   or double-click GitFollow.exe
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import importlib
import json
import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path
from datetime import datetime

# ── Path resolution (works as .py script and PyInstaller .exe) ────────────────

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

ENV_FILE   = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / "data" / "state.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def save_env(env: dict):
    ENV_FILE.write_text(
        "\n".join(f"{k}={v}" for k, v in env.items() if v.strip()) + "\n",
        encoding="utf-8",
    )


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "following": {},
        "quality_cache": {},
        "stats": {"followed": 0, "unfollowed": 0, "mutual": 0},
    }


class _GUILogHandler(logging.Handler):
    """Redirects log records to a GUI callback."""
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            self.callback(self.format(record) + "\n")
        except Exception:
            pass

# ── App ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GitFollow")
        self.geometry("720x540")
        self.resizable(False, False)
        self._running = False
        self._build_ui()
        self.after(100, self._on_open)

    # ── UI skeleton ───────────────────────────────────────────────────────────

    def _build_ui(self):
        ttk.Style(self).theme_use("clam")

        hdr = tk.Frame(self, bg="#24292e", height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text="  GitFollow", bg="#24292e", fg="white",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left", padx=10, pady=8)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)

        self._build_setup_tab()
        self._build_dashboard_tab()
        self._build_run_tab()
        self._build_settings_tab()

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self):
        f = ttk.Frame(self.nb, padding=16)
        self.nb.add(f, text="  Setup  ")

        ttk.Label(f, text="Requirements", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Separator(f).pack(fill="x", pady=(4, 10))

        checks = [
            ("python",   "Python 3.8+"),
            ("requests", "requests library installed"),
            ("token",    "GH_TOKEN configured"),
            ("username", "GH_USERNAME configured"),
            ("data_dir", "data/ directory exists"),
        ]
        self._check_icons = {}
        for key, label in checks:
            row = ttk.Frame(f)
            row.pack(fill="x", pady=2)
            icon = ttk.Label(row, text="⬜", width=3, font=("Segoe UI", 11))
            icon.pack(side="left")
            ttk.Label(row, text=label, font=("Segoe UI", 10)).pack(side="left")
            self._check_icons[key] = icon

        btn_row = ttk.Frame(f)
        btn_row.pack(fill="x", pady=(14, 0))
        ttk.Button(btn_row, text="Re-check", command=self._run_checks).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Auto-fix",  command=self._autofix).pack(side="left", padx=(0, 8))
        ttk.Button(
            btn_row, text="Create GitHub Token →",
            command=lambda: webbrowser.open(
                "https://github.com/settings/tokens/new"
                "?scopes=user%3Afollow&description=GitFollow"
            ),
        ).pack(side="left")

        ttk.Separator(f).pack(fill="x", pady=(14, 6))
        self._setup_msg = ttk.Label(f, text="", foreground="gray", font=("Segoe UI", 9))
        self._setup_msg.pack(anchor="w")

    def _run_checks(self):
        results = {}
        results["python"] = sys.version_info >= (3, 8)

        try:
            import requests  # noqa
            results["requests"] = True
        except ImportError:
            results["requests"] = False

        merged = {**load_env(), **os.environ}
        results["token"]    = bool(merged.get("GH_TOKEN", "").strip())
        results["username"] = bool(merged.get("GH_USERNAME", "").strip())
        results["data_dir"] = (BASE_DIR / "data").exists()

        for key, ok in results.items():
            self._check_icons[key].config(text="✅" if ok else "❌")

        all_ok = all(results.values())
        self._setup_msg.config(
            text="All checks passed — you're ready to run!" if all_ok
                 else "Fix the items marked ❌, then click Re-check.",
            foreground="#28a745" if all_ok else "#dc3545",
        )

    def _autofix(self):
        import subprocess
        fixed = []

        try:
            import requests  # noqa
        except ImportError:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "requests", "-q"]
                )
                fixed.append("Installed requests")
            except Exception as e:
                messagebox.showerror("Auto-fix", f"Could not install requests:\n{e}")
                return

        data_dir = BASE_DIR / "data"
        if not data_dir.exists():
            data_dir.mkdir(parents=True)
            fixed.append("Created data/ directory")

        if not ENV_FILE.exists():
            ENV_FILE.write_text("GH_TOKEN=\nGH_USERNAME=\n", encoding="utf-8")
            fixed.append("Created .env — open Settings tab to fill it in")

        messagebox.showinfo(
            "Auto-fix",
            ("Fixed:\n• " + "\n• ".join(fixed)) if fixed else "Nothing to auto-fix.",
        )
        self._run_checks()

    # ── Dashboard tab ─────────────────────────────────────────────────────────

    def _build_dashboard_tab(self):
        f = ttk.Frame(self.nb, padding=16)
        self.nb.add(f, text="  Dashboard  ")

        ttk.Label(f, text="Stats", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Separator(f).pack(fill="x", pady=(4, 14))

        grid = ttk.Frame(f)
        grid.pack(fill="x")

        cards = [
            ("following",  "Following (GitHub)"),
            ("followers",  "Followers (GitHub)"),
            ("mutual",     "Mutual Follows"),
            ("unfollowed", "Total Unfollowed"),
            ("followed",   "Total Followed"),
            ("cached",     "Cached Checks"),
        ]
        self._stat_vars = {}
        for i, (key, label) in enumerate(cards):
            card = tk.Frame(grid, bg="#f6f8fa", bd=1, relief="solid", padx=16, pady=10)
            card.grid(row=i // 3, column=i % 3, padx=6, pady=6, sticky="nsew")
            var = tk.StringVar(value="—")
            self._stat_vars[key] = var
            tk.Label(card, textvariable=var, bg="#f6f8fa",
                     font=("Segoe UI", 22, "bold"), fg="#24292e").pack()
            tk.Label(card, text=label, bg="#f6f8fa",
                     font=("Segoe UI", 8), fg="#586069").pack()

        for col in range(3):
            grid.columnconfigure(col, weight=1)

        btn_row = ttk.Frame(f)
        btn_row.pack(fill="x", pady=(16, 0))
        ttk.Button(btn_row, text="Refresh", command=self._refresh_dashboard).pack(side="left")
        self._dash_ts = ttk.Label(btn_row, text="", foreground="gray", font=("Segoe UI", 9))
        self._dash_ts.pack(side="left", padx=12)

    def _refresh_dashboard(self):
        # Load local state for tool-tracked stats
        state  = load_state()
        stats  = state.get("stats", {})
        cache  = state.get("quality_cache", {})

        self._stat_vars["mutual"].set(f"{stats.get('mutual', 0):,}")
        self._stat_vars["unfollowed"].set(f"{stats.get('unfollowed', 0):,}")
        self._stat_vars["followed"].set(f"{stats.get('followed', 0):,}")
        self._stat_vars["cached"].set(f"{len(cache):,}")
        self._dash_ts.config(text="Fetching live stats...")

        # Fetch live following/followers counts from GitHub API in background
        def _fetch():
            env = {**load_env(), **os.environ}
            token    = env.get("GH_TOKEN", "").strip()
            username = env.get("GH_USERNAME", "").strip()
            if not token or not username:
                self.after(0, lambda: self._dash_ts.config(
                    text="Set GH_TOKEN and GH_USERNAME in Settings to see live counts."
                ))
                return
            try:
                import requests
                resp = requests.get(
                    f"https://api.github.com/users/{username}",
                    headers={"Authorization": f"token {token}",
                             "Accept": "application/vnd.github.v3+json"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    following_count = data.get("following", 0)
                    followers_count = data.get("followers", 0)
                    self.after(0, lambda f=following_count, fo=followers_count: (
                        self._stat_vars["following"].set(f"{f:,}"),
                        self._stat_vars["followers"].set(f"{fo:,}"),
                        self._dash_ts.config(
                            text=f"Updated {datetime.now().strftime('%H:%M:%S')}"
                        ),
                    ))
                else:
                    self.after(0, lambda: self._dash_ts.config(
                        text=f"API error {resp.status_code} — check your token."
                    ))
            except Exception as e:
                self.after(0, lambda: self._dash_ts.config(text=f"Error: {e}"))

        threading.Thread(target=_fetch, daemon=True).start()

    # ── Run tab ───────────────────────────────────────────────────────────────

    def _build_run_tab(self):
        f = ttk.Frame(self.nb, padding=16)
        self.nb.add(f, text="  Run  ")

        ttk.Label(f, text="Actions", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Separator(f).pack(fill="x", pady=(4, 12))

        btn_row = ttk.Frame(f)
        btn_row.pack(fill="x", pady=(0, 8))
        self._btn_follow = ttk.Button(
            btn_row, text="▶  Run Follow",
            command=lambda: self._start_run("follow"),
        )
        self._btn_follow.pack(side="left", padx=(0, 8))
        self._btn_unfollow = ttk.Button(
            btn_row, text="▶  Run Unfollow",
            command=lambda: self._start_run("unfollow"),
        )
        self._btn_unfollow.pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Clear", command=self._clear_log).pack(side="right")

        self._log = scrolledtext.ScrolledText(
            f, height=18, font=("Consolas", 9),
            state="disabled", bg="#1e1e1e", fg="#d4d4d4",
        )
        self._log.pack(fill="both", expand=True)

    def _start_run(self, mode: str):
        if self._running:
            messagebox.showinfo("Already running", "A run is already in progress.")
            return

        # Build env fresh from saved settings each run — never carry over
        # overrides from a previous run (e.g. FOLLOW_LIMIT=0 from unfollow mode)
        env = load_env()

        if not env.get("GH_TOKEN") or not env.get("GH_USERNAME"):
            messagebox.showerror(
                "Missing credentials",
                "GH_TOKEN and GH_USERNAME must be set.\nGo to the Settings tab.",
            )
            return

        if mode == "unfollow":
            env["QUALITY_UNFOLLOW"] = "true"
            env["FOLLOW_LIMIT"]     = "0"

        # Apply to os.environ so gitfollow reads them on import/reload
        os.environ.update(env)

        self._running = True
        self._btn_follow.config(state="disabled")
        self._btn_unfollow.config(state="disabled")
        self._log_write(f"\n{'─' * 60}\n▶  Starting {mode} run…\n{'─' * 60}\n")

        handler = _GUILogHandler(self._log_write)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

        def _worker():
            root_log = logging.getLogger()
            root_log.setLevel(logging.INFO)
            root_log.addHandler(handler)
            try:
                # Lazy import so credentials are set before the module loads.
                # Reload on every run so config re-reads the current os.environ.
                import gitfollow as _gf
                importlib.reload(_gf)
                _gf.main()
            except Exception as e:
                self._log_write(f"\nERROR: {e}\n")
            finally:
                root_log.removeHandler(handler)
                self.after(0, self._run_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _run_done(self):
        self._running = False
        self._btn_follow.config(state="normal")
        self._btn_unfollow.config(state="normal")
        self._log_write(f"\n{'─' * 60}\n■  Run complete\n{'─' * 60}\n")
        self._refresh_dashboard()

    def _log_write(self, text: str):
        def _do():
            self._log.config(state="normal")
            self._log.insert(tk.END, text)
            self._log.see(tk.END)
            self._log.config(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        self._log.config(state="normal")
        self._log.delete("1.0", tk.END)
        self._log.config(state="disabled")

    # ── Settings tab ──────────────────────────────────────────────────────────

    def _build_settings_tab(self):
        f = ttk.Frame(self.nb, padding=16)
        self.nb.add(f, text="  Settings  ")

        ttk.Label(f, text="Configuration", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Separator(f).pack(fill="x", pady=(4, 12))

        form = ttk.Frame(f)
        form.pack(fill="x")

        fields = [
            ("GH_TOKEN",       "GitHub Token",         True,  ""),
            ("GH_USERNAME",    "GitHub Username",       False, ""),
            ("FOLLOW_LIMIT",   "Follow Limit",          False, "400"),
            ("UNFOLLOW_HOURS", "Unfollow After (hrs)",  False, "24"),
            ("ACTIVITY_DAYS",  "Activity Days",         False, "30"),
            ("MIN_FOLLOWERS",  "Min Followers",         False, "1"),
            ("CACHE_DAYS",     "Cache Days",            False, "7"),
            ("WHITELIST",      "Whitelist (csv)",       False, ""),
        ]
        self._settings_vars = {}
        for i, (key, label, secret, default) in enumerate(fields):
            ttk.Label(form, text=label, width=22, anchor="w").grid(
                row=i, column=0, padx=(0, 8), pady=3, sticky="w"
            )
            var = tk.StringVar(value=default)
            self._settings_vars[key] = var
            ttk.Entry(form, textvariable=var, show="•" if secret else "", width=38).grid(
                row=i, column=1, pady=3, sticky="ew"
            )

        i = len(fields)
        ttk.Label(form, text="Quality Unfollow", width=22, anchor="w").grid(
            row=i, column=0, padx=(0, 8), pady=3, sticky="w"
        )
        self._qu_var = tk.BooleanVar()
        ttk.Checkbutton(form, variable=self._qu_var).grid(row=i, column=1, pady=3, sticky="w")
        form.columnconfigure(1, weight=1)

        btn_row = ttk.Frame(f)
        btn_row.pack(fill="x", pady=(16, 0))
        ttk.Button(btn_row, text="Save Settings",  command=self._save_settings).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Load from .env", command=self._load_settings).pack(side="left")

        self._settings_msg = ttk.Label(f, text="", foreground="gray", font=("Segoe UI", 9))
        self._settings_msg.pack(anchor="w", pady=(8, 0))

    def _save_settings(self):
        env = {k: v.get() for k, v in self._settings_vars.items()}
        env["QUALITY_UNFOLLOW"] = "true" if self._qu_var.get() else "false"
        save_env(env)
        self._settings_msg.config(
            text=f"Saved  ({datetime.now().strftime('%H:%M:%S')})",
            foreground="#28a745",
        )
        self._run_checks()

    def _load_settings(self):
        env = load_env()
        for k, var in self._settings_vars.items():
            var.set(env.get(k, var.get()))
        self._qu_var.set(env.get("QUALITY_UNFOLLOW", "false").lower() == "true")
        self._settings_msg.config(text=f"Loaded from {ENV_FILE}", foreground="gray")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _on_open(self):
        self._run_checks()
        self._refresh_dashboard()
        self._load_settings()


if __name__ == "__main__":
    App().mainloop()
