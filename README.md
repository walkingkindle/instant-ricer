# instant-ricer

A desktop ricing engine for GNOME. Turn four dials and it composes a whole look: wallpaper,
colours, top bar, dock, terminal, and widgets on the desktop and in the bar. It applies
live, with no logout, and one command puts everything back.

```
ricer instant --cool 8 --ease 4 --warmth 7
```

**Every run is different.** The dials do not select a look, they tilt the odds. Run the same
command again and you get another wallpaper, other widgets in other designs and places.
Each run prints a seed, and that seed brings its look back exactly.

## The dials

Each goes from 1 to 10. Dials you leave out are 5.

| Dial | Makes more likely |
|---|---|
| `--cool` | More widgets on the desktop (about cool minus two), bolder designs, ornaments, saturated colour, gradients, blur, a flashier top bar |
| `--ease` | Information in the top bar (stats from about 5, a media player from about 7), larger text, more opaque cards, calmer wallpapers, tidy column layouts, a dock that stays visible |
| `--warmth` | Warm wallpapers and hues, round shapes, serif type, an analogue clock, a greeting. Low values: sharp outlined cards, mono and condensed type, a digital clock, system stats |
| `--chaos` | How far a run may stray. 1 gives small variations on what the other dials suggest; 10 draws from the whole vocabulary |

`--all N` sets cool, ease and warmth together; chaos is separate.

```
ricer instant --all 3                 # calm
ricer instant --all 9 --chaos 10      # everything, everywhere
ricer reroll                          # same dials as now, a new look
ricer reroll --keep wallpaper,style   # keep those parts, reroll the rest
ricer instant --all 6 --seed 428327877   # an earlier look, exactly
```

Found one you like? `ricer default set` keeps it, and `ricer default` returns to it from
any other look. It is stored as the look itself, not as dials and a seed, so it survives
changes to the wallpaper folder and to ricer. A look also simply stays: nothing changes,
across logins and reboots, until you run ricer again.

Some things are rules, not odds. Text stays readable: a widget gets a card behind it when
its spot on the wallpaper is busy or bright. Widgets never overlap each other or the dock.
From ease 7 the dock never hides. At cool 1 and 2 the desktop stays nearly empty.

## What a look is made of

**One style per look**, shared by every part so the desktop matches itself: corner radius,
card opacity (down to no card at all), border (none, hairline, accent), type weight,
typeface voice (interface, condensed, mono, serif or geometric, resolved to fonts you have
installed), capitals for labels, gradient or flat accents, text scale. The accent colours
come from the wallpaper.

**Desktop widgets**

| Widget | Designs |
|---|---|
| Clock | one line of digits, stacked digits, analogue dial, words ("twenty past six") |
| Greeting | a time-of-day line with your name and the date |
| Calendar | month grid, week strip, big day block |
| Media | full card, small pill, large cover art; controls any MPRIS player |
| System | bars, ring gauges, or one line: CPU, memory, temperature, GPU, battery |
| Progress | how far through the day, week, month and year it is |
| Ornament | a small abstract figure drawn from the seed, different for every look |

**Top bar**: stock, plain transparent, one floating piece, three floating cards, or solid.
System stats and a media player can sit in the bar itself, so they stay visible over
full-screen windows.

**The rest**: dock side, auto-hide, size, indicator style and tint; icon and cursor set;
terminal colours; Home and drive icons are hidden while desktop widgets are shown.

## How a look is composed

1. A fresh seed is drawn (or `--seed` is used).
2. The look is built in stages, each with its own random stream and its own odds: wallpaper,
   style, colours, bar, dock, widget set and designs, placement.
3. Placement reads the wallpaper. Every image is analysed once into a grid of busy, bright
   and subject-like areas. The screen has nine zones; a widget goes where the picture is
   calm and its subject stays uncovered. Layout templates (corners, column, stage, scatter)
   bias the choice, and widgets that share a zone stack with a common width.
4. Several candidate seeds are generated. Seeds leading to a wallpaper used in the last
   three looks are passed over, badly placed candidates are marked down, and the one most
   unlike your recent looks is applied.

A seed is only ever chosen, never altered, so `--seed` reproduces a look as long as the
wallpaper folder and screen size are the same.

## Requirements

- GNOME 45 or newer. Developed on Ubuntu 24.04 (GNOME 46).
- Python 3.10+, PyGObject and GTK 3 from your distribution, and the `dconf` command.
  On Ubuntu these are already installed; elsewhere look for `python3-gi` / `python-gobject`.
- Pillow (installed automatically).

Everything else is optional. Ricer checks what the desktop has, skips the rest, and says
what it skipped. `ricer status` lists it.

| Feature | Needs |
|---|---|
| Desktop widgets | an X11 session (see [Limits](#limits)) |
| Top bar styling | [User Themes](https://extensions.gnome.org/extension/19/user-themes/) |
| Stats in the top bar | [Vitals](https://extensions.gnome.org/extension/1460/vitals/) |
| Player in the top bar | [Media Controls](https://extensions.gnome.org/extension/4470/media-controls/) |
| Blur | [Blur my Shell](https://extensions.gnome.org/extension/3193/blur-my-shell/) |
| Dock styling | Ubuntu Dock or [Dash to Dock](https://extensions.gnome.org/extension/307/dash-to-dock/) |
| Terminal colours | GNOME Terminal |
| Accent-matched app theme | Yaru variants (Ubuntu); on GNOME 47+ the system accent colour is set instead |
| Other icons and cursor | Papirus-Dark and Bibata-Modern-Ice, used only if installed |

`ricer setup` installs the missing extensions through GNOME's own dialog: you confirm each
one on screen. Ricer switches Vitals and Media Controls on and off per look.

## Install

PyGObject comes from the system, so the environment must be able to see system packages:

```
pipx install --system-site-packages git+https://github.com/walkingkindle/instant-ricer
ricer setup
ricer wallpapers fetch --count 20
ricer instant
```

or from a checkout:

```
git clone https://github.com/walkingkindle/instant-ricer && cd instant-ricer
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
.venv/bin/ricer status
```

## Wallpapers

Ricer ships no images. It picks from a folder on your machine, `~/Pictures/Wallpapers` by
default (set `RICER_WALLPAPERS` to use another). The more it holds, the more the looks vary.

```
ricer wallpapers fetch --count 20      # SFW anime scenery from wallhaven.cc
ricer wallpapers fetch --query "anime sunset landscape"
ricer wallpapers add ~/Downloads/some-image.png
ricer wallpapers list                  # each image with its measured mood
```

Each image is measured for warmth, colourfulness, detail and brightness; `--warmth` matters
most when choosing, then `--cool` (vivid) and `--ease` (calm). Fetched images belong to
their artists and are for your own desktop.

## Commands

```
ricer instant [--cool N] [--ease N] [--warmth N] [--chaos N] [--all N]
              [--seed N] [--keep PARTS] [--dry-run] [--json]
ricer reroll  [the same options]       dials you leave out stay as in the current look
ricer default [set | show | clear]     return to your saved look; `set` saves the current one
ricer setup                            install the optional extensions
ricer revert [--all]
ricer status
ricer wallpapers list | add FILE... | fetch [--count N] [--query WORDS]
ricer widgets start | stop
```

- `--keep` takes a comma-separated list of `wallpaper`, `style`, `widgets`, `layout`, `bar`
  and `dock`: those parts of the current look are carried over and the rest is rerolled.
- `--dry-run` prints the look and changes nothing. `--json` prints it in full.
- `ricer revert` undoes the last look. `ricer revert --all` undoes everything ricer has ever
  changed.

## What it changes

Ricer only writes settings it owns, and records the previous value of each first:

- wallpaper and lock-screen background, dark colour scheme, app theme, icons, cursor
- the dock's position, auto-hide, size, opacity, indicator and tint
- the top bar, through a generated shell theme at `~/.local/share/themes/Ricer`
- Vitals and Media Controls: their settings, and whether each is switched on
- Blur my Shell's blur switches
- the desktop-icon extension's Home and drive icons
- the default GNOME Terminal profile's colours
- its own files in `~/.config/ricer/` and `~/.cache/ricer/`, and an autostart entry for
  the widgets

If applying fails part-way, what was already written is put back.

## Limits

- **Desktop widgets need X11.** GNOME on Wayland does not let an application pin a window to
  the desktop layer. There, everything else is applied, including the widgets in the bar.
- **GNOME only.** On other desktops `ricer instant` refuses to run (`--dry-run` still works).
- **Sized for 1080p and up.** On smaller screens a widget that does not fit is left out.
- **The subject detector is a heuristic** (colour and brightness that stand out, plus
  detail). It keeps widgets off the obvious centre of interest, not off every face.
- The top-bar theme is layered over the stock Yaru shell theme. On distributions without
  Yaru it imports GNOME's built-in dark theme instead; that path is not yet tested.
- English only: the word clock and the greeting are not translated.

## Development

```
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

**The Look is the contract.** `look.py` defines one plain-data structure describing a whole
desktop. The generator writes it and the engine applies it; anything else that can write
one (a GUI, a model acting as art director) can drive the desktop the same way.

| Module | Role |
|---|---|
| `look.py` | the Look and its validation |
| `chance.py` | seeded streams; choices tempered by chaos |
| `generator.py` | dials and seed to a Look, stage by stage (pure) |
| `compose.py` | candidates, novelty against recent looks, the final choice |
| `wallpapers.py`, `palette.py` | image analysis, scoring, colours, fetching |
| `placement.py`, `metrics.py` | zones, costs, stacking; widget sizes |
| `engine.py`, `backends.py`, `capabilities.py` | apply, snapshot, revert; the desktop behind an interface with an in-memory fake |
| `shell_theme.py`, `data/` | the top-bar stylesheet |
| `widgets/` | the daemon and every widget design |

Everything that decides is pure and tested without a desktop. Widgets are tested by drawing
them offscreen; the window tests are skipped when there is no display.

Visual work is judged by eye, with three tools:

```
.venv/bin/python tools/contact_sheet.py sheet.png [wallpaper]   # every design under four styles
.venv/bin/python tools/heatmaps.py maps.png                     # what the analysis sees in each wallpaper
.venv/bin/python tools/preview.py look.png --cool 8 --grid 3x3  # nine fresh looks, drawn without applying
```

## Licence

MIT. See [LICENSE](LICENSE).
