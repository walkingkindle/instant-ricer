"""System widget: CPU, memory, temperatures and battery, in three designs."""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import cairo

from ricer import metrics
from ricer.widgets.drawing import Widget, draw_rows, draw_text, measure_text, set_accent_source
from ricer.widgets.style import Style

CPU_SENSORS = ("coretemp", "k10temp", "zenpower")   # hwmon driver names for CPU temperature
GPU_SENSORS = ("amdgpu", "nouveau")                 # GPUs that report through hwmon
TEMP_RANGE = (30, 100)               # °C mapped to an empty / full temperature bar
TEMP_HOT = 85                        # °C at which a reading turns red
GPU_POLL_TICKS = 6                   # asking nvidia-smi is slow-ish, so do it less often
LABELS = {"cpu": "CPU", "ram": "RAM", "temp": "Temp", "gpu": "GPU", "battery": "Bat"}


def read_cpu_times(root: Path = Path("/")) -> tuple[int, int]:
    """(idle, total) jiffies summed over all cores."""
    fields = [int(v) for v in (root / "proc/stat").read_text().splitlines()[0].split()[1:]]
    return fields[3] + fields[4], sum(fields)               # idle + iowait, total


def cpu_usage(before: tuple[int, int], after: tuple[int, int]) -> float:
    """Busy share of CPU time between two read_cpu_times() samples."""
    idle, total = after[0] - before[0], after[1] - before[1]
    return 1 - idle / total if total > 0 else 0.0


def memory_usage(root: Path = Path("/")) -> float:
    info = {}
    for line in (root / "proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        info[key] = int(value.split()[0])
    return 1 - info["MemAvailable"] / info["MemTotal"]


def hwmon_temperature(names, root: Path = Path("/")) -> float | None:
    """°C from the first hwmon sensor whose driver name is in `names`."""
    for hwmon in sorted((root / "sys/class/hwmon").glob("hwmon*")):
        try:
            if (hwmon / "name").read_text().strip() in names:
                return int((hwmon / "temp1_input").read_text()) / 1000
        except (OSError, ValueError):
            pass
    return None


def cpu_temperature(root: Path = Path("/")) -> float | None:
    return hwmon_temperature(CPU_SENSORS, root)


def gpu_temperature(root: Path = Path("/"), which=shutil.which, run=subprocess.run) -> float | None:
    """°C of the GPU: nvidia-smi for Nvidia's driver, hwmon for the open drivers."""
    if which("nvidia-smi"):
        try:
            done = run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
                       capture_output=True, text=True, timeout=2)
            return float(done.stdout.split()[0])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None
    return hwmon_temperature(GPU_SENSORS, root)


def battery_level(root: Path = Path("/")) -> float | None:
    for path in sorted((root / "sys/class/power_supply").glob("BAT*/capacity")):
        try:
            return int(path.read_text()) / 100
        except (OSError, ValueError):
            pass
    return None


def temperature_fraction(celsius: float) -> float:
    low, high = TEMP_RANGE
    return (celsius - low) / (high - low)


class System(Widget):
    """The bars design, and the readings every design shares."""

    design = "bars"

    def __init__(self, style: Style, options: dict, root: Path = Path("/")):
        super().__init__(style, options)
        self.root = root
        self.cpu = 0.0
        self.gpu = None
        self._times = read_cpu_times(root)
        wanted = options.get("rows", ["cpu", "ram"])
        if "gpu" in wanted:
            self.gpu = gpu_temperature(root)
        # a row whose sensor this machine lacks is dropped rather than shown empty
        self.rows = [row for row in wanted if self.reading(row) is not None]
        width, height = metrics.system_size(self.design, len(self.rows), options.get("width"))
        self.width, self.height = math.ceil(style.px(width)), math.ceil(style.px(height))

    def reading(self, row: str):
        """(bar fraction, value text, is hot) for a row, or None if it cannot be read."""
        if row == "cpu":
            return self.cpu, f"{round(self.cpu * 100)}%", False
        if row == "ram":
            used = memory_usage(self.root)
            return used, f"{round(used * 100)}%", False
        if row in ("temp", "gpu"):
            celsius = cpu_temperature(self.root) if row == "temp" else self.gpu
            if celsius is None:
                return None
            return temperature_fraction(celsius), f"{round(celsius)}°C", celsius >= TEMP_HOT
        level = battery_level(self.root)
        return None if level is None else (level, f"{round(level * 100)}%", False)

    def readings(self) -> list[tuple[str, float, str, bool]]:
        """(label, fraction, value text, is hot) for every row that can be read right now."""
        found = []
        for row in self.rows:
            reading = self.reading(row)
            if reading is not None:
                found.append((LABELS[row], *reading))
        return found

    def tick(self, count: int) -> bool:
        if count % 2:
            return False
        now = read_cpu_times(self.root)
        self.cpu, self._times = cpu_usage(self._times, now), now
        if "gpu" in self.rows and count % GPU_POLL_TICKS == 0:
            self.gpu = gpu_temperature(self.root)
        return True

    def draw(self, cr) -> None:
        self.draw_card(cr)
        draw_rows(cr, self.style, self.readings(), self.width, self.bare)


class SystemRings(System):
    """A row of ring gauges, each with its value in the middle."""

    design = "rings"

    def draw(self, cr) -> None:
        style, px = self.style, self.style.px
        self.draw_card(cr)
        readings = self.readings()
        if not readings:
            return
        pad = px(metrics.PAD)
        slot = (self.width - 2 * pad) / len(readings)
        radius = min(px(26), slot / 2 - px(5))
        cy = px(16) + px(26)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for index, (label, frac, text, hot) in enumerate(readings):
            cx = pad + slot * (index + 0.5)
            cr.set_line_width(px(4.5))
            cr.set_source_rgba(*style.text, 0.18)
            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.stroke()
            frac = max(0.0, min(1.0, frac))
            if frac > 0:
                if hot:
                    cr.set_source_rgba(*style.hot, 0.95)
                else:
                    set_accent_source(cr, style, cx - radius, cx + radius)
                cr.arc(cx, cy, radius, -math.pi / 2, -math.pi / 2 + 2 * math.pi * frac)
                cr.stroke()
            value = text.replace("°C", "°")                  # no room for the unit inside a ring
            value_font = style.ui(10, "Medium")
            draw_text(cr, value, value_font, cx, cy - measure_text(value, value_font)[1] / 2,
                      style.hot if hot else style.text, align="center", shadow=self.bare)
            draw_text(cr, style.label(label), style.ui(9), cx, px(84), style.text, alpha=0.70,
                      spacing=style.label_spacing, align="center", shadow=self.bare)


class SystemLine(System):
    """One line: CPU 3%  RAM 51%  Temp 62°C. Small and out of the way."""

    design = "line"

    def draw(self, cr) -> None:
        style, px = self.style, self.style.px
        self.draw_card(cr)
        label_font, value_font = style.ui(9), style.ui(11, "Medium")
        text_h = measure_text("0", value_font)[1]
        y = (self.height - text_h) / 2
        for index, (label, _frac, text, hot) in enumerate(self.readings()):
            x = px(14) + px(98) * index
            w, _ = draw_text(cr, style.label(label), label_font, x, y + px(2), style.text, alpha=0.62,
                             spacing=style.label_spacing, shadow=self.bare)
            draw_text(cr, text, value_font, x + w + px(7), y, style.hot if hot else style.text,
                      shadow=self.bare)


DESIGNS = {"bars": System, "rings": SystemRings, "line": SystemLine}
