"""Utilidades de bajo nivel: logging y ejecución de procesos."""

import subprocess
from datetime import datetime
from pathlib import Path


class CommandError(RuntimeError):
    """Un comando externo terminó con código distinto de cero."""


def log(msg: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


def run(
    cmd: list[str],
    *,
    input: str | None = None,
    cwd: Path | None = None,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Ejecuta ``cmd`` y devuelve stdout; lanza :class:`CommandError` si falla."""
    r = subprocess.run(cmd, input=input, cwd=cwd, timeout=timeout, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise CommandError(f"{' '.join(map(str, cmd[:4]))}... falló: {r.stderr.strip()[:500]}")
    return r.stdout
