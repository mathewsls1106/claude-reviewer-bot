"""Pruebas del modo periódico ``claude-review watch``.

Contrato esperado (aún no implementado):
- ``watch`` es un subcomando que repite una pasada (``run_once``) cada ``interval`` segundos dentro de
  un único proceso, sin cron ni systemd. Entre pasadas el proceso queda bloqueado en
  ``threading.Event.wait`` (cero CPU, sin hilos extra ni sondeo activo).
- El intervalo sale de ``poll_interval_seconds`` del config (300 por defecto) o de ``--interval``.
  Menos de 60 s se rechaza: config inválida (``ConfigError``) o salida 2 en el CLI.
- ``watch`` no acepta ``--dry-run`` ni ``--since``: sin guardar estado revisaría lo mismo en cada vuelta.
- Cada pasada es ``run_once(cfg)`` normal: toma el lock, avanza ``last_check`` y suelta el lock al
  terminar, así que un ``claude-review run --dry-run`` puede correr mientras ``watch`` espera.
- Una pasada que lanza excepción no detiene el bucle: se registra y se espera a la siguiente.
- SIGINT/SIGTERM fijan el evento de parada: el bucle termina al acabar la pasada en curso (sale 0).
"""

import signal
import threading

import pytest

from claude_reviewer_bot import cli, runner
from claude_reviewer_bot.config import ConfigError, parse_config

CONFIG_TOML = 'allowed_user = "a"\n[repos]\n"o/r" = "/tmp/clone"\n'


class FakeStop:
    """Sustituye a ``threading.Event``: registra las esperas y pide parar tras ``stop_after``."""

    def __init__(self, stop_after: int, already_set: bool = False):
        self.stop_after, self.waits, self._set = stop_after, [], already_set

    def is_set(self):
        return self._set

    def wait(self, timeout):
        self.waits.append(timeout)
        self._set = len(self.waits) >= self.stop_after
        return self._set


# ---------- runner.watch: bucle ----------
def test_watch_runs_tick_then_waits_interval_until_stopped():
    ticks = []
    stop = FakeStop(stop_after=3)
    cycles = runner.watch(lambda: ticks.append(1), 300, stop)
    assert cycles == 3 and len(ticks) == 3
    assert stop.waits == [300, 300, 300]


def test_watch_does_nothing_if_already_stopped():
    ticks = []
    assert runner.watch(lambda: ticks.append(1), 300, FakeStop(1, already_set=True)) == 0
    assert ticks == []


def test_watch_survives_failing_tick(capsys):
    calls = []

    def tick():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")

    assert runner.watch(tick, 60, FakeStop(stop_after=2)) == 2
    assert "boom" in capsys.readouterr().out


# ---------- runner.run_forever: armado ----------
def test_run_forever_calls_run_once_without_since_nor_dry_run(monkeypatch):
    stop = threading.Event()
    calls = []

    def fake_run_once(cfg, since=None, dry_run=False):
        calls.append((cfg, since, dry_run))
        stop.set()  # para el bucle tras la primera pasada
        return 0

    monkeypatch.setattr(runner, "run_once", fake_run_once)
    cfg = parse_config({"allowed_user": "a", "repos": {"o/r": "/tmp/clone"}})
    assert runner.run_forever(cfg, 60, stop) == 0
    assert calls == [(cfg, None, False)]


def test_stop_signals_set_event():
    stop = threading.Event()
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        runner.install_stop_signals(stop)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert stop.is_set()
        stop.clear()
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
        assert stop.is_set()
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


# ---------- config ----------
def test_poll_interval_default():
    cfg = parse_config({"allowed_user": "a", "repos": {"o/r": "/x"}})
    assert cfg.poll_interval_seconds == 300


def test_poll_interval_too_small_is_invalid():
    with pytest.raises(ConfigError):
        parse_config({"allowed_user": "a", "repos": {"o/r": "/x"}, "poll_interval_seconds": 59})


# ---------- CLI ----------
def test_normalize_argv_keeps_watch():
    assert cli.normalize_argv(["watch", "--interval", "120"]) == ["watch", "--interval", "120"]


def test_parse_watch_defaults_and_options(tmp_path):
    args = cli.parse_args(["watch"])
    assert (args.command, args.interval, args.config) == ("watch", None, None)
    args = cli.parse_args(["watch", "--interval", "120", "--config", str(tmp_path / "c.toml")])
    assert args.interval == 120 and args.config == tmp_path / "c.toml"


@pytest.mark.parametrize("flag", [["--dry-run"], ["--since", "2026-01-01T00:00:00Z"]])
def test_watch_rejects_run_only_flags(flag):
    with pytest.raises(SystemExit):
        cli.parse_args(["watch", *flag])


@pytest.mark.parametrize(("argv", "expected"), [([], 300), (["--interval", "90"], 90)])
def test_cmd_watch_resolves_interval(tmp_path, monkeypatch, argv, expected):
    conf = tmp_path / "c.toml"
    conf.write_text(CONFIG_TOML)
    seen = []
    monkeypatch.setattr(cli, "run_forever", lambda cfg, interval: seen.append(interval) or 0)
    assert cli.main(["watch", "--config", str(conf), *argv]) == 0
    assert seen == [expected]


def test_cmd_watch_rejects_small_interval(tmp_path, monkeypatch):
    conf = tmp_path / "c.toml"
    conf.write_text(CONFIG_TOML)
    monkeypatch.setattr(cli, "run_forever", lambda cfg, interval: pytest.fail("no debía arrancar"))
    assert cli.main(["watch", "--config", str(conf), "--interval", "30"]) == 2
