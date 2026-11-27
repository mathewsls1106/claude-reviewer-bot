"""Detecta comentarios ``/claude-review`` y ``/claude-summary`` nuevos y los convierte en :class:`Job`."""

import re

from .config import Config
from .github import GitHubClient
from .models import COMMANDS, MARKER, CommentKind, Job, JsonDict, Mode

# El comando solo cuenta al inicio de una línea (las citas con ">" quedan fuera).
_ALTERNATIVES = "|".join(re.escape(c) for c in COMMANDS)
CMD_RE = re.compile(rf"^[ \t]*({_ALTERNATIVES})\b[ \t]*(.*)$", re.M)
_MODE_BY_COMMAND = {m.command: m for m in Mode}


def parse_command(body: str) -> tuple[Mode, str] | None:
    """Devuelve ``(modo, instrucción extra)`` del primer comando o ``None`` si no hay ninguno."""
    m = CMD_RE.search(body)
    return (_MODE_BY_COMMAND[m.group(1)], m.group(2).strip()) if m else None


class CommentScanner:
    def __init__(self, cfg: Config, gh: GitHubClient):
        self.cfg = cfg
        self.gh = gh

    def scan(self, since: str, known: set[str]) -> list[Job]:
        return [
            job
            for repo in self.cfg.repos
            for kind in CommentKind
            for c in self.gh.comments_since(repo, kind, since)
            if (job := self._to_job(repo, kind, c, known))
        ]

    def _is_allowed(self, comment: JsonDict) -> bool:
        login = str((comment.get("user") or {}).get("login", ""))
        return login.lower() == self.cfg.allowed_user.lower()

    def _to_job(self, repo: str, kind: CommentKind, c: JsonDict, known: set[str]) -> Job | None:
        key = f"{repo}:{kind.value}:{c['id']}"
        body = c.get("body") or ""
        if key in known or MARKER in body or not self._is_allowed(c):
            return None
        parsed = parse_command(body)
        if parsed is None:
            return None
        mode, extra = parsed
        n = int(c[kind.url_field].rsplit("/", 1)[1])
        return Job(key=key, repo=repo, kind=kind, cid=c["id"], n=n, extra=extra, mode=mode)
