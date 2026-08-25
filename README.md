# herdr-keybinds

A Herdr plugin with one popup: **Keybind Browser** — a live-filterable list of
every keybinding currently configured for your Herdr instance: built-in
defaults, your `[keys]` overrides, and **every keybound plugin action** (with
its plugin name and action title resolved). Flags collisions and highlights
filter matches as you type.

## Install

```sh
herdr plugin install gwelican/herdr-keybinds
```

That's it — no build step (pure stdlib Python 3; `python3` must be in the
herdr server's `PATH`). Pin a release with `--ref` (e.g.
`herdr plugin install gwelican/herdr-keybinds --ref v0.1.0`). To develop from
a local checkout instead, use `herdr plugin link /path/to/herdr-keybinds`.

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

- Built-in defaults from `herdr --default-config`, so unmodified bindings are
  visible too.
- `[keys.*]` entries from your config, including array-valued keys (every
  binding shown as one row) and `""` values rendered as `unbound`.
- **Plugin keybinds** — every `[[keys.command]]` bound with
  `type = "plugin_action"` is listed, resolved to the plugin's display name
  and action title (via `herdr plugin list`) and tagged with the plugin id,
  so you can filter the whole list by plugin (e.g. `beads`). Plugins don't
  self-register keybinds in Herdr — this shows exactly what *your* config
  binds to their actions.
- Other `[[keys.command]]` entries (`shell`, `pane`, `popup`), tagged by type.
- Legacy `[keys.indexed]` bindings.
- Collisions (same key bound twice) are flagged with a `⚠` note.

User-configured keys render in green, built-in defaults in blue, unbound in dim.
The plugin reads config at popup open — after editing config, reload and reopen
the popup to see changes.

## Releasing

1. Bump `version` in `herdr-plugin.toml`.
2. Commit, tag, push:

   ```sh
   git commit -am "release vX.Y.Z"
   git tag vX.Y.Z
   git push origin main vX.Y.Z
   ```

Installers track `main` by default; pinned installs use
`herdr plugin install gwelican/herdr-keybinds --ref vX.Y.Z`.
