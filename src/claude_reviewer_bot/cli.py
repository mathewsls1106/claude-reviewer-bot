"""Punto de entrada: ``claude-review [--dry-run] [--since ISO] [--config RUTA]``.

Pensado para ejecutarse periódicamente (cron / systemd timer).
"""

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import ConfigError, load_config
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


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="claude-review", description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="imprime la revisión, no publica ni guarda estado")
    ap.add_argument("--since", help="ISO8601 UTC (ej. 2026-11-25T10:00:00Z) para forzar desde cuándo mirar")
    ap.add_argument("--config", type=Path, help="ruta del config.toml (o env CLAUDE_REVIEW_CONFIG)")
    return ap.parse_args(argv)


def resolve_since(explicit: str | None, state: State, now: datetime) -> str:
    if explicit:
        return explicit
    if state.last_check:
        return iso(state.last_check - OVERLAP)
    log("primera ejecución: se vigilarán comentarios desde ahora")
    return iso(now)


def run_cycle(args: argparse.Namespace, store: StateStore, scanner: CommentScanner, service: ReviewService):
    state = store.load()
    started = datetime.now(UTC)
    try:
        new_jobs = scanner.scan(resolve_since(args.since, state, started), state.known_keys())
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

    if not args.dry_run:
        state.pending = pending
        state.last_check = started
        store.save(state)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        log(f"configuración inválida: {e}")
        return 2

    store = StateStore(cfg.state_dir)
    gh = GitHubClient()
    service = ReviewService(
        cfg, gh, ClaudeCliReviewer(cfg.model, cfg.timeout_seconds), DesktopNotifier(), args.dry_run
    )
    try:
        with store.exclusive() as acquired:
            if not acquired:
                log("otra ejecución está en curso; salgo")
                return 0
            run_cycle(args, store, CommentScanner(cfg, gh), service)
    except Exception as exc:  # noqa: BLE001
        log(f"error fatal: {exc}")
        return 1
    return 0
