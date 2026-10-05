# ricer

Instant desktop ricing for GNOME. Turn three dials and ricer picks a wallpaper, derives a
colour scheme from it, restyles the top bar, dock and terminal, and puts widgets on the
desktop. It applies live, with no logout, and one command puts everything back.

```
ricer instant --cool 8 --ease 4 --warmth 7
```

The same dials always give the same look.

## The dials

Each dial goes from 1 to 10. Dials you leave out default to 5.

| Dial | 1 | 10 | What it changes |
|---|---|---|---|
| `--cool` | calm, minimal | loud, flashy | accent saturation, gradients, blur, clock size, how many widgets |
| `--ease` | looks first | usability first | dock auto-hide vs always visible, text size, card opacity, how much the widgets show, bar style |
| `--warmth` | cold blues | warm ambers | which wallpaper is picked, accent hues, terminal colours |

`--all N` sets all three at once; single dials still override it:

```
ricer instant --all 6
ricer instant --all 3 --cool 9
```

## Requirements

- GNOME 45 or newer. Developed on Ubuntu 24.04 (GNOME 46).
- Python 3.10+, PyGObject and GTK 3 from your distribution, and the `dconf` command.
  On Ubuntu these are already installed; elsewhere look for `python3-gi`/`python-gobject`.
- Pillow (installed automatically).

Everything else is optional. ricer checks what your desktop has and skips the rest, telling
you what it skipped:

| Feature | Needs |
|---|---|
| Desktop widgets | an X11 session (see [Limits](#limits)) |
| Top bar styling | the [User Themes](https://extensions.gnome.org/extension/19/user-themes/) extension |
| Blur | the [Blur my Shell](https://extensions.gnome.org/extension/3193/blur-my-shell/) extension |
| Dock styling | Ubuntu Dock or [Dash to Dock](https://extensions.gnome.org/extension/307/dash-to-dock/) |
| Terminal colours | GNOME Terminal |
| Accent-matched app theme | Yaru theme variants (Ubuntu); on GNOME 47+ the system accent colour is set instead |
| Nicer icons and cursor | Papirus-Dark and Bibata-Modern-Ice, used only if installed |

`ricer status` shows which of these your desktop has.

## Install

PyGObject comes from the system, so the environment must be able to see system packages:

```
pipx install --system-site-packages git+https://github.com/<you>/ricer
```

or from a checkout:

```
git clone https://github.com/<you>/ricer && cd ricer
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
.venv/bin/ricer status
```

## Wallpapers

ricer ships no images. It picks from a folder on your machine, `~/Pictures/Wallpapers` by
default (set `RICER_WALLPAPERS` to use another).

```
ricer wallpapers fetch --count 12      # SFW anime scenery from wallhaven.cc
ricer wallpapers fetch --query "cyberpunk city"
ricer wallpapers add ~/Downloads/some-image.png
ricer wallpapers list                  # each image with its measured mood
```

Each image is measured once for warmth, colourfulness, detail and brightness. The dials
choose the closest match: `--warmth` matters most, `--cool` prefers vivid images, and a high
`--ease` prefers calmer ones that are easier to read text over. More wallpapers means the
dials have more to choose from. Fetched images belong to their artists; they are for your
own desktop.

## Commands

```
ricer instant [--cool N] [--ease N] [--warmth N] [--all N]
              [--shuffle | --seed N] [--dry-run] [--json]
ricer revert [--all]
ricer status
ricer wallpapers list | add FILE... | fetch [--count N] [--query WORDS]
ricer widgets start | stop
```

- `--dry-run` prints the look and changes nothing.
- `--shuffle` gives a different variant for the same dials (another close-matching wallpaper,
  another accent, widgets in other corners) and prints a seed. `--seed N` brings that exact
  variant back.
- `ricer revert` undoes the last `instant`. `ricer revert --all` undoes everything ricer has
  ever changed and returns the desktop to how it was before the first run.

## What it changes

ricer only writes settings it owns, and records the previous value of each before writing:

- wallpaper and lock-screen background, dark colour scheme, app theme, icons, cursor
- dock position, auto-hide, size and opacity
- the top bar, through a generated shell theme at `~/.local/share/themes/Ricer`
- Blur my Shell's blur switches
- the default GNOME Terminal profile's colours
- its own files: `~/.config/ricer/`, `~/.cache/ricer/`, and an autostart entry for the widgets

If applying fails part-way, what was already written is rolled back.

## Widgets

Drawn by a small background process that follows `~/.config/ricer/widgets.json` and updates
within a second when it changes.

- **Clock**: time, a seconds bar, the date. Follows your 12/24-hour setting.
- **Media**: track, artist, cover art, progress and previous / play-pause / next for whatever
  MPRIS player is playing (Spotify, browsers, mpv, ...).
- **System**: CPU, memory, CPU temperature, and at higher `--ease` GPU temperature and
  battery. Rows for sensors your machine lacks are left out.

## Limits

- **Widgets need X11.** GNOME on Wayland does not let an application pin a window to the
  desktop layer, so on Wayland ricer applies everything except the widgets.
- **GNOME only.** On other desktops `ricer instant` refuses to run (`--dry-run` still works).
- The top-bar theme is layered over the stock Yaru shell theme. On distributions without
  Yaru it imports GNOME's built-in dark theme instead; that path is not yet tested.
- The same dials give the same look only while the wallpaper folder holds the same images.

## Development

```
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

The pieces that make decisions are pure and tested without a desktop: `generator.py` (dials
to look), `palette.py`, `wallpapers.py`, `shell_theme.py`, and `engine.build_plan` (look to
settings). The engine talks to the desktop through a small backend interface with an
in-memory fake for tests. Widget drawing is tested by rendering to an offscreen surface;
the window tests are skipped when there is no display.

## Licence

MIT. See [LICENSE](LICENSE).
