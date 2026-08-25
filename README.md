# herdr-keybinds

A Herdr plugin with one popup: **Keybind Browser** — a live-filterable list of
every keybinding currently configured for your Herdr instance. Merges your user
config with Herdr's built-in defaults, flags collisions, and highlights filter
matches as you type.

## Install

```sh
herdr plugin link /path/to/herdr-keybinds
```

That's it — no build step (pure stdlib Python 3; `python3` must be in the
herdr server's `PATH`).

The plugin does **not** self-register keybinds. Bind its `open` action in your
user config (`~/.config/herdr/config.toml`):

```toml
[[keys.command]]
key = "prefix+?"
type = "plugin_action"
command = "gwelican.keybinds.open"
```

(If you override a built-in, unbind it first, e.g. `help = ""` for the
built-in help popup.) Then reload config (`prefix+r` by default). You can also
open the popup from the palette — the `open` action is visible there.

## Usage

Type to filter by key name (`prefix+?`), description (`palette`), plugin
(`beads`), or tag (`shell`, `pane`). Multiple space-separated tokens are
AND-ed.

| Key | Action |
|---|---|
| `↑` / `↓` | move selection |
| `home` / `end` | jump to top / bottom |
| `pgup` / `pgdn` | page |
| `⌫` | delete char |
| `ctrl+w` | delete word |
| `ctrl+u` | clear filter |
| `ctrl+k` | kill to end of line |
| `esc` | clear filter; again to close |
| `enter` | close |

Rendering is 256-color foreground-only (no backgrounds, no reverse video), so
it survives both light and dark terminal themes. Run `keybind_browser.py`
without a TTY to get a plain-text listing instead (useful for scripts and CI).

## What gets listed

- `[keys.*]` entries from your config, including array-valued keys (every
  binding shown as one row) and `""` values rendered as `unbound`.
- `[[keys.command]]` user commands and legacy `[keys.indexed]` entries.
- Built-in defaults from `herdr --default-config`, so unmodified bindings are
  visible too.
- Plugin actions (`plugin_action` commands) resolved to their plugin name and
  action title.
- Collisions (same key bound twice) are flagged with a `⚠` note.

User-configured keys render in green, built-in defaults in blue, unbound in dim.
The plugin reads config at popup open — after editing config, reload and reopen
the popup to see changes.
