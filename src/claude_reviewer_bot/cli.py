"""CLI ``claude-review``.

    claude-review watch [--interval N]              modo de operación: una pasada cada N s
    claude-review [run] [--dry-run] [--since ISO]   una pasada (por defecto; para probar con --dry-run)
    claude-review doctor                            diagnostica el entorno
    claude-review init [--repo o/r=RUTA ...]        crea config y estado inicial

Todos aceptan ``--config RUTA`` (o la variable ``CLAUDE_REVIEW_CONFIG``).
"""

import argparse
import sys
from pathlib import Path

from .admin import doctor, init
from .config import MIN_POLL_INTERVAL, Config, ConfigError, config_path, load_config
from .runner import run_forever, run_once
from .shell import log

COMMANDS = ("watch", "run", "doctor", "init")
HELP_FLAGS = ("-h", "--help")


def normalize_argv(argv: list[str]) -> list[str]:
    """Sin subcomando equivale a ``run`` (compatibilidad con ``claude-review --dry-run``)."""
    if argv and (argv[0] in COMMANDS or argv[0] in HELP_FLAGS):
        return argv
    return ["run", *argv]


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, help="ruta del config.toml (o env CLAUDE_REVIEW_CONFIG)")

    ap = argparse.ArgumentParser(
        prog="claude-review", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", parents=[common], help="una pasada: busca comentarios y revisa")
    run.add_argument(
        "--dry-run", action="store_true", help="imprime la revisión, no publica ni guarda estado"
    )
    run.add_argument("--since", help="ISO8601 UTC (ej. 2026-11-25T10:00:00Z) para forzar desde cuándo mirar")

    watch = sub.add_parser("watch", parents=[common], help="proceso periódico: una pasada cada N segundos")
    watch.add_argument(
        "--interval", type=int, help="segundos entre pasadas (por defecto poll_interval_seconds del config)"
    )

    sub.add_parser("doctor", parents=[common], help="diagnostica herramientas, sesiones, config y repos")

    ini = sub.add_parser("init", parents=[common], help="crea el config y el estado inicial")
    ini.add_argument("--repo", dest="repos", action="append", metavar="OWNER/REPO=RUTA", help="repetible")
    ini.add_argument("--allowed-user", help="por defecto, el usuario logueado en gh")
    ini.add_argument("--force", action="store_true", help="sobrescribe un config existente")
    return ap


def parse_args(argv: list[str]) -> argparse.Namespace:
    return build_parser().parse_args(normalize_argv(argv))


# ---------- comandos ----------
def _load(path: Path | None) -> Config | None:
    try:
        return load_config(path)
    except ConfigError as e:
        log(f"configuración inválida: {e} (prueba `claude-review doctor`)")
        return None


def cmd_run(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    if cfg is None:
        return 2
    return run_once(cfg, args.since, args.dry_run)


def cmd_watch(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    if cfg is None:
        return 2
    interval: int = cfg.poll_interval_seconds if args.interval is None else args.interval
    if interval < MIN_POLL_INTERVAL:
        log(f"--interval debe ser al menos {MIN_POLL_INTERVAL} s")
        return 2
    return run_forever(cfg, interval)


def cmd_doctor(args: argparse.Namespace) -> int:
    return doctor.run(args.config or config_path())


def cmd_init(args: argparse.Namespace) -> int:
    return init.run_init(
        args.config or config_path(),
        allowed_user=args.allowed_user,
        repos=args.repos,
        force=args.force,
        interactive=sys.stdin.isatty(),
    )


HANDLERS = {"watch": cmd_watch, "run": cmd_run, "doctor": cmd_doctor, "init": cmd_init}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return HANDLERS[args.command](args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        log(f"error fatal: {exc}")
        return 1
