"""Pruebas de los comandos de administración: doctor e init.

Contrato esperado (aún no implementado):
- ``shell.probe``: como ``run`` pero nunca lanza; devuelve ``(ok, salida)``.
- ``admin.checks``: verificaciones pequeñas que devuelven ``Check(name, status, detail, hint)``.
- ``admin.doctor``: junta los checks, los imprime y decide el código de salida.
- ``admin.init``: crea el config y el estado inicial (sin necesidad de ``--since``).

Nada de esto instala software ni programa ejecuciones: el bot se corre a mano.
"""

import json
import subprocess
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from claude_reviewer_bot.admin import checks, doctor, init
from claude_reviewer_bot.admin.checks import Check, Status
from claude_reviewer_bot.config import load_config, parse_config
from claude_reviewer_bot.shell import probe
from claude_reviewer_bot.state import State, StateStore

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def make_cfg(tmp_path, **kw):
    return parse_config(
        {
            "allowed_user": "Alice",
            "repos": {"o/r": str(tmp_path / "clone")},
            "state_dir": str(tmp_path / "state"),
            **kw,
        }
    )


def git_clone(path: Path, origin: str | None = None) -> Path:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if origin:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True)
    return path


def fake_probe(responses: dict[str, tuple[bool, str]], default=(True, "ok")):
    """Responde según el prefijo del comando (p. ej. ``"gh api user"``)."""

    def _probe(cmd, **_):
        joined = " ".join(cmd)
        for prefix, result in responses.items():
            if joined.startswith(prefix):
                return result
        return default

    return _probe


@pytest.fixture
def healthy_env(monkeypatch):
    """Entorno donde todas las herramientas existen y hay sesión en gh y claude."""
    monkeypatch.setattr(checks, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        checks,
        "probe",
        fake_probe(
            {
                "gh api user": (True, "alice"),
                "claude auth status": (True, json.dumps({"loggedIn": True})),
            }
        ),
    )


# ---------- shell.probe ----------
def test_probe_ok_strips_output():
    assert probe(["sh", "-c", "echo hola"]) == (True, "hola")


def test_probe_failure_does_not_raise():
    ok, msg = probe(["sh", "-c", "echo malo >&2; exit 3"])
    assert not ok and "malo" in msg


def test_probe_missing_binary():
    ok, msg = probe(["binario-que-no-existe-xyz"])
    assert not ok and "no está instalado" in msg


def test_probe_timeout():
    ok, _ = probe(["sleep", "5"], timeout=0.1)
    assert not ok


# ---------- checks: binarios ----------
def test_check_binaries_reports_missing_with_hint(monkeypatch):
    monkeypatch.setattr(checks, "which", lambda name: None if name == "gh" else f"/usr/bin/{name}")
    monkeypatch.setattr(checks, "probe", lambda cmd, **_: (True, f"{cmd[0]} 1.0"))
    by_name = {c.name: c for c in checks.check_binaries()}
    assert by_name["gh"].status is Status.FAIL and "cli.github.com" in by_name["gh"].hint
    assert by_name["git"].status is Status.OK and "1.0" in by_name["git"].detail
    assert by_name["claude"].status is Status.OK


# ---------- checks: sesiones ----------
def test_check_gh_auth_ok(monkeypatch):
    monkeypatch.setattr(checks, "probe", fake_probe({"gh api user": (True, "alice")}))
    check, login = checks.check_gh_auth()
    assert check.status is Status.OK and login == "alice"


def test_check_gh_auth_fail(monkeypatch):
    monkeypatch.setattr(checks, "probe", fake_probe({"gh api user": (False, "no auth")}))
    check, login = checks.check_gh_auth()
    assert check.status is Status.FAIL and "gh auth login" in check.hint and login is None


@pytest.mark.parametrize(
    ("ok", "output", "expected"),
    [
        (True, {"loggedIn": True, "loginExpiresAt": "2026-12-20T00:00:00Z"}, Status.OK),
        (True, {"loggedIn": True, "loginExpiresAt": "2026-11-26T00:00:00Z"}, Status.WARN),  # vence pronto
        (True, {"loggedIn": True}, Status.OK),
        (True, {"loggedIn": False}, Status.FAIL),
        (True, "esto no es json", Status.FAIL),
        (False, "'claude' no está instalado", Status.FAIL),
    ],
)
def test_check_claude_auth(monkeypatch, ok, output, expected):
    out = json.dumps(output) if isinstance(output, dict) else output
    monkeypatch.setattr(checks, "probe", lambda cmd, **_: (ok, out))
    check = checks.check_claude_auth(now=NOW)
    assert check.status is expected
    if expected is Status.FAIL:
        assert "claude auth login" in check.hint


# ---------- checks: repos ----------
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/O/R.git", True),
        ("https://github.com/o/r", True),
        ("git@github.com:o/r.git", True),
        ("ssh://git@github.com/o/r.git", True),
        ("https://github.com/o/r-extra.git", False),
        ("https://github.com/otro/r.git", False),
    ],
)
def test_origin_matches(url, expected):
    assert checks.origin_matches(url, "o/r") is expected


def test_check_clone_missing(tmp_path):
    assert checks.check_clone(make_cfg(tmp_path).repos["o/r"]).status is Status.FAIL


def test_check_clone_not_a_git_repo(tmp_path):
    (tmp_path / "clone").mkdir()
    assert checks.check_clone(make_cfg(tmp_path).repos["o/r"]).status is Status.FAIL


def test_check_clone_wrong_origin(tmp_path):
    git_clone(tmp_path / "clone", "https://github.com/otro/repo.git")
    check = checks.check_clone(make_cfg(tmp_path).repos["o/r"])
    assert check.status is Status.FAIL and "otro/repo" in check.detail


def test_check_clone_ok(tmp_path):
    git_clone(tmp_path / "clone", "git@github.com:o/r.git")
    assert checks.check_clone(make_cfg(tmp_path).repos["o/r"]).status is Status.OK


@pytest.mark.parametrize(("ok", "expected"), [(True, Status.OK), (False, Status.FAIL)])
def test_check_repo_access(monkeypatch, ok, expected):
    calls = []
    monkeypatch.setattr(checks, "probe", lambda cmd, **_: calls.append(cmd) or (ok, "x"))
    assert checks.check_repo_access("o/r").status is expected
    assert any("repos/o/r" in part for part in calls[0])


# ---------- checks: config, plantilla, estado ----------
@pytest.mark.parametrize(
    ("login", "expected"),
    [("alice", Status.OK), ("ALICE", Status.OK), ("bob", Status.WARN), (None, Status.WARN)],
)
def test_check_allowed_user(tmp_path, login, expected):
    assert checks.check_allowed_user(make_cfg(tmp_path), login).status is expected


def test_check_templates_default_ok(tmp_path):
    results = checks.check_templates(make_cfg(tmp_path))
    assert results and all(c.status is Status.OK for c in results)


def test_check_templates_missing_file(tmp_path):
    results = checks.check_templates(make_cfg(tmp_path, template=str(tmp_path / "no.md")))
    assert [c.status for c in results] == [Status.FAIL]


def test_check_state_not_initialized(tmp_path):
    check = checks.check_state(make_cfg(tmp_path))
    assert check.status is Status.WARN and "claude-review init" in check.hint


def test_check_state_initialized(tmp_path):
    cfg = make_cfg(tmp_path)
    StateStore(cfg.state_dir).save(State(last_check=NOW))
    assert checks.check_state(cfg).status is Status.OK


# ---------- doctor ----------
def test_doctor_exit_code():
    assert doctor.exit_code([Check("a", Status.OK), Check("b", Status.WARN)]) == 0
    assert doctor.exit_code([Check("a", Status.OK), Check("b", Status.FAIL)]) == 1


def test_doctor_report_shows_hints_only_for_problems():
    report = doctor.format_report(
        [
            Check("git", Status.OK, "2.43", hint="no debería salir"),
            Check("gh", Status.FAIL, "falta", hint="instálalo"),
        ]
    )
    assert "git" in report and "gh" in report and "instálalo" in report
    assert "no debería salir" not in report


def test_doctor_without_config(tmp_path, healthy_env):
    results = doctor.collect(tmp_path / "no-existe.toml")
    config_check = next(c for c in results if c.name == "config")
    assert config_check.status is Status.FAIL and "claude-review init" in config_check.hint
    assert doctor.exit_code(results) == 1


def test_doctor_healthy_setup(tmp_path, healthy_env):
    git_clone(tmp_path / "clone", "https://github.com/o/r.git")
    path = tmp_path / "config.toml"
    path.write_text(init.render_config("alice", {"o/r": tmp_path / "clone"}, state_dir=tmp_path / "state"))
    StateStore(tmp_path / "state").save(State(last_check=NOW))

    results = doctor.collect(path)
    assert [c for c in results if c.status is not Status.OK] == []
    assert doctor.exit_code(results) == 0


# ---------- init ----------
def test_render_config_roundtrip(tmp_path):
    weird = tmp_path / 'ruta "rara"\\x'
    text = init.render_config("alice", {"o/r": weird, "o/s": tmp_path}, state_dir=tmp_path / "st")
    cfg = parse_config(tomllib.loads(text))
    assert cfg.allowed_user == "alice"
    assert cfg.repos["o/r"].clone_path == weird
    assert cfg.state_dir == tmp_path / "st"


def test_parse_repo_arg_expands_home():
    assert init.parse_repo_arg("o/r=~/x") == ("o/r", Path("~/x").expanduser())


@pytest.mark.parametrize("arg", ["o/r", "sin-barra=~/x", "o/r=", "=~/x"])
def test_parse_repo_arg_invalid(arg):
    with pytest.raises(ValueError):
        init.parse_repo_arg(arg)


def test_init_creates_config_and_state(tmp_path):
    path = tmp_path / "cfg" / "config.toml"
    code = init.run_init(
        path, allowed_user="alice", repos=[f"o/r={tmp_path}"], state_dir=tmp_path / "state", now=NOW
    )
    assert code == 0
    assert load_config(path).allowed_user == "alice"
    assert StateStore(tmp_path / "state").load().last_check == NOW


def test_init_keeps_existing_config_and_last_check(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(init.render_config("bob", {"o/r": tmp_path}, state_dir=tmp_path / "state"))
    old = NOW - timedelta(days=1)
    StateStore(tmp_path / "state").save(State(last_check=old))

    assert init.run_init(path, allowed_user="alice", now=NOW) == 0
    assert load_config(path).allowed_user == "bob"
    assert StateStore(tmp_path / "state").load().last_check == old  # no se pierden comentarios


def test_init_force_overwrites_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(init.render_config("bob", {"o/r": tmp_path}, state_dir=tmp_path / "state"))
    init.run_init(
        path,
        allowed_user="alice",
        repos=[f"o/r={tmp_path}"],
        state_dir=tmp_path / "state",
        force=True,
        now=NOW,
    )
    assert load_config(path).allowed_user == "alice"


def test_init_uses_gh_login_when_user_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(init, "gh_login", lambda: "carol")
    path = tmp_path / "config.toml"
    init.run_init(path, repos=[f"o/r={tmp_path}"], state_dir=tmp_path / "state", now=NOW)
    assert load_config(path).allowed_user == "carol"


@pytest.mark.parametrize(
    ("user", "repos", "login"),
    [("alice", [], "alice"), (None, ["o/r=/x"], None)],
    ids=["sin-repos", "sin-usuario"],
)
def test_init_non_interactive_missing_data_fails(tmp_path, monkeypatch, user, repos, login):
    monkeypatch.setattr(init, "gh_login", lambda: login)
    path = tmp_path / "config.toml"
    code = init.run_init(
        path, allowed_user=user, repos=repos, state_dir=tmp_path / "s", interactive=False, now=NOW
    )
    assert code == 2 and not path.exists()
