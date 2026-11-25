"""Orquesta la revisión de un job: validar → preparar worktree → revisar → publicar."""

from dataclasses import dataclass

from . import guards
from .config import Config
from .github import GitHubClient, NotAPullRequest
from .guards import Skip
from .models import MARKER, Job, Outcome, PullRequest
from .notifier import Notifier
from .prompt import build_prompt, load_template
from .reviewer import Reviewer
from .shell import log
from .workspace import pr_worktree


def wrap(body: str, sha: str | None = None) -> str:
    foot = f"\n\n---\n<sub>Commit revisado: `{sha[:7]}`</sub>" if sha else ""
    return f"{MARKER}\n### 🤖 Revisión automática de Claude\n\n{body}{foot}"


@dataclass(frozen=True)
class Review:
    pr: PullRequest
    comment: str


class ReviewService:
    def __init__(self, cfg: Config, gh: GitHubClient, reviewer: Reviewer, notifier: Notifier, dry_run=False):
        self.cfg = cfg
        self.gh = gh
        self.reviewer = reviewer
        self.notifier = notifier
        self.dry_run = dry_run

    # ---------- API pública ----------
    def process(self, job: Job) -> Outcome:
        log(f"revisando {job.repo}#{job.n} (intento {job.attempts + 1})")
        self._publish(self.gh.react, job)
        try:
            review = self.review(job)
        except NotAPullRequest:
            log("omitido: el comentario es de un issue, no de un PR")
            return Outcome.DONE
        except Skip as s:
            log(f"omitido: {s}")
            self._publish(self.gh.comment, job.repo, job.n, wrap(f"⚠️ No se hizo la revisión: {s}"))
            return Outcome.DONE
        except Exception as e:  # noqa: BLE001 - cualquier fallo es reintentable
            return self._on_failure(job, e)
        return self._deliver(job, review)

    def review(self, job: Job) -> Review:
        pr = self.gh.pull_request(job.repo, job.n)
        guards.enforce(guards.PR_RULES, pr, self.cfg)
        diff = self.gh.diff(pr)
        guards.enforce(guards.DIFF_RULES, diff, self.cfg)

        template = load_template(self.cfg.template_for(job.repo))
        prompt = build_prompt(template, pr, diff, job.extra, self.cfg.max_words)
        clone = self.cfg.repos[job.repo].clone_path
        with pr_worktree(clone, pr.number, pr.head_sha, self.cfg.state_dir / "worktrees") as wt:
            text = self.reviewer.review(prompt, wt)
        return Review(pr, wrap(text, pr.head_sha))

    # ---------- internos ----------
    def _publish(self, action, *args) -> None:
        """Ejecuta efectos visibles en GitHub salvo en dry-run."""
        if not self.dry_run:
            action(*args)

    def _on_failure(self, job: Job, err: Exception) -> Outcome:
        job.attempts += 1
        log(f"error: {err}")
        if job.attempts < self.cfg.max_attempts:
            return Outcome.RETRY
        msg = f"❌ La revisión falló {job.attempts} veces. Último error: `{str(err)[:300]}`"
        self._publish(self.gh.comment, job.repo, job.n, wrap(msg))
        return Outcome.DONE  # se descarta tras agotar reintentos

    def _deliver(self, job: Job, review: Review) -> Outcome:
        if self.dry_run:
            print(f"\n{'=' * 70}\n{review.comment}\n{'=' * 70}")
            return Outcome.DRY
        self.gh.comment(job.repo, job.n, review.comment)
        self.notifier.notify("Revisión de PR lista", f"{job.repo}#{job.n}: {review.pr.title}")
        return Outcome.DONE
