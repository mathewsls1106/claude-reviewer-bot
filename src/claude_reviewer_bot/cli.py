"""CLI ``claude-review``.

    claude-review [run] [--dry-run] [--since ISO]   una pasada (por defecto)
    claude-review doctor                            diagnostica el entorno
    claude-review init [--repo o/r=RUTA ...]        crea config y estado inicial

Todos aceptan ``--config RUTA`` (o la variable ``CLAUDE_REVIEW_CONFIG``).
"""

import argparse
import sys
from pathlib import Path

from .admin import doctor, init
from .config import ConfigError, config_path, load_config
from .runner import run_once
from .shell import log

COMMANDS = ("run", "doctor", "init")
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

    sub.add_parser("doctor", parents=[common], help="diagnostica herramientas, sesiones, config y repos")

    ini = sub.add_parser("init", parents=[common], help="crea el config y el estado inicial")
    ini.add_argument("--repo", dest="repos", action="append", metavar="OWNER/REPO=RUTA", help="repetible")
    ini.add_argument("--allowed-user", help="por defecto, el usuario logueado en gh")
    ini.add_argument("--force", action="store_true", help="sobrescribe un config existente")
    return ap


def parse_args(argv: list[str]) -> argparse.Namespace:
    return build_parser().parse_args(normalize_argv(argv))


# ---------- comandos ----------
def cmd_run(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        log(f"configuración inválida: {e} (prueba `claude-review doctor`)")
        return 2
    return run_once(cfg, args.since, args.dry_run)


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


HANDLERS = {"run": cmd_run, "doctor": cmd_doctor, "init": cmd_init}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return HANDLERS[args.command](args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        log(f"error fatal: {exc}")
        return 1
