"""Cairo drawing helpers shared by the widgets."""
from __future__ import annotations

import math

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

from ricer.widgets.style import Style

SHADOW = ((4, 0.14), (2, 0.24), (1, 0.34))                   # offset px, opacity
# Widgets are drawn on transparent windows. Sub-pixel (LCD) text rendering assumes an opaque
# background and leaves coloured fringes there, so text is always smoothed in plain grey.
FONT_OPTIONS = cairo.FontOptions()
FONT_OPTIONS.set_antialias(cairo.ANTIALIAS_GRAY)
FONT_OPTIONS.set_hint_style(cairo.HINT_STYLE_SLIGHT)


def rounded_rect(cr, x, y, w, h, r):
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def make_layout(cr, text, font, spacing=0, width=None):
    layout = PangoCairo.create_layout(cr)
    PangoCairo.context_set_font_options(layout.get_context(), FONT_OPTIONS)
    layout.context_changed()
    layout.set_font_description(Pango.FontDescription(font))
    if spacing:
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_letter_spacing_new(int(spacing * Pango.SCALE)))
        layout.set_attributes(attrs)
    if width:
        layout.set_width(int(width * Pango.SCALE))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
    layout.set_text(text, -1)
    return layout


def _scratch():
    return cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))


def measure_text(text, font, spacing=0) -> tuple[int, int]:
    """Pixel size of one line's line box, without needing a window."""
    return make_layout(_scratch(), text, font, spacing).get_pixel_size()


def measure_ink(text, font, spacing=0) -> tuple[int, int]:
    """Pixel size of what one line actually paints: tighter than its line box."""
    ink, _ = make_layout(_scratch(), text, font, spacing).get_pixel_extents()
    return ink.width, ink.height


def set_accent_source(cr, style: Style, x0, x1, alpha=0.95):
    """Accent paint running from x0 to x1: a two-colour gradient, or flat if the style says so."""
    if not style.gradient:
        cr.set_source_rgba(*style.accent, alpha)
        return
    gradient = cairo.LinearGradient(x0, 0, x1, 0)
    gradient.add_color_stop_rgba(0, *style.accent, alpha)
    gradient.add_color_stop_rgba(1, *style.accent2, alpha)
    cr.set_source(gradient)


def draw_text(cr, text, font, x, y, color, alpha=1.0, spacing=0, width=None, align="left",
              shadow=False, accent: Style | None = None, ink=False):
    """Draw one line of text. Returns its (width, height).

    x is the left edge, centre or right edge per `align`; y is the top. With `ink`, the box
    positioned and measured is what the glyphs paint, not the taller line box. `accent`
    paints the text in the style's accent (a gradient if it has one) instead of `color`.
    """
    layout = make_layout(cr, text, font, spacing, width)
    ink_box, _ = layout.get_pixel_extents()
    if ink:
        w, h, dx, dy = ink_box.width, ink_box.height, -ink_box.x, -ink_box.y
    else:
        (w, h), dx, dy = layout.get_pixel_size(), 0, 0
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    if shadow:
        # Text with no card behind it has to survive whatever the wallpaper does there: a dark
        # halo hugging the letters for busy backgrounds, a soft drop shadow for bright ones.
        cr.move_to(x + dx, y + dy)
        PangoCairo.layout_path(cr, layout)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_width(min(5.0, max(2.5, ink_box.height * 0.09)))
        cr.set_source_rgba(0, 0, 0, 0.30 * alpha)
        cr.stroke()
        for offset, opacity in SHADOW:
            cr.move_to(x + dx, y + dy + offset)
            cr.set_source_rgba(0, 0, 0, opacity * alpha)
            PangoCairo.show_layout(cr, layout)
    cr.move_to(x + dx, y + dy)
    if accent is not None:
        set_accent_source(cr, accent, x, x + w, alpha)
    else:
        cr.set_source_rgba(*color, alpha)
    PangoCairo.show_layout(cr, layout)
    # drawing text leaves a current point behind; an arc drawn next would start with a line
    # from it, so every text call ends with a clean path
    cr.new_path()
    return w, h


def draw_bar(cr, style: Style, x, y, w, frac, knob=False, line_width=3, hot=False):
    """Thin track from x to x+w with the first `frac` filled in the accent (or the hot colour)."""
    frac = max(0.0, min(1.0, frac))
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_width(line_width)
    cr.set_source_rgba(*style.text, 0.18)
    cr.move_to(x, y)
    cr.line_to(x + w, y)
    cr.stroke()
    if frac > 0:
        if hot:
            cr.set_source_rgba(*style.hot, 0.95)
        else:
            set_accent_source(cr, style, x, x + w)
        cr.move_to(x, y)
        cr.line_to(x + w * frac, y)
        cr.stroke()
        if knob:
            cr.arc(x + w * frac, y, line_width + 1, 0, 2 * math.pi)
            cr.fill()


def draw_card(cr, style: Style, width, height, fill: float):
    """The backing card of a widget. With no fill there is no card at all, border included."""
    if fill <= 0:
        return
    inset = 0.75 if style.border == "accent" else 0.5
    rounded_rect(cr, inset, inset, width - 2 * inset, height - 2 * inset, style.radius)
    cr.set_source_rgba(*style.card, fill)
    if style.border == "none":
        cr.fill()
        return
    cr.fill_preserve()
    if style.border == "accent":
        cr.set_source_rgba(*style.accent, 0.85)
        cr.set_line_width(1.5)
    else:
        cr.set_source_rgba(1, 1, 1, 0.10)
        cr.set_line_width(1)
    cr.stroke()


def draw_rows(cr, style: Style, rows, width: float, bare: bool) -> None:
    """Labelled bars, one per (label, fraction, value text, is hot) row, filling a card's width."""
    pad, step = style.px(18), style.px(32)
    small = style.ui(9)
    labels = [style.label(label) for label, *_ in rows]
    # the bars all start just past the longest label and stop short of the value column
    start = pad + max((measure_text(label, small, style.label_spacing)[0] for label in labels),
                      default=0) + style.px(12)
    end = width - pad - style.px(44)
    for index, (label, (_, frac, text, hot)) in enumerate(zip(labels, rows)):
        y = pad + step * index + step / 2
        draw_text(cr, label, small, pad, y - style.px(8), style.text, alpha=0.70,
                  spacing=style.label_spacing, shadow=bare)
        draw_text(cr, text, small, width - pad, y - style.px(8), style.hot if hot else style.text,
                  alpha=0.92, align="right", shadow=bare)
        draw_bar(cr, style, start, y, max(style.px(20), end - start), frac,
                 line_width=style.px(4), hot=hot)


def align_x(align: str, width: float, pad: float = 0.0) -> float:
    """The x that draw_text wants for text aligned `align` inside a box of `width`."""
    if align == "center":
        return width / 2
    return width - pad if align == "right" else pad


class Widget:
    """What every desktop widget has: a style, its options, and a size in pixels."""

    clickable = False
    width = 0
    height = 0

    def __init__(self, style: Style, options: dict):
        self.style = style
        self.options = options
        self.fill = options.get("fill", style.fill)
        self.align = options.get("align", "left")

    @property
    def bare(self) -> bool:
        """No card behind this widget: its text needs a shadow instead."""
        return self.fill <= 0

    def tick(self, _count: int) -> bool:
        """Called once a second; return True to be redrawn."""
        return False

    def draw_card(self, cr) -> None:
        draw_card(cr, self.style, self.width, self.height, self.fill)

    def draw(self, cr) -> None:
        raise NotImplementedError
