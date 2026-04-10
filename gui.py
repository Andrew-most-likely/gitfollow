"""
GitFollow GUI - Desktop interface for GitFollow.
Run: python gui.py   or double-click GitFollow.exe
"""

import colorsys
import queue
import tkinter as tk
from tkinter import scrolledtext, messagebox
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

VERSION = "2.0.4"

# ── GitHub Dark Dimmed color tokens ───────────────────────────────────────────

C_BG        = "#22272e"   # canvas-default
C_SURFACE   = "#2d333b"   # canvas-subtle
C_SIDEBAR   = "#1c2128"   # canvas-inset (sidebar)
C_SIDEBAR_H = "#2d333b"   # sidebar hover
C_SIDEBAR_S = "#2d333b"   # sidebar selected
C_ACCENT    = "#539bf5"   # accent-fg
C_SUCCESS   = "#57ab5a"   # success-fg
C_DANGER    = "#e5534b"   # danger-fg
C_WARNING   = "#c69026"   # attention-fg
C_TEXT      = "#adbac7"   # fg-default
C_TEXT2     = "#768390"   # fg-muted
C_MUTED     = "#636e7b"   # fg-subtle
C_SEP       = "#444c56"   # border-default
C_TERM_BG   = "#1c2128"   # canvas-inset (terminal)
C_TERM_FG   = "#adbac7"   # fg-default

F_APP   = ("Segoe UI", 12, "bold")
F_H1    = ("Segoe UI", 17, "bold")
F_H2    = ("Segoe UI", 12, "bold")
F_UI    = ("Segoe UI", 10)
F_BOLD  = ("Segoe UI", 10, "bold")
F_SM    = ("Segoe UI", 9)
F_XS    = ("Segoe UI", 8)
F_NUM   = ("Segoe UI", 26, "bold")
F_MONO  = ("Consolas", 9)
F_NAV   = ("Segoe UI", 10)

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


def _darken(hex_color: str, amount: float) -> str:
    """Return a darkened version of a hex color."""
    hex_c = hex_color.lstrip("#")
    r, g, b = (int(hex_c[i:i+2], 16) / 255 for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, max(0.0, v - amount))
    return "#{:02x}{:02x}{:02x}".format(int(r2 * 255), int(g2 * 255), int(b2 * 255))


# ── Rounded button (Canvas-based) ─────────────────────────────────────────────

class RoundedButton(tk.Canvas):
    """Pill-shaped button drawn on a Canvas for rounded corners."""

    def __init__(self, parent, text, command,
                 width=130, height=34, radius=8,
                 bg=C_ACCENT, fg="white", font=F_BOLD, **kwargs):
        super().__init__(
            parent, width=width, height=height,
            bg=parent.cget("bg"), highlightthickness=0, **kwargs
        )
        self._text      = text
        self._orig_cmd  = command
        self._command   = command
        self._orig_bg   = bg
        self._bg        = bg
        self._hover_bg  = _darken(bg, 0.12)
        self._fg        = fg
        self._radius    = radius
        self._font      = font
        self._btn_w     = width
        self._btn_h     = height
        self._disabled  = False
        self._hovering  = False
        self._draw()
        self.bind("<Enter>",    self._on_enter)
        self.bind("<Leave>",    self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _rounded_rect(self, color: str):
        self.delete("all")
        w, h, r = self._btn_w, self._btn_h, self._radius
        c = color
        self.create_arc(0,       0,       2*r, 2*r, start=90,  extent=90, fill=c, outline=c)
        self.create_arc(w-2*r,   0,       w,   2*r, start=0,   extent=90, fill=c, outline=c)
        self.create_arc(0,       h-2*r,   2*r, h,   start=180, extent=90, fill=c, outline=c)
        self.create_arc(w-2*r,   h-2*r,   w,   h,   start=270, extent=90, fill=c, outline=c)
        self.create_rectangle(r, 0,   w-r, h,   fill=c, outline=c)
        self.create_rectangle(0, r,   w,   h-r, fill=c, outline=c)
        self.create_text(w // 2, h // 2, text=self._text,
                         fill=self._fg, font=self._font)

    def _draw(self):
        if self._disabled:
            self._rounded_rect(C_MUTED)
        elif self._hovering:
            self._rounded_rect(self._hover_bg)
        else:
            self._rounded_rect(self._bg)

    def _on_enter(self, _e=None):
        if not self._disabled:
            self._hovering = True
            self.config(cursor="hand2")
            self._draw()

    def _on_leave(self, _e=None):
        self._hovering = False
        self.config(cursor="")
        self._draw()

    def _on_click(self, _e=None):
        if self._command and not self._disabled:
            self._command()

    def config_state(self, disabled: bool):
        self._disabled = disabled
        self._hovering = False
        self._command  = None if disabled else self._orig_cmd
        self._bg       = C_MUTED if disabled else self._orig_bg
        self._draw()


# ── Tooltip ────────────────────────────────────────────────────────────────────

class Tooltip:
    """Dark floating tooltip on hover."""

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
        x = w.winfo_rootx() + w.winfo_width() + 8
        y = w.winfo_rooty() + (w.winfo_height() // 2) - 14
        self._win = tw = tk.Toplevel(w)
        tw.wm_overrideredirect(True)
        tw.wm_attributes("-topmost", True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self._text, justify="left", wraplength=260,
            bg=C_SURFACE, fg=C_TEXT, font=F_SM, padx=12, pady=8,
        ).pack()

    def _hide(self, event=None):
        if self._win:
            self._win.destroy()
            self._win = None


def _tip(parent, text: str, bg=C_BG) -> tk.Label:
    """Small inline ? label with a hover tooltip."""
    lbl = tk.Label(parent, text="?", font=("Segoe UI", 8, "bold"),
                   fg=C_MUTED, bg=bg, cursor="question_arrow", width=2)
    Tooltip(lbl, text)
    return lbl


# ── Log handler ────────────────────────────────────────────────────────────────

class _GUILogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            self.callback(self.format(record) + "\n")
        except Exception:
            pass


# ── App ────────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GitFollow")
        self.geometry("960x640")
        self.resizable(False, False)
        self.configure(bg=C_SIDEBAR)
        self._running       = False
        self._pages         = {}
        self._nav_frames    = {}
        self._current_page  = None
        self._log_queue     = queue.Queue()
        self._build_ui()
        self.after(50,  self._poll_log_queue)
        self.after(100, self._on_open)

    # ── Shell ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Left sidebar
        self._sidebar = tk.Frame(self, bg=C_SIDEBAR, width=190)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        # Right content pane
        self._pane = tk.Frame(self, bg=C_BG)
        self._pane.pack(side="left", fill="both", expand=True)

        self._build_sidebar()
        self._build_setup_page()
        self._build_dashboard_page()
        self._build_run_page()
        self._build_settings_page()

        # Status bar (pinned to bottom of pane)
        tk.Frame(self._pane, bg=C_SEP, height=1).pack(side="bottom", fill="x")
        bar = tk.Frame(self._pane, bg=C_SURFACE, height=30)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        self._status_var = tk.StringVar(value="Ready")
        tk.Label(bar, textvariable=self._status_var,
                 bg=C_SURFACE, fg=C_MUTED, font=F_SM).pack(side="left", padx=16, pady=6)

        self._show_page("setup")

    # ── Sidebar ────────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        # App branding
        brand = tk.Frame(self._sidebar, bg=C_SIDEBAR, height=60)
        brand.pack(fill="x")
        brand.pack_propagate(False)
        tk.Label(brand, text="GitFollow", bg=C_SIDEBAR, fg="white",
                 font=F_APP).pack(side="left", padx=18, pady=18)
        tk.Label(brand, text=f"v{VERSION}", bg=C_SIDEBAR, fg=C_MUTED,
                 font=F_XS).pack(side="left", pady=22)

        tk.Frame(self._sidebar, bg=C_SEP, height=1).pack(fill="x")

        tk.Label(self._sidebar, text="MENU", bg=C_SIDEBAR, fg=C_MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=18, pady=(12, 2))

        for key, icon, label in [
            ("setup",     "checkmark.circle", "Setup"),
            ("dashboard", "chart.bar",        "Dashboard"),
            ("run",       "play.circle",      "Run"),
            ("settings",  "gearshape",        "Settings"),
        ]:
            self._nav_item(key, label)

        # Spacer + license note
        tk.Frame(self._sidebar, bg=C_SIDEBAR).pack(fill="both", expand=True)
        tk.Label(self._sidebar, text="MIT License",
                 bg=C_SIDEBAR, fg=C_MUTED, font=F_XS).pack(side="bottom", pady=14)

    def _nav_item(self, key: str, label: str):
        frame = tk.Frame(self._sidebar, bg=C_SIDEBAR, cursor="hand2")
        frame.pack(fill="x", padx=8, pady=1)

        # Accent bar (shown when selected)
        bar   = tk.Frame(frame, bg=C_SIDEBAR, width=3)
        bar.pack(side="left", fill="y")

        inner = tk.Label(frame, text=f"  {label}", bg=C_SIDEBAR, fg=C_MUTED,
                         font=F_NAV, anchor="w", padx=10, pady=8)
        inner.pack(fill="x", side="left", expand=True)

        def click(_e=None, k=key):
            self._show_page(k)

        def enter(_e=None):
            if self._current_page != key:
                frame.config(bg=C_SIDEBAR_H)
                inner.config(bg=C_SIDEBAR_H)
                bar.config(bg=C_SIDEBAR_H)

        def leave(_e=None):
            if self._current_page != key:
                frame.config(bg=C_SIDEBAR)
                inner.config(bg=C_SIDEBAR)
                bar.config(bg=C_SIDEBAR)

        for w in (frame, inner, bar):
            w.bind("<Button-1>", click)
            w.bind("<Enter>",    enter)
            w.bind("<Leave>",    leave)

        self._nav_frames[key] = (frame, inner, bar)

    def _show_page(self, name: str):
        self._current_page = name
        for pg in self._pages.values():
            pg.pack_forget()
        self._pages[name].pack(fill="both", expand=True)

        for key, (frame, inner, bar) in self._nav_frames.items():
            if key == name:
                frame.config(bg=C_SIDEBAR_S)
                inner.config(bg=C_SIDEBAR_S, fg=C_TEXT,
                             font=("Segoe UI", 10, "bold"))
                bar.config(bg=C_ACCENT)
            else:
                frame.config(bg=C_SIDEBAR)
                inner.config(bg=C_SIDEBAR, fg=C_MUTED, font=F_NAV)
                bar.config(bg=C_SIDEBAR)

    # ── Page scaffold ──────────────────────────────────────────────────────────

    def _page_header(self, page: tk.Frame, title: str, subtitle: str = "") -> tk.Frame:
        """White header bar. Returns the right-side actions frame."""
        hdr = tk.Frame(page, bg=C_SURFACE)
        hdr.pack(fill="x")

        left = tk.Frame(hdr, bg=C_SURFACE)
        left.pack(side="left", fill="y")
        tk.Label(left, text=title, bg=C_SURFACE, fg=C_TEXT,
                 font=F_H1).pack(anchor="w", padx=24, pady=(18, 0))
        if subtitle:
            tk.Label(left, text=subtitle, bg=C_SURFACE, fg=C_MUTED,
                     font=F_SM).pack(anchor="w", padx=24, pady=(1, 16))
        else:
            tk.Frame(left, height=18, bg=C_SURFACE).pack()

        right = tk.Frame(hdr, bg=C_SURFACE)
        right.pack(side="right", fill="y", padx=22, pady=18)

        tk.Frame(page, bg=C_SEP, height=1).pack(fill="x")
        return right

    def _card(self, parent, **pack_kw) -> tk.Frame:
        """White surface card with no border."""
        card = tk.Frame(parent, bg=C_SURFACE)
        card.pack(**pack_kw)
        return card

    # ── Setup page ─────────────────────────────────────────────────────────────

    def _build_setup_page(self):
        page = tk.Frame(self._pane, bg=C_BG)
        self._pages["setup"] = page
        self._page_header(page, "Setup", "Verify your environment before running.")

        content = tk.Frame(page, bg=C_BG)
        content.pack(fill="both", expand=True, padx=20, pady=20)

        card = self._card(content, fill="x")

        checks = [
            ("python",   "Python 3.8+",
             "GitFollow requires Python 3.8 or newer."),
            ("requests", "requests library installed",
             "Handles all GitHub API calls. Run 'pip install requests' if missing."),
            ("token",    "GH_TOKEN configured",
             "Your GitHub Personal Access Token. Set it in the Settings tab."),
            ("username", "GH_USERNAME configured",
             "Your GitHub username. Set it in the Settings tab."),
            ("data_dir", "data/ directory exists",
             "Stores state.json which tracks follows and quality check results."),
        ]
        self._check_icons = {}
        for key, label, tooltip in checks:
            row = tk.Frame(card, bg=C_SURFACE)
            row.pack(fill="x", padx=20, pady=5)
            dot = tk.Label(row, text="●", font=("Segoe UI", 13),
                           bg=C_SURFACE, fg=C_MUTED, width=2)
            dot.pack(side="left")
            tk.Label(row, text=label, font=F_UI,
                     bg=C_SURFACE, fg=C_TEXT).pack(side="left", padx=(4, 0))
            _tip(row, tooltip, bg=C_SURFACE).pack(side="left", padx=(8, 0))
            self._check_icons[key] = dot

        tk.Frame(card, bg=C_SEP, height=1).pack(fill="x", padx=20, pady=(8, 0))

        btn_row = tk.Frame(card, bg=C_SURFACE)
        btn_row.pack(fill="x", padx=20, pady=14)
        RoundedButton(btn_row, "Re-check", self._run_checks,
                      width=100, height=32).pack(side="left", padx=(0, 8))
        RoundedButton(btn_row, "Auto-fix", self._autofix,
                      width=100, height=32, bg=C_SUCCESS).pack(side="left", padx=(0, 8))
        RoundedButton(btn_row, "Create Token",
                      lambda: webbrowser.open(
                          "https://github.com/settings/tokens/new"
                          "?scopes=user%3Afollow&description=GitFollow"
                      ),
                      width=120, height=32, bg=C_TEXT2).pack(side="left")

        self._setup_msg = tk.Label(card, text="", font=F_SM, bg=C_SURFACE)
        self._setup_msg.pack(anchor="w", padx=20, pady=(0, 14))

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
            self._check_icons[key].config(fg=C_SUCCESS if ok else C_DANGER)

        all_ok = all(results.values())
        self._setup_msg.config(
            text="All checks passed. You are ready to run." if all_ok
                 else "Fix the failing items above, then click Re-check.",
            fg=C_SUCCESS if all_ok else C_DANGER,
        )
        self._set_status("Checks complete." if all_ok else "Some checks failed.")

    def _autofix(self):
        import subprocess as sp
        fixed = []
        # In a frozen exe, requests is already bundled — pip cannot help here
        if not getattr(sys, "frozen", False):
            try:
                import requests  # noqa
            except ImportError:
                try:
                    no_win = getattr(sp, "CREATE_NO_WINDOW", 0)
                    sp.check_call(
                        [sys.executable, "-m", "pip", "install", "requests", "-q"],
                        creationflags=no_win,
                    )
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
            fixed.append("Created .env - open Settings to fill in credentials")
        messagebox.showinfo(
            "Auto-fix",
            ("Fixed:\n  " + "\n  ".join(fixed)) if fixed else "Nothing needed fixing.",
        )
        self._run_checks()

    # ── Dashboard page ─────────────────────────────────────────────────────────

    def _build_dashboard_page(self):
        page = tk.Frame(self._pane, bg=C_BG)
        self._pages["dashboard"] = page
        hdr_right = self._page_header(page, "Dashboard", "Live statistics.")

        self._dash_ts = tk.Label(hdr_right, text="", font=F_SM,
                                 bg=C_SURFACE, fg=C_MUTED)
        self._dash_ts.pack(side="right", padx=(0, 12), anchor="center")
        RoundedButton(hdr_right, "Refresh", self._refresh_dashboard,
                      width=90, height=30, font=F_SM).pack(side="right", padx=(0, 8))
        RoundedButton(hdr_right, "Clear Cache", self._clear_cache,
                      width=100, height=30, font=F_SM, bg=C_WARNING).pack(side="right")

        content = tk.Frame(page, bg=C_BG)
        content.pack(fill="both", expand=True, padx=20, pady=20)

        grid = tk.Frame(content, bg=C_BG)
        grid.pack(fill="x")

        card_defs = [
            ("following",  "FOLLOWING",       "Your current total following count on GitHub."),
            ("followers",  "FOLLOWERS",        "Your current total follower count on GitHub."),
            ("mutual",     "MUTUAL FOLLOWS",   "Accounts tracked by GitFollow that also follow you back."),
            ("followed",   "TOTAL FOLLOWED",   "Total accounts followed through GitFollow across all runs."),
            ("unfollowed", "TOTAL UNFOLLOWED", "Total accounts unfollowed through GitFollow across all runs."),
            ("cached",     "CACHED CHECKS",    "Quality check results stored locally to avoid re-checking."),
        ]
        self._stat_vars = {}
        for i, (key, label, tooltip) in enumerate(card_defs):
            col = i % 3
            row = i // 3
            card = tk.Frame(grid, bg=C_SURFACE, padx=20, pady=16)
            card.grid(row=row, column=col,
                      padx=(0 if col == 0 else 10, 0),
                      pady=(0 if row == 0 else 10, 0),
                      sticky="nsew")

            top_row = tk.Frame(card, bg=C_SURFACE)
            top_row.pack(fill="x")
            tk.Label(top_row, text=label, font=("Segoe UI", 8),
                     bg=C_SURFACE, fg=C_MUTED).pack(side="left")
            _tip(top_row, tooltip, bg=C_SURFACE).pack(side="right")

            var = tk.StringVar(value="--")
            self._stat_vars[key] = var
            tk.Label(card, textvariable=var, font=F_NUM,
                     bg=C_SURFACE, fg=C_TEXT).pack(anchor="w", pady=(8, 0))

        for col in range(3):
            grid.columnconfigure(col, weight=1)

        tk.Label(content,
            text="Following / Followers fetched live from the GitHub API. "
                 "Other stats read from local state.json.",
            font=F_XS, bg=C_BG, fg=C_MUTED,
            wraplength=700, justify="left",
        ).pack(anchor="w", pady=(14, 0))

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
        self._dash_ts.config(text="Fetching...")
        self._set_status("Fetching live counts from GitHub...")

        def _fetch():
            env   = {**load_env(), **os.environ}
            token = env.get("GH_TOKEN", "").strip()
            user  = env.get("GH_USERNAME", "").strip()
            if not token or not user:
                self.after(0, lambda: (
                    self._stat_vars["following"].set("--"),
                    self._stat_vars["followers"].set("--"),
                    self._dash_ts.config(text="Set credentials in Settings"),
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
                    data  = resp.json()
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
                    self._dash_ts.config(text="Network error"),
                    self._set_status(f"Error: {e}"),
                ))

        threading.Thread(target=_fetch, daemon=True).start()

    def _clear_cache(self):
        state = load_state()
        count = len(state.get("quality_cache", {}))
        if count == 0:
            messagebox.showinfo("Clear Cache", "Cache is already empty.")
            return
        if not messagebox.askyesno(
            "Clear Cache",
            f"Remove {count:,} cached quality-check results?\n"
            "All accounts will be re-evaluated on the next run.",
        ):
            return
        state["quality_cache"] = {}
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        self._stat_vars["cached"].set("0")
        self._set_status(f"Cleared {count:,} cached entries.")

    # ── Run page ───────────────────────────────────────────────────────────────

    def _build_run_page(self):
        page = tk.Frame(self._pane, bg=C_BG)
        self._pages["run"] = page
        self._page_header(page, "Run", "Execute follow or unfollow passes locally.")

        content = tk.Frame(page, bg=C_BG)
        content.pack(fill="both", expand=True, padx=20, pady=20)

        # Action buttons card
        card = self._card(content, fill="x", pady=(0, 12))
        btn_area = tk.Frame(card, bg=C_SURFACE, padx=20, pady=16)
        btn_area.pack(fill="x")

        self._btn_follow = RoundedButton(
            btn_area, "Run Follow", lambda: self._start_run("follow"),
            width=130, height=36,
        )
        self._btn_follow.pack(side="left", padx=(0, 10))
        Tooltip(self._btn_follow,
                "Searches GitHub for active developers meeting your quality criteria "
                "and follows up to FOLLOW_LIMIT of them.")

        self._btn_unfollow = RoundedButton(
            btn_area, "Run Unfollow", lambda: self._start_run("unfollow"),
            width=130, height=36, bg=C_TEXT2,
        )
        self._btn_unfollow.pack(side="left", padx=(0, 10))
        Tooltip(self._btn_unfollow,
                "Scans your following list and unfollows accounts that fail "
                "quality criteria. First run is slow; subsequent runs use the cache.")

        self._btn_stop = RoundedButton(
            btn_area, "Stop", self._stop_run,
            width=80, height=36, bg=C_DANGER,
        )
        self._btn_stop.pack(side="left")
        self._btn_stop.config_state(disabled=True)

        clear_lbl = tk.Label(btn_area, text="Clear Log", font=F_SM,
                             fg=C_ACCENT, bg=C_SURFACE, cursor="hand2")
        clear_lbl.pack(side="right")
        clear_lbl.bind("<Button-1>", lambda _e: self._clear_log())

        # Terminal card
        term = tk.Frame(content, bg=C_TERM_BG,
                        highlightthickness=1, highlightbackground=C_SEP)
        term.pack(fill="both", expand=True)

        # Minimal header bar — no dots
        chrome = tk.Frame(term, bg=C_SURFACE)
        chrome.pack(fill="x")
        tk.Label(chrome, text="Output", font=F_MONO,
                 bg=C_SURFACE, fg=C_MUTED).pack(side="left", padx=14, pady=6)
        tk.Frame(term, bg=C_SEP, height=1).pack(fill="x")

        self._log = scrolledtext.ScrolledText(
            term, font=F_MONO, state="disabled",
            bg=C_TERM_BG, fg=C_TERM_FG, insertbackground=C_TERM_FG,
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
        else:
            env.pop("QUALITY_UNFOLLOW", None)
            os.environ.pop("QUALITY_UNFOLLOW", None)
            os.environ.pop("FOLLOW_LIMIT", None)
        os.environ.update(env)
        self._running = True
        self._btn_follow.config_state(disabled=True)
        self._btn_unfollow.config_state(disabled=True)
        self._btn_stop.config_state(disabled=False)
        self._set_status(f"Running {mode}...")
        self._log_write(
            f"\n{'=' * 60}\n"
            f"  GitFollow  -  {mode.title()} Run  -  "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{'=' * 60}\n\n"
        )
        handler = _GUILogHandler(self._log_write)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))

        def _worker():
            root_log = logging.getLogger()
            root_log.setLevel(logging.INFO)
            # Remove any StreamHandlers that write to stderr/stdout — these are
            # None in a windowed exe and will suppress our handler via handleError.
            for h in root_log.handlers[:]:
                if isinstance(h, logging.StreamHandler) and not isinstance(h, _GUILogHandler):
                    root_log.removeHandler(h)
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
        self._btn_stop.config_state(disabled=True)
        self._set_status("Stop requested - finishing current operation...")
        self._log_write("\n  Stop requested - will halt after current operation.\n")

    def _run_done(self):
        self._running = False
        self._btn_follow.config_state(disabled=False)
        self._btn_unfollow.config_state(disabled=False)
        self._btn_stop.config_state(disabled=True)
        self._log_write(
            f"\n{'=' * 60}\n"
            f"  Run complete  -  {datetime.now().strftime('%H:%M:%S')}\n"
            f"{'=' * 60}\n"
        )
        self._set_status("Run complete.")
        self._refresh_dashboard()

    def _log_write(self, text: str):
        self._log_queue.put(text)

    def _poll_log_queue(self):
        try:
            while True:
                text = self._log_queue.get_nowait()
                self._log.config(state="normal")
                self._log.insert(tk.END, text)
                self._log.see(tk.END)
                self._log.config(state="disabled")
        except queue.Empty:
            pass
        self.after(50, self._poll_log_queue)

    def _clear_log(self):
        self._log.config(state="normal")
        self._log.delete("1.0", tk.END)
        self._log.config(state="disabled")

    # ── Settings page ──────────────────────────────────────────────────────────

    def _build_settings_page(self):
        page = tk.Frame(self._pane, bg=C_BG)
        self._pages["settings"] = page
        self._page_header(page, "Settings",
                          "Saved to a local .env file - never committed to git.")

        # Scrollable container
        content = tk.Frame(page, bg=C_BG)
        content.pack(fill="both", expand=True, padx=20, pady=20)

        card = self._card(content, fill="x")
        form = tk.Frame(card, bg=C_SURFACE)
        form.pack(fill="x", padx=24, pady=16)

        # Fields: (env_key, label, secret, default, tip)  or  (None, "SECTION", ...)
        FIELDS = [
            (None, "AUTHENTICATION", None, None, None),
            ("GH_TOKEN",    "GitHub Token",    True,  "",
             "Personal Access Token with user:follow scope. "
             "Stored locally in .env, never shared."),
            ("GH_USERNAME", "GitHub Username", False, "",
             "Your exact GitHub username (case-insensitive)."),

            (None, "FOLLOW BEHAVIOR", None, None, None),
            ("FOLLOW_LIMIT",   "Follow Limit",        False, "150",
             "Maximum new follows per run. Keep at or below 150/day."),
            ("UNFOLLOW_HOURS", "Unfollow After (hrs)", False, "24",
             "Hours before unfollowing a non-reciprocator."),
            ("WHITELIST",      "Whitelist",            False, "",
             "Comma-separated usernames to never unfollow."),

            (None, "QUALITY FILTERS", None, None, None),
            ("ACTIVITY_DAYS",        "Activity Days",    False, "30",
             "Skip users who haven't pushed a commit in this many days."),
            ("MIN_FOLLOWERS",        "Min Followers",    False, "1",
             "Only follow users with at least this many followers."),
            ("MAX_REPOS",            "Max Repos",        False, "500",
             "Skip accounts with more public repos than this. Catches mass-forking bots."),
            ("MAX_FF_RATIO",         "Max F/F Ratio",    False, "10.0",
             "Skip accounts whose following/followers ratio exceeds this. "
             "Filters follow-farmers."),
            ("MIN_ACCOUNT_AGE_DAYS", "Min Account Age",  False, "30",
             "Skip accounts newer than this many days. Filters throwaway accounts."),
            ("CACHE_DAYS",           "Cache Days",       False, "7",
             "Days to cache quality check results to save API quota."),
        ]

        self._settings_vars = {}
        row_idx = 0
        first_section = True

        for item in FIELDS:
            key, label, secret, default, tooltip = item

            if key is None:
                # Section separator + heading
                if not first_section:
                    tk.Frame(form, bg=C_SEP, height=1).grid(
                        row=row_idx, column=0, columnspan=2,
                        sticky="ew", pady=(10, 6)
                    )
                    row_idx += 1
                first_section = False
                tk.Label(form, text=label, font=("Segoe UI", 8, "bold"),
                         bg=C_SURFACE, fg=C_MUTED).grid(
                    row=row_idx, column=0, columnspan=2,
                    sticky="w", pady=(0, 4)
                )
                row_idx += 1
                continue

            lbl_f = tk.Frame(form, bg=C_SURFACE)
            lbl_f.grid(row=row_idx, column=0, padx=(0, 16), pady=4, sticky="w")
            tk.Label(lbl_f, text=label, font=F_UI, bg=C_SURFACE,
                     fg=C_TEXT, width=20, anchor="w").pack(side="left")
            _tip(lbl_f, tooltip, bg=C_SURFACE).pack(side="left", padx=(4, 0))

            var = tk.StringVar(value=default)
            self._settings_vars[key] = var
            entry = tk.Entry(
                form, textvariable=var, show="*" if secret else "",
                font=F_UI, width=36,
                bg=C_BG, fg=C_TEXT, relief="flat",
                highlightthickness=1,
                highlightbackground=C_SEP,
                highlightcolor=C_ACCENT,
                insertbackground=C_TEXT,
            )
            entry.grid(row=row_idx, column=1, pady=4, sticky="ew")
            row_idx += 1

        # Quality unfollow toggle
        tk.Frame(form, bg=C_SEP, height=1).grid(
            row=row_idx, column=0, columnspan=2, sticky="ew", pady=(10, 6)
        )
        row_idx += 1
        qu_f = tk.Frame(form, bg=C_SURFACE)
        qu_f.grid(row=row_idx, column=0, padx=(0, 16), pady=4, sticky="w")
        tk.Label(qu_f, text="Quality Unfollow", font=F_UI, bg=C_SURFACE,
                 fg=C_TEXT, width=20, anchor="w").pack(side="left")
        _tip(qu_f,
             "When enabled, Run Unfollow also cleans up existing follows that fail "
             "quality criteria. First run is slow; subsequent runs use the cache.",
             bg=C_SURFACE).pack(side="left", padx=(4, 0))
        self._qu_var = tk.BooleanVar()
        tk.Checkbutton(form, variable=self._qu_var,
                       bg=C_SURFACE, activebackground=C_SURFACE,
                       fg=C_TEXT, activeforeground=C_TEXT,
                       selectcolor=C_BG,
                       relief="flat").grid(row=row_idx, column=1, pady=4, sticky="w")
        form.columnconfigure(1, weight=1)

        # Save / load
        tk.Frame(card, bg=C_SEP, height=1).pack(fill="x", padx=24)
        btn_row = tk.Frame(card, bg=C_SURFACE)
        btn_row.pack(fill="x", padx=24, pady=16)
        RoundedButton(btn_row, "Save Settings", self._save_settings,
                      width=130, height=34).pack(side="left", padx=(0, 12))
        load_lbl = tk.Label(btn_row, text="Load from .env", font=F_SM,
                            fg=C_ACCENT, bg=C_SURFACE, cursor="hand2")
        load_lbl.pack(side="left")
        load_lbl.bind("<Button-1>", lambda _e: self._load_settings())

        self._settings_msg = tk.Label(card, text="", font=F_SM, bg=C_SURFACE)
        self._settings_msg.pack(anchor="w", padx=24, pady=(0, 12))

    def _save_settings(self):
        _INT_FIELDS   = {"FOLLOW_LIMIT", "UNFOLLOW_HOURS", "ACTIVITY_DAYS",
                         "MIN_FOLLOWERS", "MAX_REPOS", "MIN_ACCOUNT_AGE_DAYS", "CACHE_DAYS"}
        _FLOAT_FIELDS = {"MAX_FF_RATIO"}
        env = {k: v.get() for k, v in self._settings_vars.items()}
        for k in _INT_FIELDS:
            val = env.get(k, "").strip()
            if val:
                try:
                    int(val)
                except ValueError:
                    self._settings_msg.config(
                        text=f"{k} must be a whole number (got '{val}')", fg=C_DANGER)
                    return
        for k in _FLOAT_FIELDS:
            val = env.get(k, "").strip()
            if val:
                try:
                    float(val)
                except ValueError:
                    self._settings_msg.config(
                        text=f"{k} must be a number (got '{val}')", fg=C_DANGER)
                    return
        env["QUALITY_UNFOLLOW"] = "true" if self._qu_var.get() else "false"
        save_env(env)
        self._settings_msg.config(text=f"Saved to {ENV_FILE}", fg=C_SUCCESS)
        self._set_status("Settings saved.")
        self._run_checks()

    def _load_settings(self):
        env = load_env()
        for k, var in self._settings_vars.items():
            var.set(env.get(k, var.get()))
        self._qu_var.set(env.get("QUALITY_UNFOLLOW", "false").lower() == "true")
        self._settings_msg.config(text=f"Loaded from {ENV_FILE}", fg=C_MUTED)

    # ── Shared ─────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        self._status_var.set(msg)

    def _on_open(self):
        self._run_checks()
        self._refresh_dashboard()
        self._load_settings()


if __name__ == "__main__":
    App().mainloop()
