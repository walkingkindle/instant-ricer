"""System widget: a card of thin bars for CPU, memory, temperatures and battery."""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

from ricer.widgets.drawing import draw_bar, draw_card, draw_text
from ricer.widgets.style import Style

CPU_SENSORS = ("coretemp", "k10temp", "zenpower")   # hwmon driver names for CPU temperature
GPU_SENSORS = ("amdgpu", "nouveau")                 # GPUs that report through hwmon
TEMP_RANGE = (30, 100)               # °C mapped to an empty / full temperature bar
TEMP_HOT = 85                        # °C at which a reading turns red
GPU_POLL_TICKS = 6                   # asking nvidia-smi is slow-ish, so do it less often
LABELS = {"cpu": "CPU", "ram": "RAM", "temp": "TEMP", "gpu": "GPU", "battery": "BAT"}


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


class System:
    clickable = False
    WIDTH = 260

    def __init__(self, style: Style, options: dict, root: Path = Path("/")):
        self.style = style
        self.root = root
        self.cpu = 0.0
        self.gpu = None
        self._times = read_cpu_times(root)
        wanted = options.get("rows", ["cpu", "ram"])
        if "gpu" in wanted:
            self.gpu = gpu_temperature(root)
        # a row whose sensor this machine lacks is dropped rather than shown empty
        self.rows = [row for row in wanted if self.reading(row) is not None]
        self.width = math.ceil(style.px(self.WIDTH))
        self.height = math.ceil(style.px(36 + 32 * len(self.rows)))

    def reading(self, row: str):
        """(bar fraction, label text, is hot) for a row, or None if it cannot be read."""
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

    def tick(self, count: int) -> bool:
        if count % 2:
            return False
        now = read_cpu_times(self.root)
        self.cpu, self._times = cpu_usage(self._times, now), now
        if "gpu" in self.rows and count % GPU_POLL_TICKS == 0:
            self.gpu = gpu_temperature(self.root)
        return True

    def draw(self, cr) -> None:
        style = self.style
        draw_card(cr, style, self.width, self.height)
        pad, step = style.px(18), style.px(32)
        small = style.font_desc(9)
        for index, row in enumerate(self.rows):
            reading = self.reading(row)
            if reading is None:
                continue
            frac, text, hot = reading
            y = pad + step * index + step / 2
            draw_text(cr, LABELS[row], small, pad, y - style.px(8), style.text, alpha=0.70,
                      spacing=2)
            draw_text(cr, text, small, self.width - pad, y - style.px(8),
                      style.hot if hot else style.text, alpha=0.90, align="right")
            draw_bar(cr, style, pad + style.px(46), y, self.width - 2 * pad - style.px(90), frac,
                     line_width=style.px(4))
