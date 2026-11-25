"""Detecta comentarios ``/claude-review`` nuevos y los convierte en :class:`Job`."""

import re

from .config import Config
from .github import GitHubClient
from .models import COMMAND, MARKER, CommentKind, Job

# El comando solo cuenta al inicio de una línea (las citas con ">" quedan fuera).
CMD_RE = re.compile(rf"^[ \t]*{re.escape(COMMAND)}\b[ \t]*(.*)$", re.M)


def parse_command(body: str) -> str | None:
    """Devuelve la instrucción extra (posiblemente vacía) o ``None`` si no hay comando."""
    m = CMD_RE.search(body)
    return m.group(1).strip() if m else None


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

    def _is_allowed(self, comment: dict) -> bool:
        login = (comment.get("user") or {}).get("login", "")
        return login.lower() == self.cfg.allowed_user.lower()

    def _to_job(self, repo: str, kind: CommentKind, c: dict, known: set[str]) -> Job | None:
        key = f"{repo}:{kind.value}:{c['id']}"
        body = c.get("body") or ""
        if key in known or MARKER in body or not self._is_allowed(c):
            return None
        extra = parse_command(body)
        if extra is None:
            return None
        n = int(c[kind.url_field].rsplit("/", 1)[1])
        return Job(key=key, repo=repo, kind=kind, cid=c["id"], n=n, extra=extra)
