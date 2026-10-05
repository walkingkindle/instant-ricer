"""Cairo drawing helpers shared by the widgets."""
from __future__ import annotations

import math

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

from ricer.widgets.style import Style


def rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def make_layout(cr, text, font, spacing=0, width=None):
    layout = PangoCairo.create_layout(cr)
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


def measure_text(text, font, spacing=0):
    """Pixel size of one line of text, without needing a window."""
    cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
    return make_layout(cr, text, font, spacing).get_pixel_size()


def draw_text(cr, text, font, x, y, color, alpha=1.0, spacing=0, width=None,
              align="left", shadow=False):
    """Draw one line of text; x is the left edge, centre or right edge per `align`."""
    layout = make_layout(cr, text, font, spacing, width)
    w, h = layout.get_pixel_size()
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    if shadow:
        # soft drop shadow so text with no card behind it stays readable on bright wallpapers
        for off, a in ((4, 0.14), (2, 0.24), (1, 0.34)):
            cr.move_to(x, y + off)
            cr.set_source_rgba(0, 0, 0, a * alpha)
            PangoCairo.show_layout(cr, layout)
    cr.move_to(x, y)
    cr.set_source_rgba(*color, alpha)
    PangoCairo.show_layout(cr, layout)
    return w, h


def set_accent_source(cr, style: Style, x0, x1, alpha=0.95):
    """Accent paint running from x0 to x1: a two-colour gradient, or flat if the style says so."""
    if not style.gradient:
        cr.set_source_rgba(*style.accent, alpha)
        return
    gradient = cairo.LinearGradient(x0, 0, x1, 0)
    gradient.add_color_stop_rgba(0, *style.accent, alpha)
    gradient.add_color_stop_rgba(1, *style.accent2, alpha)
    cr.set_source(gradient)


def draw_bar(cr, style: Style, x, y, w, frac, knob=False, line_width=3):
    """Thin track from x to x+w with the first `frac` filled in the accent."""
    frac = max(0.0, min(1.0, frac))
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_width(line_width)
    cr.set_source_rgba(1, 1, 1, 0.18)
    cr.move_to(x, y)
    cr.line_to(x + w, y)
    cr.stroke()
    if frac > 0:
        set_accent_source(cr, style, x, x + w)
        cr.move_to(x, y)
        cr.line_to(x + w * frac, y)
        cr.stroke()
        if knob:
            cr.arc(x + w * frac, y, line_width + 1, 0, 2 * math.pi)
            cr.fill()


def draw_card(cr, style: Style, width, height):
    rounded_rect(cr, 0.5, 0.5, width - 1, height - 1, style.px(18))
    cr.set_source_rgba(*style.card)
    cr.fill_preserve()
    cr.set_source_rgba(1, 1, 1, 0.10)
    cr.set_line_width(1)
    cr.stroke()
