#!/usr/bin/env python3
"""Mo Betta Crafts: tray app + always-on-top crafting overlay for Monsters & Memories.

Search ~1,400 tradeskill recipes (from the community wiki, see wiki_recipes.py), pin the ones you are
working on, and track how many of each ingredient you have. The game keeps inventory on its server
(nothing on disk says what is in your bags), so counts are typed in by you: click a count to set it.
"made 1" on a pinned recipe takes its ingredients off your counts and adds the result. Counts are kept
per character; the overlay follows whichever character the game's files show you are playing.

Controls:
  * hotkey Ctrl+Shift+K toggles the overlay
  * tray icon menu (right-click)
  * running the exe again while it is open:  MoBettaCrafts.exe open|hide|toggle|quit

  python crafts.py              run
  python crafts.py --shot X.png [--search copper]
                                open, save a screenshot of the window to X.png, quit (for testing)
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import math
import os
import queue
import sys
import tempfile
import threading
import tkinter as tk
import traceback
import winreg
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:  # running from source without the tray libs: overlay still works
    pystray = None

APP_NAME = "MoBettaCrafts"
HERE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BUNDLED = Path(getattr(sys, "_MEIPASS", HERE))
RECIPES_FILE = HERE / "recipes.json"  # a wiki refresh writes here; falls back to the copy inside the exe
STATE_FILE = Path(os.environ.get("MBC_STATE") or HERE / "crafts_state.json")  # env override for test shots
LOG_FILE = HERE / "MoBettaCrafts.log"
GAME_DIR = Path(os.environ.get("USERPROFILE", "")) / "AppData/LocalLow/Niche Worlds Cult/Monsters and Memories"
CMD_FILE = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "MoBettaCrafts.command"
MUTEX_NAME = "Local\\MoBettaCrafts-single-instance"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

BG, PANEL, HEAD, FG, DIM, ACCENT = "#14161c", "#1c1f27", "#0e1015", "#e6e1d6", "#8d8a80", "#d9a441"
GOOD, SHORT = "#7fbf6a", "#d9785a"
WIDTH, MAX_HEIGHT, WRAP = 440, 640, 400
MAX_RESULTS = 40
TICK_MS = 1000
CHAR_TICKS = 5
HOTKEY_ID, WM_HOTKEY = 1, 0x0312
MOD_CONTROL, MOD_SHIFT, VK_K = 0x0002, 0x0004, 0x4B
WINDOW_CMDS = ("open", "show", "hide", "close", "toggle", "quit", "exit")


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- data

def load_recipes() -> tuple[list[dict], str]:
    for p in (RECIPES_FILE, BUNDLED / "recipes.json"):
        try:
            d = json.loads(p.read_text("utf-8"))
            return d["recipes"], d.get("fetched", "")
        except (OSError, ValueError, KeyError):
            continue
    return [], ""


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=1), "utf-8")
    except OSError as e:
        log(f"could not save state: {e}")


def server_dir() -> Path | None:
    """The game keeps one folder per server (beta1, ...). Pick the most recently used one."""
    best, best_t = None, -1.0
    if GAME_DIR.is_dir():
        for d in GAME_DIR.iterdir():
            if d.is_dir() and any((c / "Ledger").is_dir() for c in d.iterdir() if c.is_dir()):
                t = max((p.stat().st_mtime for p in d.glob("*/Ledger/*.json")), default=0.0)
                if t > best_t:
                    best, best_t = d, t
    return best


def active_character(root: Path | None) -> str | None:
    """The character whose folder the game touched most recently."""
    best, best_t = None, 0.0
    if root:
        for d in root.iterdir():
            if d.is_dir():
                t = max((p.stat().st_mtime for p in d.rglob("*") if p.is_file()), default=0.0)
                if t > best_t:
                    best, best_t = d.name, t
    return best


# ---------------------------------------------------------------- windows plumbing

def already_running() -> bool:
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW(None, False, MUTEX_NAME)
    return k32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def send_to_running(cmd: str) -> None:
    try:
        CMD_FILE.write_text(cmd + "\n", "utf-8")
    except OSError:
        pass


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{Path(__file__).resolve()}"'


def startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_startup(on: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass


def hotkey_loop(q: "queue.Queue[tuple[str, str | None]]") -> None:
    user32 = ctypes.windll.user32
    if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT, VK_K):
        log("hotkey Ctrl+Shift+K unavailable (another app owns it)")
        return
    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == WM_HOTKEY:
            q.put(("toggle", None))


def tray_image() -> "Image.Image":
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    gold = (217, 164, 65, 255)
    d.rounded_rectangle((2, 2, 62, 62), radius=12, fill=(20, 22, 28, 255), outline=gold, width=3)
    d.rectangle((14, 38, 50, 46), fill=gold)            # anvil face
    d.polygon([(22, 46), (42, 46), (38, 54), (26, 54)], fill=gold)
    d.line((40, 14, 26, 32), fill=gold, width=6)       # hammer
    d.rectangle((34, 10, 48, 18), fill=gold)
    return img


# ---------------------------------------------------------------- app

class App:
    def __init__(self, shot: str | None, search: str = "") -> None:
        self.recipes, self.fetched = load_recipes()
        self.by_name: dict[str, list[dict]] = {}
        for r in self.recipes:
            if not r["salvage"]:
                self.by_name.setdefault(r["name"].lower(), []).append(r)
        self.by_id = {r["id"]: r for r in self.recipes}
        self.skills = sorted({r["skill"] for r in self.recipes})

        self.state = load_state()
        self.state.setdefault("pins", [])      # [{id, times}]
        self.state.setdefault("have", {})      # char -> {item lower: count you typed in}
        self.open_sub: set[str] = set()        # "pinId|ingredient" rows whose sub-recipe is expanded
        self.char: str | None = None
        self.q: "queue.Queue[tuple[str, str | None]]" = queue.Queue()
        self.ticks = 0
        self.visible = True
        self.collapsed = False
        self.tray = None

        self.root = tk.Tk()
        self.root.title("Mo Betta Crafts")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.93)
        self.root.configure(bg=BG)
        self.root.geometry(self._load_pos())

        self.bold = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.normal = tkfont.Font(family="Segoe UI", size=9)
        self.small = tkfont.Font(family="Segoe UI", size=8)

        header = tk.Frame(self.root, bg=HEAD, cursor="fleur")
        header.pack(fill="x")
        self.title = tk.Label(header, text="Mo Betta Crafts", bg=HEAD, fg=ACCENT, font=self.bold, anchor="w", padx=8)
        self.title.pack(side="left", fill="x", expand=True)
        for text, cmd in (("×", self.hide_window), ("–", self.toggle_collapse)):
            tk.Button(header, text=text, command=cmd, bg=HEAD, fg=DIM, activebackground="#22252e",
                      activeforeground=FG, relief="flat", font=self.small, padx=6).pack(side="right")
        for w in (header, self.title):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        self.main = tk.Frame(self.root, bg=BG)
        self.main.pack(fill="both", expand=True)

        # search bar
        bar = tk.Frame(self.main, bg=BG, padx=8, pady=6)
        bar.pack(fill="x")
        self.search = tk.StringVar()
        entry = tk.Entry(bar, textvariable=self.search, bg=PANEL, fg=FG, insertbackground=FG, relief="flat",
                         font=self.normal)
        entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.skill = tk.StringVar(value="All skills")
        om = tk.OptionMenu(bar, self.skill, "All skills", *self.skills)
        om.config(bg=PANEL, fg=FG, activebackground="#2a2e3a", activeforeground=FG, relief="flat",
                  highlightthickness=0, font=self.small, width=12)
        om["menu"].config(bg=PANEL, fg=FG, activebackground=ACCENT, activeforeground=HEAD, font=self.small)
        om.pack(side="left", padx=(6, 0))

        # scrollable body
        wrap = tk.Frame(self.main, bg=BG)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, width=WIDTH)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=BG, padx=8)
        self.canvas.create_window((0, 0), window=self.body, anchor="nw", width=WIDTH)
        self.body.bind("<Configure>", lambda e: self._fit())
        self.root.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

        self.foot = tk.Label(self.main, text="", bg=BG, fg=DIM, font=self.small, anchor="w", padx=8, pady=3)
        self.foot.pack(fill="x")
        self._placeholder(entry, self._placeholder_text)
        if search:
            entry.config(fg=FG)
            self.search.set(search)
        self.search.trace_add("write", lambda *_: self.render())
        self.skill.trace_add("write", lambda *_: self.render())

        threading.Thread(target=hotkey_loop, args=(self.q,), daemon=True).start()
        self._start_tray()
        self.detect_char()
        self.render()
        self.root.after(TICK_MS, self._tick)
        if shot:
            self.root.after(1500, lambda: self._screenshot(shot))
        log(f"started with {len(self.recipes)} recipes")
        self.root.mainloop()

    # ---------------------------------------------------------------- tray / commands

    def _start_tray(self) -> None:
        if pystray is None:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show / hide overlay", lambda: self.q.put(("toggle", None)), default=True),
            pystray.MenuItem("Update recipes from wiki", lambda: self.q.put(("wiki", None))),
            pystray.MenuItem("Start with Windows", lambda: self.q.put(("startup", None)),
                             checked=lambda item: startup_enabled()),
            pystray.MenuItem("Open log", lambda: self.q.put(("log", None))),
            pystray.MenuItem("Quit", lambda: self.q.put(("quit", None))),
        )
        self.tray = pystray.Icon(APP_NAME, tray_image(), "Mo Betta Crafts  (Ctrl+Shift+K)", menu)
        self.tray.run_detached()

    def handle(self, verb: str, arg: str | None) -> None:
        verb = verb.lower()
        log(f"command: {verb}")
        if verb in ("open", "show"):
            self.show_window()
        elif verb in ("hide", "close"):
            self.hide_window()
        elif verb == "toggle":
            self.hide_window() if self.visible else self.show_window()
        elif verb == "wiki":
            self.foot.config(text="updating recipes from the wiki…")
            threading.Thread(target=self._update_wiki, daemon=True).start()
        elif verb == "wiki-done":
            self.__init_recipes()
            self.render()
        elif verb == "startup":
            try:
                set_startup(not startup_enabled())
            except OSError as e:
                log(f"could not change startup setting: {e}")
            if self.tray:
                self.tray.update_menu()
        elif verb == "log":
            try:
                os.startfile(LOG_FILE)
            except OSError:
                pass
        elif verb in ("quit", "exit"):
            self.quit()

    def _update_wiki(self) -> None:
        try:
            import wiki_recipes
            wiki_recipes.OUT = RECIPES_FILE
            wiki_recipes.main()
        except Exception:
            log("wiki update failed:\n" + traceback.format_exc())
        self.q.put(("wiki-done", None))

    def __init_recipes(self) -> None:
        self.recipes, self.fetched = load_recipes()
        self.by_name = {}
        for r in self.recipes:
            if not r["salvage"]:
                self.by_name.setdefault(r["name"].lower(), []).append(r)
        self.by_id = {r["id"]: r for r in self.recipes}

    def _tick(self) -> None:
        try:
            if CMD_FILE.exists():
                cmd = CMD_FILE.read_text("utf-8-sig").strip()  # -sig: tolerate a BOM from PowerShell
                CMD_FILE.unlink(missing_ok=True)
                if cmd:
                    self.q.put((cmd.split()[0], None))
        except OSError:
            pass
        while not self.q.empty():
            self.handle(*self.q.get())
        self.ticks += 1
        if self.ticks % CHAR_TICKS == 0 and self.detect_char():
            self.render()
        self.root.after(TICK_MS, self._tick)

    # ---------------------------------------------------------------- inventory

    def detect_char(self) -> bool:
        """Follow whichever character the game touched last. True when it changed."""
        char = active_character(server_dir())
        if not char or char == self.char:
            return False
        self.char = char
        return True

    def have(self, item: str) -> int:
        return self.state["have"].get(self.char or "", {}).get(item.lower(), 0)

    def set_have(self, item: str, value: int, render: bool = True) -> None:
        bag = self.state["have"].setdefault(self.char or "", {})
        if value > 0:
            bag[item.lower()] = value
        else:
            bag.pop(item.lower(), None)
        if render:
            save_state(self.state)
            self.render()

    def made_one(self, rid: str) -> None:
        """One combine done: take the ingredients off your counts, add the result, count down the pin."""
        r = self.by_id.get(rid)
        if not r:
            return
        for ing in r["ingredients"]:
            if not ing.get("tool"):
                self.set_have(ing["name"], max(0, self.have(ing["name"]) - ing["qty"]), render=False)
        for res in r.get("results") or [{"qty": 1, "name": r["name"]}]:
            self.set_have(res["name"], self.have(res["name"]) + res["qty"], render=False)
        p = self.pinned(rid)
        if p and p["times"] > 1:
            p["times"] -= 1
        save_state(self.state)
        self.render()

    # ---------------------------------------------------------------- pins

    def pinned(self, rid: str) -> dict | None:
        return next((p for p in self.state["pins"] if p["id"] == rid), None)

    def toggle_pin(self, rid: str) -> None:
        p = self.pinned(rid)
        if p:
            self.state["pins"].remove(p)
        else:
            self.state["pins"].append({"id": rid, "times": 1})
        save_state(self.state)
        self.render()

    def bump(self, rid: str, d: int) -> None:
        p = self.pinned(rid)
        if p:
            p["times"] = max(1, p["times"] + d)
            save_state(self.state)
            self.render()

    # ---------------------------------------------------------------- render

    def render(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        who = f"  ·  {self.char}" if self.char else ""
        self.title.config(text=f"Mo Betta Crafts{who}")
        if self.collapsed:
            return
        pins = [(p, self.by_id[p["id"]]) for p in self.state["pins"] if p["id"] in self.by_id]
        if pins:
            self._section("Crafting list")
            for p, r in pins:
                self._pinned_block(p, r)
        self._results()
        src = f"recipes: community wiki, {self.fetched}" if self.fetched else "no recipes loaded"
        self.foot.config(text=f"{len(self.recipes)} {src}  ·  click a count to type what you have")
        self.root.after_idle(self._fit)

    def _section(self, text: str) -> None:
        tk.Label(self.body, text=text, bg=PANEL, fg=FG, font=self.bold, anchor="w", padx=6, pady=3).pack(
            fill="x", pady=(8, 2))

    def _pinned_block(self, p: dict, r: dict) -> None:
        box = tk.Frame(self.body, bg=BG)
        box.pack(fill="x", pady=(4, 2))
        top = tk.Frame(box, bg=BG)
        top.pack(fill="x")
        makes = f"{r['makes']}× " if r.get("makes") and r["makes"] > 1 else ""
        tk.Label(top, text=makes + r["name"], bg=BG, fg=ACCENT, font=self.bold, anchor="w").pack(side="left")
        tk.Button(top, text="✕", command=lambda: self.toggle_pin(r["id"]), bg=BG, fg=DIM, relief="flat",
                  activebackground=BG, activeforeground=SHORT, font=self.small, padx=4).pack(side="right")
        for t, d in (("+", 1), ("−", -1)):
            tk.Button(top, text=t, command=lambda d=d: self.bump(r["id"], d), bg=BG, fg=DIM, relief="flat",
                      activebackground=BG, activeforeground=FG, font=self.small, padx=3).pack(side="right")
        tk.Label(top, text=f"×{p['times']}", bg=BG, fg=FG, font=self.small).pack(side="right")
        tk.Button(top, text="✓ made 1", command=lambda: self.made_one(r["id"]), bg=BG, fg=GOOD, relief="flat",
                  activebackground=BG, activeforeground=FG, font=self.small, padx=4).pack(side="right", padx=(0, 6))
        tk.Label(box, text=self._meta(r), bg=BG, fg=DIM, font=self.small, anchor="w").pack(fill="x")
        for ing in r["ingredients"]:
            need = ing["qty"] * p["times"]
            self._ingredient_row(box, ing, need, key=f"{r['id']}|{ing['name']}", depth=0)

    def _ingredient_row(self, parent: tk.Frame, ing: dict, need: int, key: str, depth: int) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=(12 + depth * 16, 0))
        if ing.get("tool"):
            tk.Label(row, text=f"🔧 {ing['name']} (tool, not used up)", bg=BG, fg=DIM, font=self.small,
                     anchor="w").pack(side="left")
            return
        have = self.have(ing["name"])
        ok = have >= need
        cnt = tk.Label(row, text=f"{have}/{need}", bg=BG, fg=GOOD if ok else SHORT, font=self.normal, width=7,
                       anchor="e", cursor="hand2")
        cnt.pack(side="left")
        cnt.bind("<Button-1>", lambda e, n=ing["name"], w=cnt: self._edit_count(n, w))
        subs = self.by_name.get(ing["name"].lower(), [])
        arrow = ("▾ " if key in self.open_sub else "▸ ") if subs else "   "
        name = tk.Label(row, text=f"{arrow}{ing['name']}", bg=BG, fg=FG if not ok else DIM, font=self.normal,
                        anchor="w", cursor="hand2" if subs else "")
        name.pack(side="left", padx=(6, 0))
        if subs:
            name.bind("<Button-1>", lambda e, k=key: self._toggle_sub(k))
        if subs and key in self.open_sub:
            short = max(0, need - have)
            for sub in subs[:2]:  # an item can have more than one recipe (e.g. bars from ore or from scraps)
                runs = math.ceil(short / (sub.get("makes") or 1)) if short else 0
                tk.Label(parent, text=f"{sub['skill']}: {runs}× combine" + (f" · {sub['station']}" if sub["station"] else ""),
                         bg=BG, fg=DIM, font=self.small, anchor="w").pack(fill="x", padx=(34 + depth * 16, 0))
                for s_ing in sub["ingredients"]:
                    self._ingredient_row(parent, s_ing, s_ing["qty"] * runs if not s_ing.get("tool") else 1,
                                         key=f"{key}|{sub['id']}|{s_ing['name']}", depth=depth + 1)

    def _toggle_sub(self, key: str) -> None:
        self.open_sub.symmetric_difference_update({key})
        self.render()

    def _edit_count(self, item: str, label: tk.Label) -> None:
        e = tk.Entry(label.master, width=5, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=self.normal,
                     justify="right")
        e.insert(0, str(self.have(item)))
        e.select_range(0, "end")
        e.place(in_=label, relx=0, rely=0, relwidth=1, relheight=1)
        e.focus_set()

        def done(_=None) -> None:
            txt = e.get().strip()
            e.destroy()
            if txt.isdigit():
                self.set_have(item, int(txt))
        e.bind("<Return>", done)
        e.bind("<FocusOut>", done)
        e.bind("<Escape>", lambda _: e.destroy())

    def _meta(self, r: dict) -> str:
        bits = [r["skill"]]
        if r.get("trivial") is not None:
            bits.append(f"trivial {r['trivial']}")
        if r.get("station"):
            bits.append(r["station"])
        if r.get("notes"):
            bits.append(r["notes"])
        return "  ·  ".join(bits)

    def _results(self) -> None:
        q = self.search.get().strip().lower()
        if q == self._placeholder_text:
            q = ""
        skill = self.skill.get()
        if not q and skill == "All skills":
            if not self.state["pins"]:
                tk.Label(self.body, text="Search for something you want to make (or an ingredient you have),\n"
                                         "or pick a skill. Click ☆ to pin a recipe to your crafting list.",
                         bg=BG, fg=DIM, font=self.normal, justify="left").pack(anchor="w", pady=10)
            return
        hits = []
        for r in self.recipes:
            if skill != "All skills" and r["skill"] != skill:
                continue
            uses = ""
            if q and q not in r["name"].lower():
                m = next((i["name"] for i in r["ingredients"] if q in i["name"].lower()), None)
                if not m:
                    continue
                uses = m
            hits.append((uses != "", r["salvage"], r.get("trivial") or 0, r["name"], r, uses))
        hits.sort(key=lambda h: h[:4])
        self._section(f"{len(hits)} recipe{'s' if len(hits) != 1 else ''}" +
                      (f" (showing {MAX_RESULTS})" if len(hits) > MAX_RESULTS else ""))
        for *_, r, uses in hits[:MAX_RESULTS]:
            row = tk.Frame(self.body, bg=BG)
            row.pack(fill="x", pady=(3, 0))
            star = tk.Label(row, text="★" if self.pinned(r["id"]) else "☆", bg=BG, fg=ACCENT, font=self.bold,
                            cursor="hand2")
            star.pack(side="left", anchor="n")
            star.bind("<Button-1>", lambda e, rid=r["id"]: self.toggle_pin(rid))
            col = tk.Frame(row, bg=BG)
            col.pack(side="left", fill="x", expand=True, padx=(4, 0))
            makes = f"{r['makes']}× " if r.get("makes") and r["makes"] > 1 else ""
            tag = "  (salvage)" if r["salvage"] else ""
            tk.Label(col, text=makes + r["name"] + tag, bg=BG, fg=FG, font=self.normal, anchor="w").pack(fill="x")
            ings = ", ".join(f"{i['qty']} {i['name']}" for i in r["ingredients"] if not i.get("tool"))
            tools = [i["name"] for i in r["ingredients"] if i.get("tool")]
            line = ings + (f"  + {', '.join(tools)}" if tools else "")
            if uses:
                line = f"uses {uses}  ·  " + line
            tk.Label(col, text=line, bg=BG, fg=DIM, font=self.small, anchor="w", justify="left",
                     wraplength=WRAP - 30).pack(fill="x")
            tk.Label(col, text=self._meta(r), bg=BG, fg="#5f5d57", font=self.small, anchor="w", justify="left",
                     wraplength=WRAP - 30).pack(fill="x")

    _placeholder_text = "search recipes or ingredients…"

    def _placeholder(self, entry: tk.Entry, text: str) -> None:
        def show(_=None) -> None:
            if not self.search.get():
                entry.config(fg=DIM)
                self.search.set(text)

        def hide(_=None) -> None:
            if self.search.get() == text:
                self.search.set("")
                entry.config(fg=FG)
        entry.bind("<FocusIn>", hide)
        entry.bind("<FocusOut>", show)
        show()

    def _fit(self) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        h = min(self.body.winfo_reqheight(), MAX_HEIGHT)
        self.canvas.configure(height=max(h, 40))

    # ---------------------------------------------------------------- window

    def toggle_collapse(self) -> None:
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.main.pack_forget()
        else:
            self.main.pack(fill="both", expand=True)
        self.render()

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.visible = True

    def hide_window(self) -> None:
        self._save_pos()
        self.root.withdraw()
        self.visible = False
        if pystray is None:
            self.quit()

    def quit(self) -> None:
        self._save_pos()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        log("quit")
        self.root.destroy()

    def _screenshot(self, path: str) -> None:
        from PIL import ImageGrab
        self.root.update()
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        ImageGrab.grab((x, y, x + self.root.winfo_width(), y + self.root.winfo_height()), all_screens=True).save(path)
        self.quit()

    def _drag_start(self, e: tk.Event) -> None:
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag_move(self, e: tk.Event) -> None:
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _load_pos(self) -> str:
        p = self.state.get("pos")
        return f"+{p['x']}+{p['y']}" if p else "+60+60"

    def _save_pos(self) -> None:
        self.state["pos"] = {"x": self.root.winfo_x(), "y": self.root.winfo_y()}
        save_state(self.state)


def main() -> None:
    args = sys.argv[1:]
    shot = args[args.index("--shot") + 1] if "--shot" in args else None
    if not shot and already_running():
        cmd = args[0].lower() if args and args[0].lower() in WINDOW_CMDS else "open"
        send_to_running(cmd)
        return
    search = args[args.index("--search") + 1] if "--search" in args else ""
    App(shot, search)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("fatal:\n" + traceback.format_exc())
        raise
