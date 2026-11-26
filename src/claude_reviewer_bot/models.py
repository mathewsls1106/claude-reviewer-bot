"""Modelos de dominio."""

from dataclasses import asdict, dataclass
from enum import Enum, StrEnum
from typing import Any

COMMAND = "/claude-review"
MARKER = "<!-- claude-review -->"

JsonDict = dict[str, Any]  # objeto JSON tal como lo devuelve la API de GitHub


class CommentKind(StrEnum):
    ISSUE = "i"  # comentario en la conversación del PR
    REVIEW = "r"  # comentario en una línea del diff

    @property
    def api_path(self) -> str:
        return "issues" if self is CommentKind.ISSUE else "pulls"

    @property
    def url_field(self) -> str:
        return "issue_url" if self is CommentKind.ISSUE else "pull_request_url"


@dataclass
class Job:
    """Una petición de revisión pendiente (persistible en el estado)."""

    key: str
    repo: str
    kind: CommentKind
    cid: int
    n: int
    extra: str = ""
    attempts: int = 0

    def to_dict(self) -> JsonDict:
        return asdict(self) | {"kind": self.kind.value}

    @classmethod
    def from_dict(cls, d: JsonDict) -> "Job":
        return cls(**(d | {"kind": CommentKind(d["kind"])}))


@dataclass(frozen=True)
class PullRequest:
    repo: str
    number: int
    title: str
    body: str
    state: str
    head_sha: str
    head_repo: str | None  # None si el fork fue borrado
    changed_files: int

    @classmethod
    def from_api(cls, repo: str, d: JsonDict) -> "PullRequest":
        head_repo = d["head"]["repo"]
        return cls(
            repo=repo,
            number=d["number"],
            title=d["title"],
            body=d.get("body") or "",
            state=d["state"],
            head_sha=d["head"]["sha"],
            head_repo=head_repo["full_name"] if head_repo else None,
            changed_files=d["changed_files"],
        )

    @property
    def is_fork(self) -> bool:
        return self.head_repo is None or self.head_repo.lower() != self.repo.lower()


class Outcome(Enum):
    DONE = "done"  # terminado (publicado, omitido o descartado): no reintentar
    RETRY = "retry"  # falló, se reintenta en la próxima ejecución
    DRY = "dry"  # dry-run: no se toca el estado
