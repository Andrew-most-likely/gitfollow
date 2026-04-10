"""
GitFollow GUI - Desktop interface for GitFollow.
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

# ── Paths ─────────────────────────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

ENV_FILE   = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / "data" / "state.json"

VERSION = "1.3"

# ── Design tokens ─────────────────────────────────────────────────────────────

BG       = "#f6f8fa"
SURFACE  = "#ffffff"
BORDER   = "#d0d7de"
HDR_BG   = "#24292f"
HDR_TEXT = "#ffffff"
PRIMARY  = "#0969da"
SUCCESS  = "#1a7f37"
DANGER   = "#cf222e"
WARNING  = "#bf8700"
TEXT     = "#1f2328"
MUTED    = "#57606a"
TERM_BG  = "#0d1117"
TERM_FG  = "#e6edf3"
TAG_BG   = "#ddf4ff"
TAG_FG   = "#0550ae"

F_UI   = ("Segoe UI", 10)
F_BOLD = ("Segoe UI", 10, "bold")
F_H1   = ("Segoe UI", 11, "bold")
F_MONO = ("Consolas", 9)
F_NUM  = ("Segoe UI", 22, "bold")
F_SM   = ("Segoe UI", 9)
F_XS   = ("Segoe UI", 8)

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

# ── Tooltip ───────────────────────────────────────────────────────────────────

class Tooltip:
    """Hover tooltip attached to any widget."""

    def __init__(self, widget: tk.Widget, text: str):
        self._win  = None
        self._text = text
        widget.bind("<Enter>",  self._show)
        widget.bind("<Leave>",  self._hide)
        widget.bind("<Button>", self._hide)

    def _show(self, event=None):
        if self._win:
            return
        w = event.widget
        x = w.winfo_rootx() + w.winfo_width() + 6
        y = w.winfo_rooty() + (w.winfo_height() // 2) - 12
        self._win = tw = tk.Toplevel(w)
        tw.wm_overrideredirect(True)
        tw.wm_attributes("-topmost", True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self._text, justify="left", wraplength=260,
            bg="#fffbe6", fg=TEXT, relief="solid", bd=1,
            font=F_SM, padx=10, pady=8,
        ).pack()

    def _hide(self, event=None):
        if self._win:
            self._win.destroy()
            self._win = None


def _help(parent: tk.Widget, tip: str) -> tk.Label:
    """Small inline ? button with a hover tooltip."""
    lbl = tk.Label(
        parent, text=" ? ", font=F_XS,
        fg=PRIMARY, bg=BG, cursor="question_arrow",
        relief="solid", bd=1,
    )
    Tooltip(lbl, tip)
    return lbl


# ── Log handler ───────────────────────────────────────────────────────────────

class _GUILogHandler(logging.Handler):
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
        self.geometry("800x600")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._running = False
        self._build_ui()
        self.after(100, self._on_open)

    # ── Styles and skeleton ───────────────────────────────────────────────────

    def _build_ui(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",            background=BG)
        s.configure("TLabel",            background=BG, foreground=TEXT, font=F_UI)
        s.configure("TButton",           font=F_UI, padding=[10, 5])
        s.configure("TCheckbutton",      background=BG, foreground=TEXT, font=F_UI)
        s.configure("TSeparator",        background=BORDER)
        s.configure("TNotebook",         background=BG, borderwidth=0, tabmargins=[0, 4, 0, 0])
        s.configure("TNotebook.Tab",     font=F_UI, padding=[18, 8], background="#e8ecf0", foreground=MUTED)
        s.map("TNotebook.Tab",
              background=[("selected", SURFACE), ("active", "#f0f4f8")],
              foreground=[("selected", TEXT),    ("active", TEXT)])
        s.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT, bordercolor=BORDER, font=F_UI)
        s.configure("Primary.TButton",   font=F_BOLD, background=PRIMARY, foreground="white")
        s.map("Primary.TButton",
              background=[("active", "#0757bb"), ("disabled", "#8ab4e8")])

        # Header
        hdr = tk.Frame(self, bg=HDR_BG, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="GitFollow", bg=HDR_BG, fg=HDR_TEXT,
                 font=("Segoe UI", 15, "bold")).pack(side="left", padx=16, pady=12)
        tk.Label(hdr, text=f"v{VERSION}", bg=HDR_BG, fg="#8b949e",
                 font=F_SM).pack(side="left", pady=16)
        tk.Label(hdr, text="Automated GitHub network growth",
                 bg=HDR_BG, fg="#8b949e", font=F_SM).pack(side="right", padx=16, pady=16)

        # Notebook
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=0, pady=0)

        self._build_setup_tab()
        self._build_dashboard_tab()
        self._build_run_tab()
        self._build_settings_tab()

        # Status bar
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        bar = tk.Frame(self, bg="#f0f2f4", height=28)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self._status_var = tk.StringVar(value="Ready")
        tk.Label(bar, textvariable=self._status_var, bg="#f0f2f4",
                 fg=MUTED, font=F_SM).pack(side="left", padx=12, pady=5)
        tk.Label(bar, text="MIT License", bg="#f0f2f4",
                 fg=MUTED, font=F_SM).pack(side="right", padx=12, pady=5)

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self):
        outer = ttk.Frame(self.nb)
        self.nb.add(outer, text="  Setup  ")

        f = tk.Frame(outer, bg=SURFACE, bd=1, relief="solid")
        f.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(f, text="Environment Checks", font=F_H1, bg=SURFACE, fg=TEXT).pack(
            anchor="w", padx=20, pady=(16, 4))
        tk.Label(f, text="Verify that everything is configured correctly before running.",
                 font=F_SM, bg=SURFACE, fg=MUTED).pack(anchor="w", padx=20, pady=(0, 12))
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", padx=20)

        checks = [
            ("python",   "Python 3.8+",                    "GitFollow requires Python 3.8 or newer."),
            ("requests", "requests library installed",      "The requests library handles all GitHub API calls. Run 'pip install requests' if missing."),
            ("token",    "GH_TOKEN configured",             "Your GitHub Personal Access Token. Set it in the Settings tab and click Save."),
            ("username", "GH_USERNAME configured",          "Your GitHub username. Set it in the Settings tab and click Save."),
            ("data_dir", "data/ directory exists",          "Stores state.json which tracks follows, unfollow history, and cached quality checks."),
        ]
        self._check_icons = {}
        chk_frame = tk.Frame(f, bg=SURFACE)
        chk_frame.pack(fill="x", padx=20, pady=12)
        for key, label, tip in checks:
            row = tk.Frame(chk_frame, bg=SURFACE)
            row.pack(fill="x", pady=4)
            icon = tk.Label(row, text="  ", font=("Segoe UI", 11), bg=SURFACE, width=3)
            icon.pack(side="left")
            tk.Label(row, text=label, font=F_UI, bg=SURFACE, fg=TEXT).pack(side="left")
            _help(row, tip).pack(side="left", padx=(8, 0))
            self._check_icons[key] = icon

        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", padx=20)

        btn_row = tk.Frame(f, bg=SURFACE)
        btn_row.pack(fill="x", padx=20, pady=14)
        ttk.Button(btn_row, text="Re-check",  command=self._run_checks).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Auto-fix",  command=self._autofix).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Create GitHub Token",
                   command=lambda: webbrowser.open(
                       "https://github.com/settings/tokens/new"
                       "?scopes=user%3Afollow&description=GitFollow"
                   )).pack(side="left")

        self._setup_msg = tk.Label(f, text="", font=F_SM, bg=SURFACE)
        self._setup_msg.pack(anchor="w", padx=20, pady=(0, 16))

    def _run_checks(self):
        self._set_status("Running checks...")
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
            self._check_icons[key].config(
                text=" ok" if ok else " --",
                fg=SUCCESS if ok else DANGER,
                font=F_SM,
            )

        all_ok = all(results.values())
        self._setup_msg.config(
            text="All checks passed. You are ready to run." if all_ok
                 else "Fix the failing items above, then click Re-check.",
            fg=SUCCESS if all_ok else DANGER,
        )
        self._set_status("Checks complete." if all_ok else "Some checks failed.")

    def _autofix(self):
        import subprocess as sp
        fixed = []
        try:
            import requests  # noqa
        except ImportError:
            try:
                sp.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
                fixed.append("Installed requests")
            except Exception as e:
                messagebox.showerror("Auto-fix failed", str(e))
                return
        data_dir = BASE_DIR / "data"
        if not data_dir.exists():
            data_dir.mkdir(parents=True)
            fixed.append("Created data/ directory")
        if not ENV_FILE.exists():
            ENV_FILE.write_text("GH_TOKEN=\nGH_USERNAME=\n", encoding="utf-8")
            fixed.append("Created .env - open Settings tab to fill it in")
        messagebox.showinfo(
            "Auto-fix",
            ("Fixed:\n  " + "\n  ".join(fixed)) if fixed else "Nothing needed fixing.",
        )
        self._run_checks()

    # ── Dashboard tab ─────────────────────────────────────────────────────────

    def _build_dashboard_tab(self):
        outer = ttk.Frame(self.nb)
        self.nb.add(outer, text="  Dashboard  ")

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x", padx=16, pady=(16, 0))
        tk.Label(header, text="Live Stats", font=F_H1, bg=BG, fg=TEXT).pack(side="left")
        ttk.Button(header, text="Refresh", command=self._refresh_dashboard).pack(side="right")
        self._dash_ts = tk.Label(header, text="", font=F_SM, bg=BG, fg=MUTED)
        self._dash_ts.pack(side="right", padx=(0, 10))

        grid_frame = tk.Frame(outer, bg=BG)
        grid_frame.pack(fill="x", padx=16, pady=12)

        cards = [
            ("following",  "Following",       "Your current total following count on GitHub."),
            ("followers",  "Followers",        "Your current total follower count on GitHub."),
            ("mutual",     "Mutual Follows",   "Accounts tracked by GitFollow that also follow you back."),
            ("followed",   "Total Followed",   "Total accounts followed through GitFollow across all runs."),
            ("unfollowed", "Total Unfollowed", "Total accounts unfollowed through GitFollow across all runs."),
            ("cached",     "Cached Checks",    "Quality check results stored locally. Avoids re-checking accounts on every run."),
        ]
        self._stat_vars = {}
        for i, (key, label, tip) in enumerate(cards):
            col = i % 3
            row = i // 3

            card = tk.Frame(grid_frame, bg=SURFACE, bd=1, relief="solid",
                            padx=20, pady=14)
            card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")

            top = tk.Frame(card, bg=SURFACE)
            top.pack(fill="x")
            tk.Label(top, text=label, font=F_XS, bg=SURFACE, fg=MUTED).pack(side="left")
            _help(top, tip).pack(side="right")

            var = tk.StringVar(value="...")
            self._stat_vars[key] = var
            tk.Label(card, textvariable=var, font=F_NUM, bg=SURFACE, fg=TEXT).pack(anchor="w", pady=(4, 0))

        for col in range(3):
            grid_frame.columnconfigure(col, weight=1)

        note = tk.Label(outer,
            text="Following and Followers are fetched live from the GitHub API. Other stats are read from local state.json.",
            font=F_XS, bg=BG, fg=MUTED, wraplength=720, justify="left")
        note.pack(anchor="w", padx=22, pady=(4, 0))

    def _refresh_dashboard(self):
        state = load_state()
        stats = state.get("stats", {})
        cache = state.get("quality_cache", {})

        self._stat_vars["mutual"].set(f"{stats.get('mutual', 0):,}")
        self._stat_vars["followed"].set(f"{stats.get('followed', 0):,}")
        self._stat_vars["unfollowed"].set(f"{stats.get('unfollowed', 0):,}")
        self._stat_vars["cached"].set(f"{len(cache):,}")
        self._stat_vars["following"].set("...")
        self._stat_vars["followers"].set("...")
        self._dash_ts.config(text="Fetching live counts...")
        self._set_status("Fetching live counts from GitHub...")

        def _fetch():
            env    = {**load_env(), **os.environ}
            token  = env.get("GH_TOKEN", "").strip()
            user   = env.get("GH_USERNAME", "").strip()
            if not token or not user:
                self.after(0, lambda: (
                    self._stat_vars["following"].set("--"),
                    self._stat_vars["followers"].set("--"),
                    self._dash_ts.config(text="Set credentials in Settings to load live counts."),
                    self._set_status("Credentials not configured."),
                ))
                return
            try:
                import requests
                resp = requests.get(
                    f"https://api.github.com/users/{user}",
                    headers={"Authorization": f"token {token}",
                             "Accept": "application/vnd.github.v3+json"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    f_ing = data.get("following", 0)
                    f_ers = data.get("followers", 0)
                    ts    = datetime.now().strftime("%H:%M:%S")
                    self.after(0, lambda: (
                        self._stat_vars["following"].set(f"{f_ing:,}"),
                        self._stat_vars["followers"].set(f"{f_ers:,}"),
                        self._dash_ts.config(text=f"Updated {ts}"),
                        self._set_status("Dashboard refreshed."),
                    ))
                else:
                    self.after(0, lambda: (
                        self._stat_vars["following"].set("Err"),
                        self._stat_vars["followers"].set("Err"),
                        self._dash_ts.config(text=f"API error {resp.status_code}"),
                        self._set_status(f"GitHub API returned {resp.status_code}."),
                    ))
            except Exception as e:
                self.after(0, lambda: (
                    self._dash_ts.config(text="Network error."),
                    self._set_status(f"Error: {e}"),
                ))

        threading.Thread(target=_fetch, daemon=True).start()

    # ── Run tab ───────────────────────────────────────────────────────────────

    def _build_run_tab(self):
        outer = ttk.Frame(self.nb)
        self.nb.add(outer, text="  Run  ")

        top = tk.Frame(outer, bg=BG)
        top.pack(fill="x", padx=16, pady=(16, 0))

        tk.Label(top, text="Actions", font=F_H1, bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(top,
            text="Runs execute locally on your machine. To run on a schedule, use GitHub Actions.",
            font=F_SM, bg=BG, fg=MUTED).pack(anchor="w", pady=(2, 12))

        btn_row = tk.Frame(outer, bg=BG)
        btn_row.pack(fill="x", padx=16, pady=(0, 8))

        follow_frame = tk.Frame(btn_row, bg=BG)
        follow_frame.pack(side="left", padx=(0, 8))
        self._btn_follow = ttk.Button(
            follow_frame, text="Run Follow", style="Primary.TButton",
            command=lambda: self._start_run("follow"),
        )
        self._btn_follow.pack(side="left")
        _help(follow_frame,
              "Searches GitHub for active users meeting your quality criteria "
              "and follows up to FOLLOW_LIMIT of them. Skips orgs, inactive accounts, "
              "and users with no followers."
              ).pack(side="left", padx=(6, 0))

        unfollow_frame = tk.Frame(btn_row, bg=BG)
        unfollow_frame.pack(side="left", padx=(0, 8))
        self._btn_unfollow = ttk.Button(
            unfollow_frame, text="Run Unfollow",
            command=lambda: self._start_run("unfollow"),
        )
        self._btn_unfollow.pack(side="left")
        _help(unfollow_frame,
              "Scans your entire following list and unfollows accounts that fail "
              "quality criteria: organizations, users with no followers, and users "
              "who have not pushed a commit in ACTIVITY_DAYS days. "
              "First run is slow (one check per account). Results are cached."
              ).pack(side="left", padx=(6, 0))

        self._btn_stop = ttk.Button(
            btn_row, text="Stop", command=self._stop_run, state="disabled"
        )
        self._btn_stop.pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Clear Log", command=self._clear_log).pack(side="right")

        # Terminal
        term_frame = tk.Frame(outer, bg=TERM_BG, bd=1, relief="solid")
        term_frame.pack(fill="both", expand=True, padx=16, pady=(4, 16))

        term_header = tk.Frame(term_frame, bg="#161b22")
        term_header.pack(fill="x")
        tk.Label(term_header, text="Output", font=F_XS,
                 bg="#161b22", fg="#8b949e").pack(side="left", padx=10, pady=4)

        self._log = scrolledtext.ScrolledText(
            term_frame, font=F_MONO, state="disabled",
            bg=TERM_BG, fg=TERM_FG, insertbackground=TERM_FG,
            relief="flat", borderwidth=0, selectbackground="#264f78",
        )
        self._log.pack(fill="both", expand=True, padx=4, pady=(0, 4))

    def _start_run(self, mode: str):
        if self._running:
            messagebox.showinfo("Already running", "A run is already in progress.")
            return

        env = load_env()
        merged = {**env, **os.environ}
        if not merged.get("GH_TOKEN") or not merged.get("GH_USERNAME"):
            messagebox.showerror(
                "Missing credentials",
                "GH_TOKEN and GH_USERNAME must be set.\nGo to the Settings tab.",
            )
            return

        if mode == "unfollow":
            env["QUALITY_UNFOLLOW"] = "true"
            env["FOLLOW_LIMIT"]     = "0"

        os.environ.update(env)
        self._running = True
        self._btn_follow.config(state="disabled")
        self._btn_unfollow.config(state="disabled")
        self._btn_stop.config(state="normal")
        self._set_status(f"Running {mode}...")
        self._log_write(f"\n{'=' * 60}\n  GitFollow - {mode.title()} Run - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'=' * 60}\n\n")

        handler = _GUILogHandler(self._log_write)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))

        def _worker():
            root_log = logging.getLogger()
            root_log.setLevel(logging.INFO)
            root_log.addHandler(handler)
            try:
                import gitfollow as _gf
                importlib.reload(_gf)
                _gf.stop_event.clear()
                self._gf_module = _gf
                _gf.main()
            except Exception as e:
                self._log_write(f"\nERROR: {e}\n")
            finally:
                root_log.removeHandler(handler)
                self.after(0, self._run_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_run(self):
        gf = getattr(self, "_gf_module", None)
        if gf:
            gf.stop_event.set()
        self._btn_stop.config(state="disabled")
        self._set_status("Stop requested - finishing current operation...")
        self._log_write("\n  Stop requested - will halt after current operation.\n")

    def _run_done(self):
        self._running = False
        self._btn_follow.config(state="normal")
        self._btn_unfollow.config(state="normal")
        self._btn_stop.config(state="disabled")
        self._log_write(f"\n{'=' * 60}\n  Run complete - {datetime.now().strftime('%H:%M:%S')}\n{'=' * 60}\n")
        self._set_status("Run complete.")
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
        outer = ttk.Frame(self.nb)
        self.nb.add(outer, text="  Settings  ")

        f = tk.Frame(outer, bg=SURFACE, bd=1, relief="solid")
        f.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(f, text="Configuration", font=F_H1, bg=SURFACE, fg=TEXT).pack(
            anchor="w", padx=20, pady=(16, 4))
        tk.Label(f, text="Settings are saved to a local .env file and never committed to git.",
                 font=F_SM, bg=SURFACE, fg=MUTED).pack(anchor="w", padx=20, pady=(0, 12))
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", padx=20)

        form = tk.Frame(f, bg=SURFACE)
        form.pack(fill="x", padx=20, pady=12)

        fields = [
            ("GH_TOKEN",       "GitHub Token",         True,  "",
             "Your GitHub Personal Access Token. Only the user:follow scope is required. "
             "This is stored locally in .env and never shared."),
            ("GH_USERNAME",    "GitHub Username",       False, "",
             "Your exact GitHub username (case-insensitive)."),
            ("FOLLOW_LIMIT",   "Follow Limit",          False, "150",
             "Maximum new accounts to follow per run. Keep at or below 150/day for responsible use and to stay well within GitHub's guidelines."),
            ("UNFOLLOW_HOURS", "Unfollow After (hrs)",  False, "24",
             "How many hours to wait before unfollowing someone who has not followed you back. "
             "Default is 24 hours."),
            ("ACTIVITY_DAYS",  "Activity Days",         False, "30",
             "Skip users who have not pushed a commit in this many days. "
             "Higher values are more lenient. Lower values are stricter."),
            ("MIN_FOLLOWERS",  "Min Followers",         False, "1",
             "Only follow users who already have at least this many followers. "
             "Raising this filters out newer or abandoned accounts."),
            ("CACHE_DAYS",     "Cache Days",            False, "7",
             "How many days to remember quality check results. "
             "Prevents re-checking the same accounts on every run and saves API quota."),
            ("WHITELIST",      "Whitelist",             False, "",
             "Comma-separated usernames to never unfollow, regardless of activity or follow-back status."),
        ]
        self._settings_vars = {}
        for i, (key, label, secret, default, tip) in enumerate(fields):
            lbl_frame = tk.Frame(form, bg=SURFACE)
            lbl_frame.grid(row=i, column=0, padx=(0, 10), pady=5, sticky="w")
            tk.Label(lbl_frame, text=label, font=F_UI, bg=SURFACE,
                     fg=TEXT, width=20, anchor="w").pack(side="left")
            _help(lbl_frame, tip).pack(side="left", padx=(4, 0))

            var = tk.StringVar(value=default)
            self._settings_vars[key] = var
            ttk.Entry(form, textvariable=var, show="*" if secret else "",
                      width=40).grid(row=i, column=1, pady=5, sticky="ew")

        i = len(fields)
        lbl_frame = tk.Frame(form, bg=SURFACE)
        lbl_frame.grid(row=i, column=0, padx=(0, 10), pady=5, sticky="w")
        tk.Label(lbl_frame, text="Quality Unfollow", font=F_UI,
                 bg=SURFACE, fg=TEXT, width=20, anchor="w").pack(side="left")
        _help(lbl_frame,
              "When enabled, the Run Unfollow action scans your entire following list "
              "and unfollows accounts that fail quality criteria: organizations, "
              "users with no followers, and inactive users. "
              "First run is slow, subsequent runs use the cache."
              ).pack(side="left", padx=(4, 0))
        self._qu_var = tk.BooleanVar()
        ttk.Checkbutton(form, variable=self._qu_var).grid(row=i, column=1, pady=5, sticky="w")
        form.columnconfigure(1, weight=1)

        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", padx=20)

        btn_row = tk.Frame(f, bg=SURFACE)
        btn_row.pack(fill="x", padx=20, pady=14)
        ttk.Button(btn_row, text="Save Settings",
                   style="Primary.TButton", command=self._save_settings).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Load from .env",
                   command=self._load_settings).pack(side="left")

        self._settings_msg = tk.Label(f, text="", font=F_SM, bg=SURFACE)
        self._settings_msg.pack(anchor="w", padx=20, pady=(0, 12))

    def _save_settings(self):
        env = {k: v.get() for k, v in self._settings_vars.items()}
        env["QUALITY_UNFOLLOW"] = "true" if self._qu_var.get() else "false"
        save_env(env)
        self._settings_msg.config(
            text=f"Saved to {ENV_FILE}",
            fg=SUCCESS,
        )
        self._set_status("Settings saved.")
        self._run_checks()

    def _load_settings(self):
        env = load_env()
        for k, var in self._settings_vars.items():
            var.set(env.get(k, var.get()))
        self._qu_var.set(env.get("QUALITY_UNFOLLOW", "false").lower() == "true")
        self._settings_msg.config(text=f"Loaded from {ENV_FILE}", fg=MUTED)

    # ── Status bar and lifecycle ───────────────────────────────────────────────

    def _set_status(self, msg: str):
        self._status_var.set(msg)

    def _on_open(self):
        self._run_checks()
        self._refresh_dashboard()
        self._load_settings()


if __name__ == "__main__":
    App().mainloop()
