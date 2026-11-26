"""Pasadas del bot (buscar comentarios nuevos, procesarlos, guardar el estado) y el bucle periódico."""

import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import FrameType
from typing import Protocol

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
) -> None:
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


# ---------- modo periódico ----------
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)


class Stopper(Protocol):
    """Lo que ``watch`` necesita de ``threading.Event`` (permite simularlo en tests)."""

    def is_set(self) -> bool: ...

    def wait(self, timeout: float | None = None) -> bool: ...


def watch(tick: Callable[[], object], interval: float, stop: Stopper) -> int:
    """Ejecuta ``tick`` y duerme ``interval`` s hasta que ``stop`` se active. Devuelve las pasadas hechas.

    La espera es ``Event.wait``: el proceso queda bloqueado sin consumir CPU ni sondear.
    """
    cycles = 0
    while not stop.is_set():
        try:
            tick()
        except Exception as e:  # noqa: BLE001
            log(f"la pasada falló, se reintenta en la siguiente: {e}")
        cycles += 1
        if stop.wait(interval):
            break
    return cycles


def install_stop_signals(stop: threading.Event) -> None:
    """SIGINT/SIGTERM piden parar: el bucle termina al acabar la pasada en curso."""

    def handler(signum: int, frame: FrameType | None) -> None:
        log(f"señal {signal.Signals(signum).name}: se detiene al terminar la pasada en curso")
        stop.set()

    for sig in STOP_SIGNALS:
        signal.signal(sig, handler)


@contextmanager
def stop_signals(stop: threading.Event) -> Iterator[None]:
    """Instala los manejadores de parada y restaura los anteriores al salir."""
    previous = {sig: signal.getsignal(sig) for sig in STOP_SIGNALS}
    install_stop_signals(stop)
    try:
        yield
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


def run_forever(cfg: Config, interval: float, stop: threading.Event | None = None) -> int:
    stop = stop or threading.Event()
    log(f"modo periódico: una pasada cada {interval:g} s (Ctrl+C o SIGTERM para detener)")
    with stop_signals(stop):
        cycles = watch(lambda: run_once(cfg), interval, stop)
    log(f"modo periódico detenido tras {cycles} pasada(s)")
    return 0
