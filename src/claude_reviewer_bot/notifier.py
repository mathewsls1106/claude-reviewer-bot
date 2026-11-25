"""Notificaciones de escritorio (opcionales)."""

import shutil
import subprocess
from typing import Protocol


class Notifier(Protocol):
    def notify(self, title: str, body: str) -> None: ...


class DesktopNotifier:
    def notify(self, title: str, body: str) -> None:
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", title, body], check=False)


class NullNotifier:
    def notify(self, title: str, body: str) -> None:
        pass
