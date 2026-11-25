"""Pruebas del CLI con subcomandos y del cálculo de ``since``.

Contrato esperado (aún no implementado):
- Subcomandos: ``run`` (por defecto), ``doctor`` e ``init``. El bot se ejecuta a mano (sin timer).
- ``claude-review`` sin subcomando sigue funcionando igual que hoy (equivale a ``run``).
- ``--config`` se acepta en todos los subcomandos.
- La lógica del ciclo se mueve de ``cli.py`` a ``runner.py``.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from claude_reviewer_bot import cli
from claude_reviewer_bot.runner import resolve_since
from claude_reviewer_bot.state import State

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


# ---------- compatibilidad: sin subcomando = run ----------
@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], ["run"]),
        (["--dry-run"], ["run", "--dry-run"]),
        (["--since", "2026-01-01T00:00:00Z"], ["run", "--since", "2026-01-01T00:00:00Z"]),
        (["--config", "/x.toml"], ["run", "--config", "/x.toml"]),
        (["run", "--dry-run"], ["run", "--dry-run"]),
        (["doctor"], ["doctor"]),
        (["-h"], ["-h"]),
    ],
)
def test_normalize_argv(argv, expected):
    assert cli.normalize_argv(argv) == expected


# ---------- parseo ----------
def test_parse_run_defaults():
    args = cli.parse_args([])
    assert (args.command, args.dry_run, args.since, args.config) == ("run", False, None, None)


def test_parse_init_options():
    args = cli.parse_args(
        ["init", "--repo", "o/r=~/a", "--repo", "o/s=~/b", "--allowed-user", "x", "--force"]
    )
    assert args.repos == ["o/r=~/a", "o/s=~/b"]
    assert (args.allowed_user, args.force) == ("x", True)


@pytest.mark.parametrize("command", [["run"], ["doctor"], ["init"]])
def test_config_accepted_on_every_command(command):
    assert cli.parse_args([*command, "--config", "/x.toml"]).config == Path("/x.toml")


# ---------- runner.resolve_since ----------
def test_resolve_since_prefers_explicit():
    state = State(last_check=NOW)
    assert resolve_since("2026-01-01T00:00:00Z", state, NOW) == "2026-01-01T00:00:00Z"


def test_resolve_since_uses_last_check_minus_overlap():
    assert resolve_since(None, State(last_check=NOW), NOW) == "2026-11-25T11:58:00Z"


def test_resolve_since_first_run_uses_now():
    assert resolve_since(None, State(), NOW) == "2026-11-25T12:00:00Z"
