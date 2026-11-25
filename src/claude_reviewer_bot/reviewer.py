"""Motores de revisión (Strategy). Hoy: Claude Code CLI; se puede cambiar por otro."""

import os
from pathlib import Path
from typing import Protocol

from .models import COMMAND
from .shell import run

READ_ONLY_TOOLS = "Read,Grep,Glob"
SECRET_ENV = ("GH_TOKEN", "GITHUB_TOKEN")


class Reviewer(Protocol):
    def review(self, prompt: str, cwd: Path) -> str: ...


class ClaudeCliReviewer:
    def __init__(self, model: str = "", timeout: int = 900):
        self.model = model
        self.timeout = timeout

    def _command(self) -> list[str]:
        cmd = ["claude", "-p", "--allowedTools", READ_ONLY_TOOLS]
        return cmd + ["--model", self.model] if self.model else cmd

    def review(self, prompt: str, cwd: Path) -> str:
        # Sin tokens de GitHub en el entorno de Claude.
        env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
        out = run(self._command(), input=prompt, cwd=cwd, timeout=self.timeout, env=env).strip()
        if not out:
            raise RuntimeError("claude devolvió una respuesta vacía")
        # Evita que el bot se dispare a sí mismo.
        return out.replace(COMMAND, f"`{COMMAND.lstrip('/')}`")
