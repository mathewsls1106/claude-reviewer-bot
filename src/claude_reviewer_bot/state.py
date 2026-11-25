"""Persistencia del estado (Repository) y lock de ejecución única."""

import fcntl
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .models import Job

MAX_DONE = 1000


@dataclass
class State:
    last_check: datetime | None = None
    done: list[str] = field(default_factory=list)
    pending: list[Job] = field(default_factory=list)

    def known_keys(self) -> set[str]:
        return set(self.done) | {j.key for j in self.pending}


class StateStore:
    def __init__(self, state_dir: Path):
        self.dir = state_dir
        self.file = state_dir / "state.json"

    def load(self) -> State:
        if not self.file.exists():
            return State()
        raw = json.loads(self.file.read_text())
        last = raw.get("last_check")
        return State(
            last_check=datetime.fromisoformat(last) if last else None,
            done=raw.get("done", []),
            pending=[Job.from_dict(j) for j in raw.get("pending", [])],
        )

    def save(self, state: State) -> None:
        data = {
            "last_check": state.last_check.isoformat() if state.last_check else None,
            "done": state.done[-MAX_DONE:],
            "pending": [j.to_dict() for j in state.pending],
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.file)  # escritura atómica

    @contextmanager
    def exclusive(self):
        """Lock no bloqueante. Produce ``True`` si se obtuvo, ``False`` si otra instancia corre."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / "lock", "w") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            yield True
