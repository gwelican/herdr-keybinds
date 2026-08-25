#!/usr/bin/env python3
"""Keybind Browser for Herdr.

Popup that lists every configured Herdr keybinding and live-filters the
list as you type, matching against key strings, descriptions, action
names, commands, and plugin names.

Sources merged:
  1. User config [keys] table + [[keys.command]] entries + legacy
     [keys.indexed] (path: $HERDR_CONFIG_PATH or ~/.config/herdr/config.toml)
  2. Built-in defaults from `herdr --default-config` (the commented
     key bindings under its [keys] section)

Keys:
  type        filter (all tokens must match somewhere in the row)
  backspace   delete filter char
  ctrl-w      delete word backward (also ctrl+backspace)
  ctrl-k      clear filter
  ctrl-u      clear filter
  up/down     move selection
  pgup/pgdn   page
  home/end    jump to first/last
  esc         clear filter, or close when the filter is empty
  enter       close
"""

import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import termios
import tomllib
import tty

BUILTIN_DESCRIPTIONS = {
    "prefix": "Prefix key (press to enter prefix mode)",
    "help": "Open help",
    "settings": "Open settings",
    "detach": "Detach session",
    "reload_config": "Reload config",
    "open_notification_target": "Open notification target",
    "workspace_picker": "Workspace picker",
    "goto": "Goto / jump to anything",
    "new_workspace": "New workspace",
    "new_worktree": "New worktree",
    "open_worktree": "Open worktree",
    "remove_worktree": "Remove worktree",
    "rename_workspace": "Rename workspace",
    "close_workspace": "Close workspace",
    "previous_workspace": "Previous workspace",
    "next_workspace": "Next workspace",
    "previous_agent": "Previous agent",
    "next_agent": "Next agent",
    "focus_agent": "Focus agent (indexed)",
    "remote_image_paste": "Paste image from raw key (remote)",
    "new_tab": "New tab",
    "rename_tab": "Rename tab",
    "previous_tab": "Previous tab",
    "next_tab": "Next tab",
    "move_tab_previous": "Move tab backward",
    "move_tab_next": "Move tab forward",
    "switch_tab": "Switch tab (indexed)",
    "switch_workspace": "Switch workspace (indexed)",
    "close_tab": "Close tab",
    "rename_pane": "Rename pane",
    "edit_scrollback": "Edit scrollback",
    "focus_pane_left": "Focus pane left",
    "focus_pane_down": "Focus pane down",
    "focus_pane_up": "Focus pane up",
    "focus_pane_right": "Focus pane right",
    "cycle_pane_next": "Cycle to next pane",
    "cycle_pane_previous": "Cycle to previous pane",
    "last_pane": "Toggle last focused pane",
    "split_vertical": "Split pane vertically",
    "split_horizontal": "Split pane horizontally",
    "close_pane": "Close pane",
    "zoom": "Toggle pane zoom",
    "resize_mode": "Enter resize mode",
    "resize_pane_left": "Resize pane left",
    "resize_pane_down": "Resize pane down",
    "resize_pane_up": "Resize pane up",
    "resize_pane_right": "Resize pane right",
    "toggle_sidebar": "Toggle sidebar",
    "navigate_workspace_up": "Navigate mode: workspace up",
    "navigate_workspace_down": "Navigate mode: workspace down",
    "navigate_pane_left": "Navigate mode: pane left",
    "navigate_pane_down": "Navigate mode: pane down",
    "navigate_pane_up": "Navigate mode: pane up",
    "navigate_pane_right": "Navigate mode: pane right",
}


def herdr_bin():
    return os.environ.get("HERDR_BIN_PATH") or shutil.which("herdr") or "herdr"


def run_json(argv):
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def config_path():
    return os.environ.get("HERDR_CONFIG_PATH") or os.path.expanduser(
        "~/.config/herdr/config.toml"
    )


def load_config():
    try:
        with open(config_path(), "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def load_defaults():
    """Built-in [keys] defaults, parsed from `herdr --default-config`."""
    try:
        out = subprocess.run(
            [herdr_bin(), "--default-config"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return {}
    if out.returncode != 0:
        return {}
    defaults = {}
    in_keys = False
    for line in out.stdout.splitlines():
        sec = re.match(r"^\[([^\]]+)\]\s*$", line)
        if sec:
            in_keys = sec.group(1) == "keys"
            continue
        if not in_keys:
            continue
        if re.match(r"^#\s*\[", line):
            # commented sub-sections ([[keys.command]] example, [keys.indexed])
            in_keys = False
            continue
        m = re.match(r'^#\s*([a-z][a-z0-9_]*)\s*=\s*"([^"]*)"\s*(?:#.*)?$', line)
        if m:
            defaults[m.group(1)] = m.group(2)
    return defaults


def load_plugin_actions():
    """qualified action id -> (plugin display name, action title)"""
    data = run_json([herdr_bin(), "plugin", "list", "--json"])
    pmap = {}
    if not data:
        return pmap
    for p in data.get("result", {}).get("plugins", []):
        if not p.get("enabled", True):
            continue
        pname = p.get("name") or p.get("plugin_id")
        for a in p.get("actions") or []:
            pmap["%s.%s" % (p["plugin_id"], a["id"])] = (
                pname,
                a.get("title") or a["id"],
            )
    return pmap


def norm_keys(v):
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [k for k in v if isinstance(k, str)]
    return []


def build_entries(config, defaults, pmap):
    keys_section = config.get("keys", {})
    user_bindings = {
        k: v
        for k, v in keys_section.items()
        if k not in ("command", "indexed") and isinstance(v, (str, list))
    }
    commands = keys_section.get("command", [])
    indexed = keys_section.get("indexed", {})

    # Keys already claimed by user-configured bindings; a default binding
    # whose key was claimed by a different binding is no longer effective.
    taken = {}
    for name, v in user_bindings.items():
        for key in norm_keys(v):
            if key:
                taken[key] = "builtin %s" % name
    for c in commands:
        if isinstance(c, dict):
            for key in norm_keys(c.get("key")):
                if key:
                    taken[key] = "command (%s)" % c.get("type", "shell")

    entries = []

    names = sorted(set(defaults) | set(user_bindings))
    for name in names:
        desc = BUILTIN_DESCRIPTIONS.get(name, name.replace("_", " "))
        note = None
        if name in user_bindings:
            keys = norm_keys(user_bindings[name])
            source = "user"
        elif name in defaults:
            dkey = defaults[name]
            if dkey and dkey in taken:
                keys, source = [], "default"
                note = "default key %s is taken by %s" % (dkey, taken[dkey])
            else:
                keys, source = ([dkey] if dkey else []), "default"
        else:
            keys, source = [], "default"
        entries.append({
            "name": name,
            "desc": desc,
            "keys": keys,
            "source": source,
            "tag": "",
            "plugin": "",
            "note": note,
            "group": 0 if source == "user" else (1 if keys else 2),
            "kind": 1,
        })

    if isinstance(indexed, dict):
        for target, label in (
            ("tabs", "Indexed tab switching"),
            ("workspaces", "Indexed workspace switching"),
            ("agents", "Indexed agent focus"),
        ):
            mod = indexed.get(target)
            if isinstance(mod, str) and mod:
                entries.append({
                    "name": "keys.indexed.%s" % target,
                    "desc": "%s: %s+1..9" % (label, mod),
                    "keys": ["%s+1..9" % mod],
                    "source": "user",
                    "tag": "",
                    "plugin": "",
                    "note": "legacy indexed binding",
                    "group": 0,
                    "kind": 1,
                })

    for c in commands:
        if not isinstance(c, dict):
            continue
        ctype = str(c.get("type", "shell"))
        command = str(c.get("command", ""))
        keys = norm_keys(c.get("key"))
        desc = c.get("description")
        plugin = ""
        if ctype == "plugin_action":
            qualified = command.split()[0] if command else ""
            if "." in qualified:
                plugin, _action_id = qualified.rsplit(".", 1)
                info = pmap.get(qualified)
                if not desc:
                    desc = (
                        "%s (%s)" % (info[1], info[0])
                        if info
                        else "Plugin action: %s" % qualified
                    )
            elif not desc:
                desc = "Plugin action: %s" % (qualified or command)
        else:
            if not desc:
                label = {
                    "shell": "Shell command",
                    "pane": "Open in pane",
                    "popup": "Open popup",
                }.get(ctype, "Command")
                desc = "%s: %s" % (label, command)
        note = None
        if ctype == "popup":
            note = "popup %sx%s" % (c.get("width", "auto"), c.get("height", "auto"))
        entries.append({
            "name": "command: %s" % command,
            "desc": desc,
            "keys": keys,
            "source": "user",
            "tag": ctype if ctype != "plugin_action" else (plugin or "plugin"),
            "plugin": plugin,
            "note": note,
            "group": 0,
            "kind": 0,
        })

    entries.sort(key=lambda e: (e["group"], e["kind"], e["name"]))

    for e in entries:
        e["hay"] = " ".join(
            [
                " | ".join(k for k in e["keys"] if k),
                e["name"],
                e["desc"],
                e["tag"],
                e["plugin"],
                e.get("note") or "",
            ]
        ).lower()
    return entries


# ---------------------------------------------------------------- TUI -----

RESET = "\x1b[0m"
C_TITLE = "\x1b[1;38;5;51m"       # title, active filter
C_SEP = "\x1b[38;5;240m"          # separator rules
C_MARK = "\x1b[1;38;5;51m"        # selection marker
C_KEY_USER = "\x1b[1;38;5;114m"   # user-configured key
C_KEY_BUILTIN = "\x1b[1;38;5;75m" # builtin key
C_UNBOUND = "\x1b[2;38;5;244m"    # unbound
C_DIM = "\x1b[38;5;245m"          # tag chips, footer
C_NOTE = "\x1b[2;38;5;244m"       # collision notes
C_MATCH = "\x1b[1;38;5;220m"      # filter match highlight
C_BOLD = "\x1b[1m"                # active row description

ESC_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
MOTION = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end"}
CSI_MOTION = re.compile(r"1;\d+([A-DHF])")  # kitty keyboard-protocol motion


def read_event(fd):
    """Return (kind, payload) for one terminal event, or None on EOF."""
    b = os.read(fd, 1)
    if not b:
        return None
    c = b[0]
    if c == 0x1B:
        r, _, _ = select.select([fd], [], [], 0.1)
        if not r:
            return ("esc",)
        b2 = os.read(fd, 1)
        if not b2:
            return ("esc",)
        if b2[0] in (0x5B, 0x4F):  # CSI "[" or SS3 "O"
            seq = b""
            while True:
                r, _, _ = select.select([fd], [], [], 0.1)
                if not r:
                    break
                cb = os.read(fd, 1)
                if not cb:
                    break
                seq += cb
                if 0x40 <= cb[0] <= 0x7E:
                    break
            s = seq.decode("latin1")
            if s in ("5~", "5;5~"):
                return ("pageup",)
            if s in ("6~", "6;5~"):
                return ("pagedown",)
            if s in ("3~", "3;5~"):
                return ("wordback",)  # ctrl+backspace / xterm delete
            if s in MOTION:
                return (MOTION[s],)
            m = CSI_MOTION.fullmatch(s)
            if m:
                return (MOTION[m.group(1)],)
            return ("unknown",)
        return ("esc",)
    if c in (0x0D, 0x0A):
        return ("enter",)
    if c in (0x7F, 0x08):
        return ("backspace",)
    if c == 0x03:
        return ("ctrlc",)
    if c == 0x15:  # ctrl-u
        return ("clear",)
    if c == 0x17:  # ctrl-w
        return ("wordback",)
    if c == 0x2B:  # ctrl-k
        return ("killline",)
    if c >= 0x20:
        if c < 0x80:
            return ("char", chr(c))
        buf = b
        if c >= 0xF0:
            need = 3
        elif c >= 0xE0:
            need = 2
        else:
            need = 1
        for _ in range(need):
            r, _, _ = select.select([fd], [], [], 0.01)
            if r:
                buf += os.read(fd, 1)
        try:
            return ("char", buf.decode("utf-8"))
        except UnicodeDecodeError:
            return ("char", buf.decode("utf-8", "ignore"))
    return ("unknown",)


def word_backspace(q):
    """Delete the word before the end of the filter (plus its trailing spaces)."""
    i = len(q)
    while i > 0 and q[i - 1] == " ":
        i -= 1
    while i > 0 and q[i - 1] != " ":
        i -= 1
    return q[:i]


def hl_chunks(text, tokens):
    """Split text into [(chunk, matched)] for case-insensitive token matches."""
    if not text or not tokens:
        return [(text, False)]
    low = text.lower()
    marks = [False] * len(text)
    for t in tokens:
        if not t:
            continue
        start = 0
        while True:
            i = low.find(t, start)
            if i < 0:
                break
            for j in range(i, i + len(t)):
                marks[j] = True
            start = i + len(t)
    chunks = []
    cur, cur_m = "", marks[0]
    for ch, m in zip(text, marks):
        if cur and m != cur_m:
            chunks.append((cur, cur_m))
            cur = ""
        cur += ch
        cur_m = m
    if cur:
        chunks.append((cur, cur_m))
    return chunks


def row_segments(e, key_w, tokens, active):
    keyd = " | ".join(k for k in e["keys"] if k)
    pad = " " * max(key_w - len(keyd), 0)
    if active:
        segs = [(C_MARK + "▸" + RESET, None), (" ", None)]
    else:
        segs = [("  ", None)]
    if keyd:
        color = C_KEY_USER if e["source"] == "user" else C_KEY_BUILTIN
        for chunk, matched in hl_chunks(keyd, tokens):
            segs.append((chunk, C_MATCH if matched else color))
        segs.append((pad, None))
    else:
        segs.append(("unbound", C_UNBOUND))
        segs.append((pad, None))
    desc_style = C_BOLD if active else None
    for chunk, matched in hl_chunks(e["desc"], tokens):
        segs.append((chunk, C_MATCH if matched else desc_style))
    if e["tag"]:
        segs.append(("  [" + e["tag"] + "]", C_DIM))
    if e.get("note") and not e["keys"]:
        segs.append(("  ⚠ " + e["note"], C_NOTE))
    return segs


def draw_segments(segs, width):
    out = []
    remaining = width
    for text, sgr in segs:
        if remaining <= 0:
            break
        cut = text[:remaining]
        out.append(sgr + cut + RESET if sgr else cut)
        remaining -= len(cut)
    if remaining > 0:
        out.append(" " * remaining)
    return "".join(out)


def main():
    print("Loading keybindings\u2026", flush=True)
    config = load_config()
    defaults = load_defaults()
    pmap = load_plugin_actions()
    entries = build_entries(config, defaults, pmap)

    if not sys.stdout.isatty():
        for e in entries:
            keyd = " | ".join(k for k in e["keys"] if k) or "unbound"
            extra = "  [%s]" % e["tag"] if e["tag"] else ""
            note = "  ⚠ %s" % e["note"] if e.get("note") and not e["keys"] else ""
            print("%-30s  %s%s%s" % (keyd, e["desc"], extra, note))
        return 0

    W, H = shutil.get_terminal_size((120, 40))
    all_keys = [
        " | ".join(k for k in e["keys"] if k) or "unbound" for e in entries
    ]
    longest = max((len(k) for k in all_keys), default=0)
    key_w = min(max(longest, 10), 30)
    row_w = W - 2

    state = {"query": "", "sel": 0, "view": 0}

    def tokens():
        return [t for t in state["query"].lower().split() if t]

    def filtered():
        toks = tokens()
        if not toks:
            return entries
        return [e for e in entries if all(t in e["hay"] for t in toks)]

    def visible_len(s):
        return len(ESC_RE.sub("", s))

    def render():
        rows = filtered()
        sel = state["sel"]
        view = state["view"]
        avail = max(H - 4, 1)
        if not rows:
            sel = view = 0
        else:
            sel = max(0, min(sel, len(rows) - 1))
            if sel < view:
                view = sel
            if sel >= view + avail:
                view = sel - avail + 1
        state["sel"], state["view"] = sel, view
        toks = tokens()
        query = state["query"]

        head = C_TITLE + "keybinds" + RESET
        if query:
            head += "  " + C_TITLE + "? " + query + RESET
            tail = C_DIM + "%d/%d" % (len(rows), len(entries)) + RESET
        else:
            tail = C_DIM + "%d bindings" % len(entries) + RESET
        gap = max(1, row_w - visible_len(head) - visible_len(tail))
        out = [head + " " * gap + tail]
        out.append(C_SEP + "─" * row_w + RESET)

        for i, e in enumerate(rows[view : view + avail]):
            out.append(
                draw_segments(
                    row_segments(e, key_w, toks, i == sel - view), row_w
                )
            )
        while len(out) < H - 2:
            out.append(" " * row_w)
        out.append(C_SEP + "─" * row_w + RESET)

        fsegs = []
        if query:
            fsegs.append(("filter ", C_DIM))
            fsegs.append(("? " + query, C_TITLE))
        fsegs.append((
            "   ·   ↑↓ move · pgup/pgdn page · home/end · "
            "⌫/ctrl+w word · ctrl+u line · esc clear · enter close",
            C_DIM,
        ))
        out.append(draw_segments(fsegs, row_w))
        sys.stdout.write("\x1b[H" + "\n".join(out) + "\x1b[J")
        sys.stdout.flush()

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    def raise_term(*_args):
        raise SystemExit(130)
    signal.signal(signal.SIGINT, raise_term)
    signal.signal(signal.SIGTERM, raise_term)

    try:
        tty.setcbreak(fd)
        sys.stdout.write("\x1b[?25l")
        sys.stdout.flush()
        render()
        while True:
            ev = read_event(fd)
            if ev is None:
                break
            kind = ev[0]
            rows = filtered()
            last = max(len(rows) - 1, 0)
            page = max(H - 4, 1)
            if kind in ("enter", "ctrlc"):
                break
            elif kind == "esc":
                if state["query"]:
                    state["query"] = ""
                else:
                    break
            elif kind == "backspace":
                state["query"] = state["query"][:-1]
            elif kind == "wordback":
                state["query"] = word_backspace(state["query"])
            elif kind in ("clear", "killline"):
                state["query"] = ""
            elif kind == "char":
                state["query"] += ev[1]
            elif kind == "up":
                state["sel"] = max(0, state["sel"] - 1)
            elif kind == "down":
                state["sel"] = min(last, state["sel"] + 1)
            elif kind == "pageup":
                state["sel"] = max(0, state["sel"] - page)
            elif kind == "pagedown":
                state["sel"] = min(last, state["sel"] + page)
            elif kind == "home":
                state["sel"] = 0
            elif kind == "end":
                state["sel"] = last
            render()
    finally:
        sys.stdout.write("\x1b[?25h\x1b[0m\x1b[2J\x1b[H")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    main()
