"""Window colours: the stock app theme, recoloured for a Look.

GTK has no setting that tints every window. It does load a theme found in the user's data
folder in place of a system theme of the same name, so the stock stylesheet is recoloured
here and the engine installs the result under the stock name. Every grey takes the look's
hue and the stock accent becomes the look's accent. Each colour keeps its luminance, so text
is exactly as readable as the theme's authors made it; everything else stays theirs.

Nothing in here writes a file or reads a setting.
"""
from __future__ import annotations

import colorsys
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ricer.look import Look
from ricer.palette import hex_to_rgb, hue_distance, hue_of, luminance, saturation_of, with_luminance

NEUTRAL = 0.14                       # stock colours less saturated than this count as greys
ACCENT_WINDOW = 10.0                 # degrees around the stock accent's hue that belong to it
FADE = (0.30, 0.80)                  # lightness over which greys shed their tint: text stays crisp
TEXT_TINT = 0.3                      # the share of the tint that the lightest greys keep
STRENGTH = (0.16, 0.42)              # saturation of the darkest greys, from pale cards to vivid ones
ACCENT_SATURATION = (0.6, 1.2)       # how far accent shades may be scaled toward the look's
MAX_IMPORTS = 4                      # how deep @import is followed
MARK = "/* Written by ricer"         # first words of every file ricer puts in a theme folder
BLOCK_START, BLOCK_END = "/* ricer:begin", "/* ricer:end */"
OUTLINES = {"hairline": "rgba(255, 255, 255, 0.12)"}         # window outline per border style
STOCK_SURFACE = (44, 44, 44)         # a theme that names no window colour is taken to use this one
# libadwaita's own dark colours, which a look recolours the same way as a GTK 3 theme
ADWAITA_SURFACES = {
    "window_bg_color": "#242424", "view_bg_color": "#1e1e1e",
    "headerbar_bg_color": "#303030", "headerbar_backdrop_color": "#242424",
    "sidebar_bg_color": "#303030", "sidebar_backdrop_color": "#2a2a2a",
    "secondary_sidebar_bg_color": "#2a2a2a", "secondary_sidebar_backdrop_color": "#272727",
    "dialog_bg_color": "#383838", "popover_bg_color": "#383838", "thumbnail_bg_color": "#383838",
}
ADWAITA_ACCENT_BG, ADWAITA_ACCENT = "#3584e4", "#78aeed"     # behind white text; on a dark surface


@dataclass(frozen=True)
class Tone:
    """What a recolouring aims for."""
    hue: float                       # degrees: the hue every grey takes
    strength: float                  # saturation of the darkest greys; 0 leaves them grey
    accent: str                      # '#rrggbb': what the stock accent turns into


def tone_for(look: Look) -> Tone:
    """Windows take the colour of the look's cards, as strongly as the cards have it."""
    card = look.palette.card
    low, high = STRENGTH
    return Tone(hue=hue_of(card), strength=round(max(low, min(high, saturation_of(card))), 3),
                accent=look.palette.accent)


def stock_accent(css: str) -> str | None:
    """The accent a GTK 3 stylesheet was built around, if it names one."""
    return named_colour(css, "theme_selected_bg_color")


def named_colour(css: str, name: str) -> str | None:
    match = re.search(rf"@define-color\s+{re.escape(name)}\s+(#[0-9a-fA-F]{{6}})\b", css)
    return match.group(1).lower() if match else None


class Recolour:
    """Turns one stock colour into its counterpart in the look. Colours are 0..255 triples."""

    def __init__(self, tone: Tone, accent: str | None = None):
        self.tone = tone
        self._from = hue_of(accent) if accent else None
        self._to = hue_of(tone.accent)
        low, high = ACCENT_SATURATION
        wanted = saturation_of(tone.accent) / max(0.05, saturation_of(accent)) if accent else 1.0
        self._saturation = max(low, min(high, wanted))
        self._seen: dict[tuple[int, int, int], tuple[int, int, int] | None] = {}

    def __call__(self, red: int, green: int, blue: int) -> tuple[int, int, int] | None:
        """The new colour, or None where the stock one stays."""
        key = (red, green, blue)
        if key not in self._seen:
            self._seen[key] = self._map(tuple(channel / 255 for channel in key))
        return self._seen[key]

    def of(self, red: int, green: int, blue: int) -> tuple[int, int, int]:
        return self(red, green, blue) or (red, green, blue)

    def _map(self, rgb) -> tuple[int, int, int] | None:
        hue, lightness, saturation = colorsys.rgb_to_hls(*rgb)
        if saturation < NEUTRAL:
            start, end = FADE
            fade = min(1.0, max(0.0, (lightness - start) / (end - start)))
            wanted = self.tone.strength * (1 - (1 - TEXT_TINT) * fade)
            new = with_luminance(self.tone.hue, wanted, luminance(rgb))
        elif self._from is not None and hue_distance(hue * 360, self._from) <= ACCENT_WINDOW:
            new = with_luminance(self._to, min(1.0, saturation * self._saturation), luminance(rgb))
        else:
            return None                                      # warnings, errors, links: theirs
        new = tuple(round(channel * 255) for channel in new)
        return None if new == tuple(round(channel * 255) for channel in rgb) else new


# Colours are only swapped inside declarations. Out in the selectors '#name' is an id, and
# inside comments, strings and url() anything that looks like a colour is something else.
_TOKEN = re.compile(r"""
      (?P<skip> /\*.*?\*/ | "(?:\\.|[^"\\])*" | '(?:\\.|[^'\\])*' | url\([^)]*\) )
    | (?P<open> \{ ) | (?P<close> \} ) | (?P<end> ; ) | (?P<define> @define-color\b )
    | \#(?P<hex> [0-9a-fA-F]{6} | [0-9a-fA-F]{3} ) (?![\w-])
    | \b(?P<func> rgba? ) \( \s* (?P<r>\d{1,3}) \s* , \s* (?P<g>\d{1,3}) \s* , \s* (?P<b>\d{1,3})
      \s* (?P<alpha> , [^)]* )? \)
""", re.S | re.X)


def recolour(css: str, colour) -> str:
    """`css` with every literal colour passed through `colour(r, g, b)`.

    Where `colour` returns None the text is left byte for byte as it was.
    """
    depth, defining = 0, False

    def swap(match: re.Match) -> str:
        nonlocal depth, defining
        text = match.group(0)
        if match.group("skip"):
            return text
        if match.group("open"):
            depth += 1
        elif match.group("close"):
            depth = max(0, depth - 1)
        elif match.group("end"):
            defining = False
        elif match.group("define"):
            defining = True
        elif depth or defining:
            if match.group("hex"):
                digits = match.group("hex")
                if len(digits) == 3:
                    digits = "".join(digit * 2 for digit in digits)
                new = colour(*(int(digits[i:i + 2], 16) for i in (0, 2, 4)))
                return text if new is None else "#%02x%02x%02x" % new
            old = tuple(int(match.group(name)) for name in "rgb")
            new = colour(*old) if max(old) <= 255 else None
            if new is not None:
                return f"{match.group('func')}({new[0]}, {new[1]}, {new[2]}{match.group('alpha') or ''})"
        return text

    return _TOKEN.sub(swap, css)


# -- reading a stock theme ------------------------------------------------------------------

_IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?(["']?)([^"')\s;]+)\1\s*\)?\s*;""")
_URL = re.compile(r"""url\(\s*(["']?)(.*?)\1\s*\)""")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def open_bundle(path: Path):
    """A reader for the stylesheets compiled into a theme's .gresource file, or None."""
    try:
        from gi.repository import Gio
        bundle = Gio.Resource.load(str(path))
    except Exception:                                        # no PyGObject, no file, not a bundle
        return None

    def read(name: str) -> str:
        try:
            return bundle.lookup_data(name, Gio.ResourceLookupFlags.NONE).get_data().decode()
        except Exception as error:
            raise OSError(f"{name} is not in {path}") from error
    return read


def _flatten(uri: str, read, depth: int) -> str:
    text = read(uri)
    base = uri.rsplit("/", 1)[0] + "/"

    def absolute(reference: str) -> str:
        if _SCHEME.match(reference):
            return reference
        return Path(reference).as_uri() if reference.startswith("/") else base + reference

    def inline(match: re.Match) -> str:
        return _flatten(absolute(match.group(2)), read, depth + 1) if depth < MAX_IMPORTS else ""

    text = _IMPORT.sub(inline, text)
    return _URL.sub(lambda match: f'url("{absolute(match.group(2))}")', text)


def stock_sheet(folder: Path, bundles=open_bundle) -> str | None:
    """A theme's `gtk-3.0/gtk.css` as one text: imports inlined, every url() made absolute.

    Themes such as Yaru keep the real stylesheet inside `gtk.gresource` and import it from
    there. Made absolute, its pictures still load once the text lives somewhere else.
    None if the theme cannot be read.
    """
    opened = []

    def read(uri: str) -> str:
        if uri.startswith("resource://"):
            if not opened:
                opened.append(bundles(folder / "gtk.gresource"))
            if opened[0] is None:
                raise OSError(f"{folder} has no readable gtk.gresource")
            return opened[0](uri[len("resource://"):])
        return Path(unquote(urlsplit(uri).path)).read_text()

    try:
        return _flatten((folder / "gtk.css").as_uri(), read, 0)
    except (OSError, UnicodeError):
        return None


# -- what ricer writes ------------------------------------------------------------------------

def _triplet(colour) -> str:
    return ", ".join(str(channel) for channel in colour)


def _hex(colour) -> str:
    return "#%02x%02x%02x" % tuple(colour)


def _ints(colour: str) -> tuple[int, int, int]:
    return tuple(round(channel * 255) for channel in hex_to_rgb(colour))


def rules(look: Look, colour: Recolour, surface: tuple[int, int, int], glass: float | None) -> str:
    """The look's own rules, which follow the stock ones.

    `surface` is the stock window colour. `glass` is how opaque GNOME Terminal's title and tab
    bars are, for a terminal whose text area is see-through; None leaves them solid.
    """
    accent = _triplet(_ints(look.palette.accent))
    lines = ["", "", "/* ricer: what the look adds to the stock theme */"]
    outline = OUTLINES.get(look.style.border) or (
        f"rgba({accent}, 0.85)" if look.style.border == "accent" else None)
    if outline:
        faint = OUTLINES.get(look.style.border) or f"rgba({accent}, 0.3)"
        lines += [
            f"decoration {{ box-shadow: 0 3px 9px 1px rgba(0, 0, 0, 0.5), 0 0 0 1px {outline}; }}",
            "decoration:backdrop { box-shadow: 0 3px 9px 1px transparent, "
            f"0 2px 6px 2px rgba(0, 0, 0, 0.2), 0 0 0 1px {faint}; }}",
        ]
    if glass is not None:
        pane = f"rgba({_triplet(colour.of(*surface))}, {round(glass, 2)})"
        lines += [
            # the title bar, the tab bar and the text area become one pane of tinted glass
            f"terminal-window.background, terminal-window.background:backdrop {{ background-color: {pane}; }}",
            f"terminal-window headerbar, terminal-window headerbar:backdrop {{ background: {pane}; "
            f"border-color: rgba({accent}, 0.22); box-shadow: inset 0 1px rgba(255, 255, 255, 0.06); }}",
            "terminal-window notebook > header, terminal-window notebook > header:backdrop "
            f"{{ background-color: transparent; border-color: rgba({accent}, 0.16); }}",
            "terminal-window notebook > header tab, terminal-window notebook > header tab:backdrop "
            "{ background-color: transparent; }",
            f"terminal-window notebook > header tab:checked {{ background-color: rgba({accent}, 0.14); }}",
        ]
    return "\n".join(lines) + "\n"


def render(stock: str, look: Look, glass: float | None = None) -> str:
    """A stock GTK 3 stylesheet in the look's colours."""
    colour = Recolour(tone_for(look), stock_accent(stock))
    surface = named_colour(stock, "theme_bg_color")
    return recolour(stock, colour) + rules(look, colour, _ints(surface) if surface else STOCK_SURFACE,
                                           glass)


def sheet_name(css: str) -> str:
    """A file name that stands for exactly this stylesheet."""
    return hashlib.sha256(css.encode()).hexdigest()[:16] + ".css"


def stub(sheet: Path) -> str:
    """What goes in the theme folder: a few words and a hand-over to the generated stylesheet."""
    return (f"{MARK}: this look's window colours. `ricer revert` takes them away. */\n"
            f'@import url("{sheet.as_uri()}");\n')


def is_ours(text: str) -> bool:
    return text.startswith(MARK)


def adwaita(look: Look) -> str:
    """Colour definitions for libadwaita apps, which take colours by name and not from a theme."""
    tone = tone_for(look)
    colour = Recolour(tone)
    accent_hue, saturation = hue_of(tone.accent), saturation_of(tone.accent)

    def accent(like: str) -> str:
        new = with_luminance(accent_hue, saturation, luminance(hex_to_rgb(like)))
        return _hex(round(channel * 255) for channel in new)

    names = {"accent_color": accent(ADWAITA_ACCENT), "accent_bg_color": accent(ADWAITA_ACCENT_BG),
             "accent_fg_color": "#ffffff",
             **{name: _hex(colour.of(*_ints(grey))) for name, grey in ADWAITA_SURFACES.items()}}
    lines = [f"{BLOCK_START}: this look's window colours; rewritten by every look */",
             *(f"@define-color {name} {value};" for name, value in names.items()), BLOCK_END]
    return "\n".join(lines) + "\n"


def block_in(text: str | None) -> str | None:
    """Ricer's block inside a user stylesheet, or None if it has none."""
    start = (text or "").find(BLOCK_START)
    end = (text or "").find(BLOCK_END, start)
    if start < 0 or end < 0:
        return None
    return text[start:end + len(BLOCK_END)] + "\n"


def without_block(text: str) -> str:
    """A user stylesheet with ricer's block taken out and everything else as it was."""
    start = text.find(BLOCK_START)
    end = text.find(BLOCK_END, start)
    if start < 0 or end < 0:
        return text
    return text[:start] + text[end + len(BLOCK_END):].lstrip("\n")


def with_block(text: str | None, block: str) -> str:
    """A user stylesheet with ricer's block in it, ahead of whatever the user wrote."""
    return block + without_block(text or "")
