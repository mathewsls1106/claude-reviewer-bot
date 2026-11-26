"""Fachada sobre la CLI ``gh``: lo único que sabe hablar con GitHub."""

import json
from collections.abc import Iterator

from .models import CommentKind, Job, JsonDict, PullRequest
from .shell import CommandError, log, run

GH_TIMEOUT = 90


class NotAPullRequest(Exception):
    """El número corresponde a un issue, no a un PR."""


def iter_json_values(text: str) -> Iterator[JsonDict]:
    """Recorre objetos JSON concatenados (salida de ``gh api --jq '.[]'``)."""
    dec, i = json.JSONDecoder(), 0
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            return
        obj, i = dec.raw_decode(text, i)
        yield obj


class GitHubClient:
    def _gh(self, *args: str) -> str:
        return run(["gh", *args], timeout=GH_TIMEOUT)

    def comments_since(self, repo: str, kind: CommentKind, since: str) -> Iterator[JsonDict]:
        path = f"repos/{repo}/{kind.api_path}/comments?since={since}&per_page=100"
        yield from iter_json_values(self._gh("api", "--paginate", path, "--jq", ".[]"))

    def pull_request(self, repo: str, n: int) -> PullRequest:
        try:
            data = json.loads(self._gh("api", f"repos/{repo}/pulls/{n}"))
        except CommandError as e:
            if "404" in str(e):
                raise NotAPullRequest(f"{repo}#{n}") from e
            raise
        return PullRequest.from_api(repo, data)

    def diff(self, pr: PullRequest) -> str:
        return self._gh("pr", "diff", str(pr.number), "-R", pr.repo)

    def comment(self, repo: str, n: int, body: str) -> None:
        self._gh("api", "-X", "POST", f"repos/{repo}/issues/{n}/comments", "-f", f"body={body}")

    def react(self, job: Job, content: str = "eyes") -> None:
        """Best effort: un fallo aquí no debe frenar la revisión."""
        path = f"repos/{job.repo}/{job.kind.api_path}/comments/{job.cid}/reactions"
        try:
            self._gh("api", "-X", "POST", path, "-f", f"content={content}")
        except CommandError as e:
            log(f"reacción falló (ignorado): {e}")
