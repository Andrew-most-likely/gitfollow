"""
GitFollow GUI - Desktop interface for GitFollow.
Run: python gui.py   or double-click GitFollow.exe
"""

import colorsys
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

VERSION = "2.0"

# ── Design tokens ─────────────────────────────────────────────────────────────

C_BG       = "#F2F2F7"
C_SURFACE  = "#FFFFFF"
C_SIDEBAR  = "#111111"
C_SB_H     = "#2A2A2A"
C_SB_S     = "#1E1E1E"
C_ACCENT   = "#007AFF"
C_SUCCESS  = "#34C759"
C_DANGER   = "#FF3B30"
C_TEXT     = "#1C1C1E"
C_TEXT2    = "#636366"
C_MUTED    = "#AEAEB2"
C_SEP      = "#E5E5EA"
C_SHADOW   = "#C8C8CE"
C_TERM     = "#0A0A0A"
C_TERM_FG  = "#E8E8ED"

F_APP  = ("Segoe UI", 13, "bold")
F_H1   = ("Segoe UI", 22, "bold")
F_H2   = ("Segoe UI", 13, "bold")
F_UI   = ("Segoe UI", 10)
F_BOLD = ("Segoe UI", 10, "bold")
F_SM   = ("Segoe UI", 9)
F_XS   = ("Segoe UI", 8)
F_BIG  = ("Segoe UI", 34, "bold")
F_MONO = ("Consolas", 9)
F_NAV  = ("Segoe UI", 10)
F_ICON = ("Segoe UI", 15)

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
    return {"following": {}, "quality_cache": {},
            "stats": {"followed": 0, "unfollowed": 0, "mutual": 0}}


def _darken(hex_color: str, amount: float) -> str:
    hx = hex_color.lstrip("#")
    r, g, b = (int(hx[i:i+2], 16) / 255 for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, max(0.0, v - amount))
    return "#{:02x}{:02x}{:02x}".format(int(r2*255), int(g2*255), int(b2*255))


# ── Shadow card ───────────────────────────────────────────────────────────────
# Renders a white card with a soft bottom-right drop shadow by showing a
# slightly larger, darker frame behind the card frame.

def shadow_card(parent, padx=0, pady=0, **pack_kw) -> tk.Frame:
    wrap = tk.Frame(parent, bg=C_SHADOW)
    wrap.pack(**pack_kw)
    card = tk.Frame(wrap, bg=C_SURFACE)
    card.pack(fill="both", expand=True,
              padx=(0, 3), pady=(0, 4))
    if padx or pady:
        card.configure(padx=padx, pady=pady)
    return card


# ── Rounded button ────────────────────────────────────────────────────────────

class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command,
                 width=130, height=34, radius=8,
                 bg=C_ACCENT, fg="white", font=F_BOLD, **kwargs):
        try:
            pbg = parent.cget("bg")
        except Exception:
            pbg = C_BG
        super().__init__(parent, width=width, height=height,
                         bg=pbg, highlightthickness=0, **kwargs)
        self._text     = text
        self._orig_cmd = command
        self._command  = command
        self._orig_bg  = bg
        self._bg       = bg
        self._hov_bg   = _darken(bg, 0.12)
        self._fg       = fg
        self._radius   = radius
        self._font     = font
        self._btn_w    = width
        self._btn_h    = height
        self._disabled = False
        self._hovering = False
        self._draw()
        self.bind("<Enter>",    self._on_enter)
        self.bind("<Leave>",    self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _rrect(self, color: str):
        self.delete("all")
        w, h, r = self._btn_w, self._btn_h, self._radius
        for args in [
            (0,     0,     2*r,   2*r,   90,  90),
            (w-2*r, 0,     w,     2*r,   0,   90),
            (0,     h-2*r, 2*r,   h,     180, 90),
            (w-2*r, h-2*r, w,     h,     270, 90),
        ]:
            self.create_arc(*args[:4], start=args[4], extent=args[5],
                            fill=color, outline=color)
        self.create_rectangle(r, 0,   w-r, h,   fill=color, outline=color)
        self.create_rectangle(0, r,   w,   h-r, fill=color, outline=color)
        self.create_text(w//2, h//2, text=self._text,
                         fill=self._fg, font=self._font)

    def _draw(self):
        color = C_MUTED if self._disabled else \
                (self._hov_bg if self._hovering else self._bg)
        self._rrect(color)

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


# ── Tooltip ───────────────────────────────────────────────────────────────────

class Tooltip:
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
        tk.Label(tw, text=self._text, justify="left", wraplength=260,
                 bg="#1C1C1E", fg="white", font=F_SM, padx=12, pady=8).pack()

    def _hide(self, event=None):
        if self._win:
            self._win.destroy()
            self._win = None


def _tip(parent, text: str, bg=C_BG) -> tk.Label:
    lbl = tk.Label(parent, text="?", font=("Segoe UI", 8, "bold"),
                   fg=C_MUTED, bg=bg, cursor="question_arrow", width=2)
    Tooltip(lbl, text)
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


# ── Scrollable frame ──────────────────────────────────────────────────────────

class ScrollFrame(tk.Frame):
    """A vertically scrollable frame. Add children to .inner."""

    def __init__(self, parent, bg=C_BG, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)
        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self._sb     = tk.Scrollbar(self, orient="vertical",
                                    command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._sb.set)
        self._sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self._canvas, bg=bg)
        self._win  = self._canvas.create_window((0, 0), window=self.inner,
                                                anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>", self._on_scroll)
        self.inner.bind("<MouseWheel>", self._on_scroll)

    def _on_inner_configure(self, _e=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        self._canvas.itemconfig(self._win, width=e.width)

    def _on_scroll(self, e):
        self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")


# ── App ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GitFollow")
        self.geometry("1080x700")
        self.resizable(False, False)
        self.configure(bg=C_SIDEBAR)
        self._running      = False
        self._pages        = {}
        self._nav_widgets  = {}
        self._current_page = None
        self._build_ui()
        self.after(100, self._on_open)

    # ── Shell ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._sidebar = tk.Frame(self, bg=C_SIDEBAR, width=200)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        self._pane = tk.Frame(self, bg=C_BG)
        self._pane.pack(side="left", fill="both", expand=True)

        self._build_sidebar()
        self._build_setup_page()
        self._build_dashboard_page()
        self._build_run_page()
        self._build_settings_page()

        # Status bar
        sb = tk.Frame(self._pane, bg=C_SURFACE, height=28)
        sb.pack(side="bottom", fill="x")
        sb.pack_propagate(False)
        tk.Frame(self._pane, bg=C_SEP, height=1).pack(side="bottom", fill="x")

        self._status_dot = tk.Label(sb, text="●", font=("Segoe UI", 9),
                                    fg=C_SUCCESS, bg=C_SURFACE)
        self._status_dot.pack(side="left", padx=(14, 4), pady=6)
        self._status_var = tk.StringVar(value="Ready")
        tk.Label(sb, textvariable=self._status_var,
                 bg=C_SURFACE, fg=C_TEXT2, font=F_SM).pack(side="left", pady=6)

        self._show_page("setup")

    # ── Sidebar ────────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        # Branding
        brand = tk.Frame(self._sidebar, bg=C_SIDEBAR, height=64)
        brand.pack(fill="x")
        brand.pack_propagate(False)
        tk.Label(brand, text="GitFollow", bg=C_SIDEBAR, fg="white",
                 font=F_APP).pack(side="left", padx=20, pady=20)
        tk.Label(brand, text=f"v{VERSION}", bg=C_SIDEBAR, fg="#555558",
                 font=F_XS).pack(side="left", pady=24)

        tk.Frame(self._sidebar, bg="#2A2A2A", height=1).pack(fill="x")
        tk.Frame(self._sidebar, bg=C_SIDEBAR, height=8).pack(fill="x")

        nav_items = [
            ("setup",     "○", "Setup"),
            ("dashboard", "◈", "Dashboard"),
            ("run",       "▷", "Run"),
            ("settings",  "⚙", "Settings"),
        ]
        for key, icon, label in nav_items:
            self._make_nav_item(key, icon, label)

        tk.Frame(self._sidebar, bg=C_SIDEBAR).pack(fill="both", expand=True)
        tk.Label(self._sidebar, text="MIT License", bg=C_SIDEBAR,
                 fg="#3A3A3A", font=F_XS).pack(side="bottom", pady=14)

    def _make_nav_item(self, key: str, icon: str, label: str):
        frame = tk.Frame(self._sidebar, bg=C_SIDEBAR, cursor="hand2")
        frame.pack(fill="x", padx=10, pady=1)

        accent = tk.Frame(frame, bg=C_SIDEBAR, width=3)
        accent.pack(side="left", fill="y")

        icon_lbl = tk.Label(frame, text=icon, font=F_ICON,
                            bg=C_SIDEBAR, fg="#555558", width=3)
        icon_lbl.pack(side="left", pady=10)

        text_lbl = tk.Label(frame, text=label, font=F_NAV,
                            bg=C_SIDEBAR, fg="#666669", anchor="w", padx=6)
        text_lbl.pack(side="left", fill="x", expand=True, pady=10)

        def click(_e=None, k=key):
            self._show_page(k)

        def enter(_e=None):
            if self._current_page != key:
                for w in (frame, icon_lbl, text_lbl, accent):
                    w.config(bg=C_SB_H)

        def leave(_e=None):
            if self._current_page != key:
                for w in (frame, icon_lbl, text_lbl, accent):
                    w.config(bg=C_SIDEBAR)

        for w in (frame, accent, icon_lbl, text_lbl):
            w.bind("<Button-1>", click)
            w.bind("<Enter>",    enter)
            w.bind("<Leave>",    leave)

        self._nav_widgets[key] = (frame, accent, icon_lbl, text_lbl)

    def _show_page(self, name: str):
        self._current_page = name
        for pg in self._pages.values():
            pg.pack_forget()
        self._pages[name].pack(fill="both", expand=True)

        for key, (frame, accent, icon_lbl, text_lbl) in self._nav_widgets.items():
            if key == name:
                for w in (frame, icon_lbl, text_lbl):
                    w.config(bg=C_SB_S)
                accent.config(bg=C_ACCENT)
                icon_lbl.config(fg="white")
                text_lbl.config(fg="white", font=("Segoe UI", 10, "bold"))
            else:
                for w in (frame, accent, icon_lbl, text_lbl):
                    w.config(bg=C_SIDEBAR)
                icon_lbl.config(fg="#555558")
                text_lbl.config(fg="#666669", font=F_NAV)

    # ── Setup page ─────────────────────────────────────────────────────────────

    def _build_setup_page(self):
        page = tk.Frame(self._pane, bg=C_BG)
        self._pages["setup"] = page

        # Large page title directly on gray bg
        tk.Label(page, text="Setup", font=F_H1,
                 bg=C_BG, fg=C_TEXT).pack(anchor="w", padx=28, pady=(28, 4))
        tk.Label(page, text="Verify your environment before running.",
                 font=F_SM, bg=C_BG, fg=C_MUTED).pack(anchor="w", padx=28, pady=(0, 20))

        card = shadow_card(page, fill="x", padx=28, pady=(0, 0))

        checks = [
            ("python",   "Python 3.8+",
             "GitFollow requires Python 3.8 or newer."),
            ("requests", "requests library installed",
             "Handles all GitHub API calls. Run 'pip install requests' if missing."),
            ("token",    "GH_TOKEN configured",
             "Your GitHub Personal Access Token. Set it in Settings."),
            ("username", "GH_USERNAME configured",
             "Your GitHub username. Set it in Settings."),
            ("data_dir", "data/ directory exists",
             "Stores state.json which tracks follows and quality check results."),
        ]
        self._check_icons = {}
        for i, (key, label, tooltip) in enumerate(checks):
            if i:
                tk.Frame(card, bg=C_SEP, height=1).pack(fill="x", padx=20)
            row = tk.Frame(card, bg=C_SURFACE)
            row.pack(fill="x", padx=20, pady=14)
            dot = tk.Label(row, text="●", font=("Segoe UI", 14),
                           bg=C_SURFACE, fg=C_MUTED, width=2)
            dot.pack(side="left")
            tk.Label(row, text=label, font=F_UI,
                     bg=C_SURFACE, fg=C_TEXT).pack(side="left", padx=(8, 0))
            _tip(row, tooltip, bg=C_SURFACE).pack(side="left", padx=(10, 0))
            self._check_icons[key] = dot

        self._setup_msg = tk.Label(card, text="", font=F_SM,
                                   bg=C_SURFACE, fg=C_MUTED)
        self._setup_msg.pack(anchor="w", padx=20, pady=(8, 4))

        tk.Frame(card, bg=C_SEP, height=1).pack(fill="x", padx=20)
        btn_row = tk.Frame(card, bg=C_SURFACE)
        btn_row.pack(fill="x", padx=20, pady=16)
        RoundedButton(btn_row, "Re-check",    self._run_checks,
                      width=105, height=32).pack(side="left", padx=(0, 8))
        RoundedButton(btn_row, "Auto-fix",    self._autofix,
                      width=105, height=32, bg=C_SUCCESS).pack(side="left", padx=(0, 8))
        RoundedButton(btn_row, "Create Token",
                      lambda: webbrowser.open(
                          "https://github.com/settings/tokens/new"
                          "?scopes=user%3Afollow&description=GitFollow"),
                      width=125, height=32, bg=C_TEXT2).pack(side="left")

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
        self._set_status("Ready" if all_ok else "Some checks failed",
                         C_SUCCESS if all_ok else C_DANGER)

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
            fixed.append("Created .env - open Settings to fill in credentials")
        messagebox.showinfo("Auto-fix",
            ("Fixed:\n  " + "\n  ".join(fixed)) if fixed else "Nothing needed fixing.")
        self._run_checks()

    # ── Dashboard page ─────────────────────────────────────────────────────────

    def _build_dashboard_page(self):
        page = tk.Frame(self._pane, bg=C_BG)
        self._pages["dashboard"] = page

        # Title row
        title_row = tk.Frame(page, bg=C_BG)
        title_row.pack(fill="x", padx=28, pady=(28, 4))
        tk.Label(title_row, text="Dashboard", font=F_H1,
                 bg=C_BG, fg=C_TEXT).pack(side="left")
        self._dash_ts = tk.Label(title_row, text="", font=F_SM,
                                 bg=C_BG, fg=C_MUTED)
        self._dash_ts.pack(side="right", padx=(0, 4), anchor="s", pady=8)
        RoundedButton(title_row, "Refresh", self._refresh_dashboard,
                      width=90, height=30, font=F_SM).pack(side="right", pady=4)

        tk.Label(page, text="Live statistics from GitHub and local state.",
                 font=F_SM, bg=C_BG, fg=C_MUTED).pack(anchor="w", padx=28, pady=(0, 20))

        # 3-column stat grid
        grid = tk.Frame(page, bg=C_BG)
        grid.pack(fill="x", padx=28)

        stats = [
            ("following",  "Following",         "Your current total following count on GitHub."),
            ("followers",  "Followers",          "Your current total follower count on GitHub."),
            ("mutual",     "Mutual",             "Accounts tracked by GitFollow that follow you back."),
            ("followed",   "Total Followed",     "Total accounts followed through GitFollow."),
            ("unfollowed", "Total Unfollowed",   "Total accounts unfollowed through GitFollow."),
            ("cached",     "Cached Checks",      "Quality check results stored locally."),
        ]
        self._stat_vars = {}
        for i, (key, label, tip_text) in enumerate(stats):
            col = i % 3
            row = i // 3

            wrap = tk.Frame(grid, bg=C_SHADOW)
            wrap.grid(row=row, column=col,
                      padx=(0, 0 if col == 2 else 12),
                      pady=(0, 0 if row == 1 else 12),
                      sticky="nsew")
            card = tk.Frame(wrap, bg=C_SURFACE, padx=22, pady=18)
            card.pack(fill="both", expand=True, padx=(0, 3), pady=(0, 4))

            top = tk.Frame(card, bg=C_SURFACE)
            top.pack(fill="x")
            tk.Label(top, text=label.upper(), font=("Segoe UI", 8),
                     bg=C_SURFACE, fg=C_MUTED).pack(side="left")
            _tip(top, tip_text, bg=C_SURFACE).pack(side="right")

            var = tk.StringVar(value="--")
            self._stat_vars[key] = var
            tk.Label(card, textvariable=var, font=F_BIG,
                     bg=C_SURFACE, fg=C_TEXT).pack(anchor="w", pady=(10, 0))

        for col in range(3):
            grid.columnconfigure(col, weight=1)

        tk.Label(page,
            text="Following / Followers fetched live from GitHub API. "
                 "Other stats read from local state.json.",
            font=F_XS, bg=C_BG, fg=C_MUTED,
            wraplength=700, justify="left",
        ).pack(anchor="w", padx=28, pady=(16, 0))

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

        def _fetch():
            env   = {**load_env(), **os.environ}
            token = env.get("GH_TOKEN", "").strip()
            user  = env.get("GH_USERNAME", "").strip()
            if not token or not user:
                self.after(0, lambda: (
                    self._stat_vars["following"].set("--"),
                    self._stat_vars["followers"].set("--"),
                    self._dash_ts.config(text="Set credentials in Settings"),
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
                        self._set_status("Dashboard refreshed"),
                    ))
                else:
                    self.after(0, lambda: (
                        self._stat_vars["following"].set("Err"),
                        self._stat_vars["followers"].set("Err"),
                        self._dash_ts.config(text=f"Error {resp.status_code}"),
                    ))
            except Exception as e:
                self.after(0, lambda: self._dash_ts.config(text="Network error"))

        threading.Thread(target=_fetch, daemon=True).start()

    # ── Run page ───────────────────────────────────────────────────────────────

    def _build_run_page(self):
        page = tk.Frame(self._pane, bg=C_BG)
        self._pages["run"] = page

        tk.Label(page, text="Run", font=F_H1,
                 bg=C_BG, fg=C_TEXT).pack(anchor="w", padx=28, pady=(28, 4))
        tk.Label(page, text="Execute follow or unfollow passes locally on your machine.",
                 font=F_SM, bg=C_BG, fg=C_MUTED).pack(anchor="w", padx=28, pady=(0, 20))

        # Two clickable action cards side by side
        cards_row = tk.Frame(page, bg=C_BG)
        cards_row.pack(fill="x", padx=28, pady=(0, 12))

        self._btn_follow   = self._action_card(
            cards_row,
            icon="▷", title="Run Follow",
            desc="Discover and follow active developers matching your quality filters.",
            command=lambda: self._start_run("follow"),
            color=C_ACCENT,
            side="left",
        )
        self._btn_unfollow = self._action_card(
            cards_row,
            icon="↓", title="Run Unfollow",
            desc="Clean up your following list. Removes accounts that fail quality criteria.",
            command=lambda: self._start_run("unfollow"),
            color="#636366",
            side="left",
        )

        # Stop / Clear row
        ctrl = tk.Frame(page, bg=C_BG)
        ctrl.pack(fill="x", padx=28, pady=(0, 10))
        self._btn_stop = RoundedButton(ctrl, "Stop", self._stop_run,
                                       width=80, height=30, bg=C_DANGER, font=F_SM)
        self._btn_stop.pack(side="left")
        self._btn_stop.config_state(disabled=True)
        clear = tk.Label(ctrl, text="Clear log", font=F_SM,
                         fg=C_ACCENT, bg=C_BG, cursor="hand2")
        clear.pack(side="right")
        clear.bind("<Button-1>", lambda _e: self._clear_log())

        # Terminal
        term_wrap = tk.Frame(page, bg=C_SHADOW)
        term_wrap.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        term = tk.Frame(term_wrap, bg=C_TERM)
        term.pack(fill="both", expand=True, padx=(0, 3), pady=(0, 4))

        chrome = tk.Frame(term, bg="#1A1A1A")
        chrome.pack(fill="x")
        dots = tk.Frame(chrome, bg="#1A1A1A")
        dots.pack(side="left", padx=14, pady=9)
        for col in ("#FF5F56", "#FFBD2E", "#27C93F"):
            tk.Label(dots, text="●", fg=col, bg="#1A1A1A",
                     font=("Segoe UI", 9)).pack(side="left", padx=2)
        tk.Label(chrome, text="Output", font=("Segoe UI", 9),
                 bg="#1A1A1A", fg="#555558").pack(pady=9)

        self._log = scrolledtext.ScrolledText(
            term, font=F_MONO, state="disabled",
            bg=C_TERM, fg=C_TERM_FG, insertbackground=C_TERM_FG,
            relief="flat", borderwidth=0, selectbackground="#264f78",
        )
        self._log.pack(fill="both", expand=True, padx=4, pady=(0, 4))

    def _action_card(self, parent, icon, title, desc, command, color, side):
        """Clickable card with icon, title, and description."""
        wrap = tk.Frame(parent, bg=C_SHADOW)
        wrap.pack(side=side, fill="both", expand=True,
                  padx=(0, 0 if side == "right" else 12))
        card = tk.Frame(wrap, bg=C_SURFACE, padx=24, pady=22, cursor="hand2")
        card.pack(fill="both", expand=True, padx=(0, 3), pady=(0, 4))

        tk.Label(card, text=icon, font=("Segoe UI", 26),
                 bg=C_SURFACE, fg=color).pack(anchor="w")
        tk.Label(card, text=title, font=F_H2,
                 bg=C_SURFACE, fg=C_TEXT).pack(anchor="w", pady=(8, 0))
        tk.Label(card, text=desc, font=F_SM, bg=C_SURFACE, fg=C_MUTED,
                 wraplength=340, justify="left").pack(anchor="w", pady=(4, 0))

        # Bind click on card and all children
        def _click(_e=None):
            if not getattr(self, "_running", False):
                command()

        for w in [card] + card.winfo_children():
            w.bind("<Button-1>", _click)

        # Return a duck-typed object with config_state
        class _CardRef:
            def __init__(self_, c, lbl_icon):
                self_._card = c
                self_._icon = lbl_icon
                self_._orig_color = color
                self_._cmd = command

            def config_state(self_, disabled: bool):
                state_color = C_MUTED if disabled else self_._orig_color
                self_._icon.config(fg=state_color)
                new_cursor = "" if disabled else "hand2"
                for w in [self_._card] + self_._card.winfo_children():
                    try:
                        w.config(cursor=new_cursor)
                    except Exception:
                        pass

        icon_lbl = card.winfo_children()[0]
        return _CardRef(card, icon_lbl)

    def _start_run(self, mode: str):
        if self._running:
            messagebox.showinfo("Already running", "A run is already in progress.")
            return
        env = load_env()
        merged = {**env, **os.environ}
        if not merged.get("GH_TOKEN") or not merged.get("GH_USERNAME"):
            messagebox.showerror("Missing credentials",
                "GH_TOKEN and GH_USERNAME must be set.\nGo to the Settings tab.")
            return
        if mode == "unfollow":
            env["QUALITY_UNFOLLOW"] = "true"
            env["FOLLOW_LIMIT"]     = "0"
        os.environ.update(env)
        self._running = True
        self._btn_follow.config_state(disabled=True)
        self._btn_unfollow.config_state(disabled=True)
        self._btn_stop.config_state(disabled=False)
        self._set_status(f"Running {mode}...", C_WARNING)
        self._log_write(
            f"\n{'─' * 56}\n"
            f"  {mode.title()} Run  ·  "
            f"{datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n"
            f"{'─' * 56}\n\n"
        )
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
        self._btn_stop.config_state(disabled=True)
        self._set_status("Stopping after current operation...", C_WARNING)
        self._log_write("\n  Stop requested — will halt after current operation.\n")

    def _run_done(self):
        self._running = False
        self._btn_follow.config_state(disabled=False)
        self._btn_unfollow.config_state(disabled=False)
        self._btn_stop.config_state(disabled=True)
        self._log_write(
            f"\n{'─' * 56}\n"
            f"  Complete  ·  {datetime.now().strftime('%H:%M:%S')}\n"
            f"{'─' * 56}\n"
        )
        self._set_status("Run complete", C_SUCCESS)
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

    # ── Settings page ──────────────────────────────────────────────────────────

    def _build_settings_page(self):
        page = tk.Frame(self._pane, bg=C_BG)
        self._pages["settings"] = page

        tk.Label(page, text="Settings", font=F_H1,
                 bg=C_BG, fg=C_TEXT).pack(anchor="w", padx=28, pady=(28, 4))
        tk.Label(page, text="Saved to a local .env file — never committed to git.",
                 font=F_SM, bg=C_BG, fg=C_MUTED).pack(anchor="w", padx=28, pady=(0, 20))

        sf = ScrollFrame(page)
        sf.pack(fill="both", expand=True)
        inner = sf.inner

        self._settings_vars = {}

        sections = [
            ("AUTHENTICATION", [
                ("GH_TOKEN",    "GitHub Token",        True,  "",
                 "Personal Access Token with user:follow scope. Stored in .env, never shared."),
                ("GH_USERNAME", "GitHub Username",     False, "",
                 "Your exact GitHub username (case-insensitive)."),
            ]),
            ("FOLLOW BEHAVIOR", [
                ("FOLLOW_LIMIT",   "Follow Limit",         False, "150",
                 "Maximum new follows per run. Keep at or below 150/day."),
                ("UNFOLLOW_HOURS", "Unfollow After (hrs)", False, "24",
                 "Hours before unfollowing a non-reciprocator."),
                ("WHITELIST",      "Whitelist",            False, "",
                 "Comma-separated usernames to never unfollow."),
            ]),
            ("QUALITY FILTERS", [
                ("ACTIVITY_DAYS",        "Activity Days",    False, "30",
                 "Skip users who haven't pushed in this many days."),
                ("MIN_FOLLOWERS",        "Min Followers",    False, "1",
                 "Only follow users with at least this many followers."),
                ("MAX_REPOS",            "Max Repos",        False, "500",
                 "Skip accounts with more public repos than this. Catches mass-forking bots."),
                ("MAX_FF_RATIO",         "Max F/F Ratio",    False, "10.0",
                 "Skip follow-farmers: accounts whose following/followers ratio exceeds this."),
                ("MIN_ACCOUNT_AGE_DAYS", "Min Account Age",  False, "30",
                 "Skip accounts newer than this many days. Filters throwaway accounts."),
                ("CACHE_DAYS",           "Cache Days",       False, "7",
                 "Days to cache quality check results to save API quota."),
            ]),
        ]

        for section_label, fields in sections:
            # Section header
            tk.Label(inner, text=section_label,
                     font=("Segoe UI", 8, "bold"),
                     bg=C_BG, fg=C_MUTED).pack(anchor="w", padx=28, pady=(0, 6))

            # Group card
            wrap = tk.Frame(inner, bg=C_SHADOW)
            wrap.pack(fill="x", padx=28, pady=(0, 20))
            group = tk.Frame(wrap, bg=C_SURFACE)
            group.pack(fill="x", padx=(0, 3), pady=(0, 4))

            for i, (key, label, secret, default, tip_text) in enumerate(fields):
                if i:
                    tk.Frame(group, bg=C_SEP, height=1).pack(fill="x", padx=20)

                row = tk.Frame(group, bg=C_SURFACE)
                row.pack(fill="x")

                lbl_f = tk.Frame(row, bg=C_SURFACE)
                lbl_f.pack(side="left", padx=(20, 0), pady=14)
                tk.Label(lbl_f, text=label, font=F_UI,
                         bg=C_SURFACE, fg=C_TEXT).pack(side="left")
                _tip(lbl_f, tip_text, bg=C_SURFACE).pack(side="left", padx=(6, 0))

                var = tk.StringVar(value=default)
                self._settings_vars[key] = var
                entry = tk.Entry(row, textvariable=var,
                                 show="*" if secret else "",
                                 font=F_UI, width=24,
                                 bg=C_SURFACE, fg=C_TEXT2,
                                 relief="flat", bd=0,
                                 justify="right",
                                 insertbackground=C_TEXT,
                                 highlightthickness=0)
                entry.pack(side="right", padx=(0, 20), pady=14)

                # Highlight active field on focus
                def _focus_in(e, ent=entry):
                    ent.config(fg=C_TEXT)
                def _focus_out(e, ent=entry):
                    ent.config(fg=C_TEXT2)
                entry.bind("<FocusIn>",  _focus_in)
                entry.bind("<FocusOut>", _focus_out)

        # Quality Unfollow toggle (separate card at end)
        tk.Label(inner, text="ADVANCED",
                 font=("Segoe UI", 8, "bold"),
                 bg=C_BG, fg=C_MUTED).pack(anchor="w", padx=28, pady=(0, 6))

        wrap2 = tk.Frame(inner, bg=C_SHADOW)
        wrap2.pack(fill="x", padx=28, pady=(0, 20))
        adv = tk.Frame(wrap2, bg=C_SURFACE)
        adv.pack(fill="x", padx=(0, 3), pady=(0, 4))

        qu_row = tk.Frame(adv, bg=C_SURFACE)
        qu_row.pack(fill="x")
        qu_lbl = tk.Frame(qu_row, bg=C_SURFACE)
        qu_lbl.pack(side="left", padx=(20, 0), pady=14)
        tk.Label(qu_lbl, text="Quality Unfollow", font=F_UI,
                 bg=C_SURFACE, fg=C_TEXT).pack(side="left")
        _tip(qu_lbl,
             "When enabled, Run Unfollow also cleans up existing follows "
             "that fail quality criteria. First run is slow; subsequent runs use cache.",
             bg=C_SURFACE).pack(side="left", padx=(6, 0))
        self._qu_var = tk.BooleanVar()
        tk.Checkbutton(qu_row, variable=self._qu_var,
                       bg=C_SURFACE, activebackground=C_SURFACE,
                       relief="flat", cursor="hand2").pack(side="right", padx=(0, 18), pady=14)

        # Save row
        tk.Frame(inner, bg=C_BG, height=4).pack()
        save_row = tk.Frame(inner, bg=C_BG)
        save_row.pack(fill="x", padx=28, pady=(0, 4))
        RoundedButton(save_row, "Save Settings", self._save_settings,
                      width=130, height=34).pack(side="left", padx=(0, 14))
        load_lbl = tk.Label(save_row, text="Load from .env",
                            font=F_SM, fg=C_ACCENT, bg=C_BG, cursor="hand2")
        load_lbl.pack(side="left")
        load_lbl.bind("<Button-1>", lambda _e: self._load_settings())

        self._settings_msg = tk.Label(inner, text="", font=F_SM, bg=C_BG)
        self._settings_msg.pack(anchor="w", padx=28, pady=(6, 20))

    def _save_settings(self):
        env = {k: v.get() for k, v in self._settings_vars.items()}
        env["QUALITY_UNFOLLOW"] = "true" if self._qu_var.get() else "false"
        save_env(env)
        self._settings_msg.config(text=f"Saved to {ENV_FILE}", fg=C_SUCCESS)
        self._set_status("Settings saved", C_SUCCESS)
        self._run_checks()

    def _load_settings(self):
        env = load_env()
        for k, var in self._settings_vars.items():
            var.set(env.get(k, var.get()))
        self._qu_var.set(env.get("QUALITY_UNFOLLOW", "false").lower() == "true")
        self._settings_msg.config(text=f"Loaded from {ENV_FILE}", fg=C_MUTED)

    # ── Shared ─────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str, dot_color: str = C_SUCCESS):
        self._status_var.set(msg)
        self._status_dot.config(fg=dot_color)

    def _on_open(self):
        self._run_checks()
        self._refresh_dashboard()
        self._load_settings()


if __name__ == "__main__":
    App().mainloop()
