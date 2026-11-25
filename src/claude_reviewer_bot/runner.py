"""Una pasada del bot: buscar comentarios nuevos, procesarlos y guardar el estado."""

from datetime import UTC, datetime, timedelta

from .config import Config
from .github import GitHubClient
from .models import Outcome
from .notifier import DesktopNotifier
from .reviewer import ClaudeCliReviewer
from .scanner import CommentScanner
from .service import ReviewService
from .shell import log
from .state import State, StateStore

OVERLAP = timedelta(minutes=2)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_since(explicit: str | None, state: State, now: datetime) -> str:
    if explicit:
        return explicit
    if state.last_check:
        return iso(state.last_check - OVERLAP)
    log("primera ejecución: se vigilarán comentarios desde ahora (usa `claude-review init` para evitarlo)")
    return iso(now)


def run_cycle(
    store: StateStore, scanner: CommentScanner, service: ReviewService, since: str | None, dry_run: bool
):
    state = store.load()
    started = datetime.now(UTC)
    try:
        new_jobs = scanner.scan(resolve_since(since, state, started), state.known_keys())
    except Exception as e:  # noqa: BLE001
        log(f"no se pudo consultar GitHub: {e}")
        return  # no avanza last_check: se reintenta en la próxima ejecución

    pending = []
    for job in state.pending + new_jobs:
        match service.process(job):
            case Outcome.DONE:
                state.done.append(job.key)
            case Outcome.RETRY:
                pending.append(job)

    if not dry_run:
        state.pending = pending
        state.last_check = started
        store.save(state)


def run_once(cfg: Config, since: str | None = None, dry_run: bool = False) -> int:
    store = StateStore(cfg.state_dir)
    gh = GitHubClient()
    reviewer = ClaudeCliReviewer(cfg.model, cfg.timeout_seconds)
    service = ReviewService(cfg, gh, reviewer, DesktopNotifier(), dry_run)
    with store.exclusive() as acquired:
        if not acquired:
            log("otra ejecución está en curso; salgo")
            return 0
        run_cycle(store, CommentScanner(cfg, gh), service, since, dry_run)
    return 0
