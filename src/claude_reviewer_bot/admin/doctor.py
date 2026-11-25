"""``claude-review doctor``: reúne las verificaciones y las muestra con pistas para arreglarlas."""

from pathlib import Path

from ..config import Config, ConfigError, load_config
from . import checks
from .checks import Check, Status


def collect(config_path: Path) -> list[Check]:
    results = checks.check_binaries()
    gh_check, login = checks.check_gh_auth()
    results += [gh_check, checks.check_claude_auth()]
    try:
        cfg = load_config(config_path)
    except (ConfigError, OSError, ValueError) as e:
        return [*results, Check("config", Status.FAIL, str(e), "Ejecuta: claude-review init")]
    return [*results, Check("config", Status.OK, str(config_path)), *_config_checks(cfg, login)]


def _config_checks(cfg: Config, login: str | None) -> list[Check]:
    results = [checks.check_allowed_user(cfg, login), *checks.check_templates(cfg)]
    for repo in cfg.repos.values():
        results += [checks.check_clone(repo), checks.check_repo_access(repo.name)]
    return [*results, checks.check_state(cfg)]


def format_report(results: list[Check]) -> str:
    lines = []
    for c in results:
        lines.append(f"{c.status.value} {c.name}" + (f": {c.detail}" if c.detail else ""))
        if c.status is not Status.OK and c.hint:
            lines.append(f"     → {c.hint}")
    return "\n".join(lines)


def exit_code(results: list[Check]) -> int:
    return 1 if any(c.status is Status.FAIL for c in results) else 0


def run(config_path: Path) -> int:
    results = collect(config_path)
    print(format_report(results))
    code = exit_code(results)
    print("\nTodo listo." if code == 0 else "\nHay problemas (❌) que impiden ejecutar el bot.")
    return code
