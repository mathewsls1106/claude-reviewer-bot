"""``claude-review init``: crea el config y el estado inicial.

- No sobrescribe un config existente salvo con ``force``.
- Nunca reinicia un ``last_check`` existente (no se pierden comentarios).
"""

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from ..config import load_config
from ..shell import log, probe
from ..state import StateStore

REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


class InitError(ValueError):
    """Faltan datos para crear la configuración."""


def _toml_str(value: str | Path) -> str:
    # Una cadena JSON sin escapar no-ASCII es una cadena básica TOML válida.
    return json.dumps(str(value), ensure_ascii=False)


def render_config(allowed_user: str, repos: dict[str, Path], state_dir: Path | None = None) -> str:
    lines = [
        "# Generado por `claude-review init`. Opciones: ver config.example.toml",
        f"allowed_user = {_toml_str(allowed_user)}",
    ]
    if state_dir:
        lines.append(f"state_dir = {_toml_str(state_dir)}")
    lines += ["", "[repos]", *(f"{_toml_str(name)} = {_toml_str(path)}" for name, path in repos.items())]
    return "\n".join(lines) + "\n"


def parse_repo_arg(arg: str) -> tuple[str, Path]:
    """``"owner/repo=RUTA"`` → ``("owner/repo", Path(RUTA))``."""
    name, sep, path = arg.partition("=")
    name, path = name.strip(), path.strip()
    if not sep or not path or not REPO_RE.match(name):
        raise ValueError(f"formato inválido '{arg}', se espera owner/repo=RUTA")
    return name, Path(path).expanduser()


def gh_login() -> str | None:
    ok, out = probe(["gh", "api", "user", "--jq", ".login"])
    return out if ok and out else None


# ---------- obtención de datos ----------
def _ask(prompt: str) -> str:
    return input(prompt).strip()


def _resolve_user(allowed_user: str | None, interactive: bool) -> str:
    user = allowed_user or gh_login()
    if not user and interactive:
        user = _ask("Usuario de GitHub autorizado a usar /claude-review: ")
    if not user:
        raise InitError("falta el usuario: usa --allowed-user o inicia sesión con `gh auth login`")
    return user


def _ask_repos() -> list[str]:
    print("Repos a vigilar, formato owner/repo=RUTA_DEL_CLON (línea vacía para terminar):")
    return list(iter(lambda: _ask("  > "), ""))


def _resolve_repos(repos: Iterable[str], interactive: bool) -> dict[str, Path]:
    items = list(repos) or (_ask_repos() if interactive else [])
    if not items:
        raise InitError("falta al menos un repo: usa --repo owner/repo=RUTA")
    return dict(parse_repo_arg(r) for r in items)


# ---------- comando ----------
def _write_config(path, allowed_user, repos, state_dir, interactive) -> None:
    text = render_config(
        _resolve_user(allowed_user, interactive), _resolve_repos(repos, interactive), state_dir
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    log(f"config creado en {path}")


def _init_state(state_dir: Path, now: datetime) -> None:
    store = StateStore(state_dir)
    state = store.load()
    if state.last_check:
        log(f"estado ya inicializado (última revisión {state.last_check.isoformat()}); se conserva")
        return
    state.last_check = now
    store.save(state)
    log(f"estado inicializado: se atenderán comentarios desde {now.isoformat()}")


def run_init(
    path: Path,
    *,
    allowed_user: str | None = None,
    repos: Iterable[str] | None = None,
    state_dir: Path | None = None,
    force: bool = False,
    interactive: bool = False,
    now: datetime | None = None,
) -> int:
    try:
        if path.exists() and not force:
            log(f"ya existe {path}; se conserva (usa --force para regenerarlo)")
        else:
            _write_config(path, allowed_user, repos or [], state_dir, interactive)
        cfg = load_config(path)
    except (InitError, ValueError) as e:
        log(f"init: {e}")
        return 2
    _init_state(cfg.state_dir, now or datetime.now(UTC))
    log("siguiente paso: claude-review doctor")
    return 0
