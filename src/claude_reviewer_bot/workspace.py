"""Worktree temporal de git con el código exacto del PR."""

import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .shell import run


@contextmanager
def pr_worktree(clone: Path, number: int, sha: str, work_dir: Path) -> Iterator[Path]:
    """Hace fetch de ``pull/N/head``, crea un worktree en ``sha`` y lo elimina al salir."""
    run(["git", "-C", str(clone), "fetch", "origin", f"pull/{number}/head"], timeout=300)
    work_dir.mkdir(parents=True, exist_ok=True)
    wt = Path(tempfile.mkdtemp(prefix=f"pr{number}-", dir=work_dir))
    try:
        run(["git", "-C", str(clone), "worktree", "add", "--detach", str(wt), sha], timeout=120)
        yield wt
    finally:
        subprocess.run(
            ["git", "-C", str(clone), "worktree", "remove", "--force", str(wt)], capture_output=True
        )
        shutil.rmtree(wt, ignore_errors=True)
