"""Start and stop the widget daemon process."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from ricer.paths import Paths

DAEMON_MODULE = "ricer.widgets.daemon"


def process_is_daemon(pid: int) -> bool:
    try:
        return DAEMON_MODULE.encode() in Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False


class DaemonControl:
    def __init__(self, paths: Paths):
        self.paths = paths

    def running_pid(self) -> int | None:
        try:
            pid = int(self.paths.pid_file.read_text())
        except (OSError, ValueError):
            return None
        return pid if process_is_daemon(pid) else None

    def start(self) -> bool:
        """Start the daemon unless it already runs. Returns True if it was started."""
        if self.running_pid():
            return False
        self.paths.cache.mkdir(parents=True, exist_ok=True)
        with open(self.paths.log_file, "ab") as log:
            subprocess.Popen([sys.executable, "-m", DAEMON_MODULE], stdin=subprocess.DEVNULL,
                             stdout=log, stderr=log, start_new_session=True)
        return True

    def stop(self) -> bool:
        pid = self.running_pid()
        if not pid:
            return False
        os.kill(pid, signal.SIGTERM)
        return True

    def wanted(self) -> bool:
        try:
            return bool(json.loads(self.paths.widgets_file.read_text()).get("widgets"))
        except (OSError, ValueError):
            return False

    def sync(self) -> None:
        """Run the daemon exactly when the config asks for widgets. It reloads config itself."""
        if self.wanted():
            self.start()
        else:
            self.stop()
