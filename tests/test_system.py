import subprocess

import pytest

pytest.importorskip("gi")

from ricer.widgets import system  # noqa: E402  (needs GTK's cairo bindings)


@pytest.fixture
def root(tmp_path):
    """A fake / with just enough of /proc and /sys."""
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc/stat").write_text("cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 1 2 3 4\n")
    (tmp_path / "proc/meminfo").write_text("MemTotal: 16000 kB\nMemFree: 1000 kB\nMemAvailable: 4000 kB\n")
    for index, (name, milli) in enumerate([("nvme", 41000), ("coretemp", 62000), ("amdgpu", 55000)]):
        hwmon = tmp_path / f"sys/class/hwmon/hwmon{index}"
        hwmon.mkdir(parents=True)
        (hwmon / "name").write_text(name + "\n")
        (hwmon / "temp1_input").write_text(f"{milli}\n")
    battery = tmp_path / "sys/class/power_supply/BAT0"
    battery.mkdir(parents=True)
    (battery / "capacity").write_text("87\n")
    return tmp_path


def test_cpu_usage_between_two_samples(root):
    before = system.read_cpu_times(root)
    assert before == (800, 1000)
    assert system.cpu_usage(before, (850, 1100)) == pytest.approx(0.5)
    assert system.cpu_usage(before, before) == 0.0


def test_memory_temperature_and_battery(root):
    assert system.memory_usage(root) == pytest.approx(0.75)
    assert system.cpu_temperature(root) == 62.0
    assert system.battery_level(root) == pytest.approx(0.87)


def test_missing_sensors_read_as_none(tmp_path):
    assert system.cpu_temperature(tmp_path) is None
    assert system.battery_level(tmp_path) is None
    assert system.gpu_temperature(tmp_path, which=lambda _: None) is None


def test_gpu_temperature_prefers_nvidia_smi_then_hwmon(root):
    def nvidia(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, stdout="71\n")

    assert system.gpu_temperature(root, which=lambda _: "/usr/bin/nvidia-smi", run=nvidia) == 71.0
    assert system.gpu_temperature(root, which=lambda _: None) == 55.0

    def broken(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", 2)

    assert system.gpu_temperature(root, which=lambda _: "/usr/bin/nvidia-smi", run=broken) is None


def test_temperature_fraction_spans_the_bar():
    assert system.temperature_fraction(30) == 0 and system.temperature_fraction(100) == 1
