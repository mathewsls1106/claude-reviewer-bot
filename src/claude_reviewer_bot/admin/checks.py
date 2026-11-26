"""Verificaciones individuales del entorno. Solo diagnostican: nunca instalan ni modifican nada.

Cada verificación devuelve un :class:`Check` con una pista (``hint``) de cómo arreglarlo.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from shutil import which

from ..config import Config, RepoConfig
from ..prompt import load_template
from ..shell import CommandError, probe, run
from ..state import StateStore

EXPIRY_WARNING = timedelta(days=3)

BINARIES = {
    "git": "Instálalo con el gestor de paquetes (p. ej. `sudo apt install git`)",
    "gh": "Instala GitHub CLI: https://cli.github.com",
    "claude": "Instala Claude Code: https://docs.claude.com/en/docs/claude-code",
}


class Status(Enum):
    OK = "✅"
    WARN = "⚠️ "
    FAIL = "❌"


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str = ""
    hint: str = ""


# ---------- herramientas ----------
def check_binaries() -> list[Check]:
    return [_check_binary(name, hint) for name, hint in BINARIES.items()]


def _check_binary(name: str, hint: str) -> Check:
    if not which(name):
        return Check(name, Status.FAIL, "no está en el PATH", hint)
    _, version = probe([name, "--version"])
    return Check(name, Status.OK, version.splitlines()[0] if version else "")


# ---------- sesiones ----------
def check_gh_auth() -> tuple[Check, str | None]:
    ok, out = probe(["gh", "api", "user", "--jq", ".login"])
    if not ok or not out:
        return Check("gh: sesión", Status.FAIL, out, "Ejecuta: gh auth login"), None
    return Check("gh: sesión", Status.OK, f"usuario {out}"), out


def check_claude_auth(now: datetime | None = None) -> Check:
    name, hint = "claude: sesión", "Ejecuta: claude auth login"
    ok, out = probe(["claude", "auth", "status", "--json"])
    if not ok:
        return Check(name, Status.FAIL, out, hint)
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return Check(name, Status.FAIL, "respuesta inesperada de `claude auth status`", hint)
    if not data.get("loggedIn"):
        return Check(name, Status.FAIL, "sin sesión iniciada", hint)
    return _check_expiry(name, data.get("loginExpiresAt"), now or datetime.now(UTC))


def _check_expiry(name: str, expires_at: str | None, now: datetime) -> Check:
    if not expires_at:
        return Check(name, Status.OK, "sesión iniciada")
    expires = datetime.fromisoformat(expires_at)
    if expires - now < EXPIRY_WARNING:
        return Check(
            name, Status.WARN, f"la sesión vence {expires:%Y-%m-%d}", "Renueva con: claude auth login"
        )
    return Check(name, Status.OK, f"sesión válida hasta {expires:%Y-%m-%d}")


# ---------- repos ----------
def origin_matches(url: str, repo: str) -> bool:
    """``True`` si la URL del remoto (https o ssh) apunta a ``owner/repo``."""
    path = url.strip().removesuffix("/").removesuffix(".git")
    owner_repo = "/".join(re.split(r"[/:]", path)[-2:])
    return owner_repo.lower() == repo.lower()


def check_clone(repo: RepoConfig) -> Check:
    name = f"{repo.name}: clon"
    if not repo.clone_path.is_dir():
        return Check(name, Status.FAIL, f"no existe {repo.clone_path}", f"Clónalo: gh repo clone {repo.name}")
    try:
        url = run(["git", "-C", str(repo.clone_path), "remote", "get-url", "origin"]).strip()
    except CommandError:
        return Check(name, Status.FAIL, f"{repo.clone_path} no es un repo git con 'origin'", "Revisa la ruta")
    if not origin_matches(url, repo.name):
        return Check(name, Status.FAIL, f"origin apunta a {url}", "Corrige la ruta en el config")
    return Check(name, Status.OK, str(repo.clone_path))


def check_repo_access(repo: str) -> Check:
    ok, out = probe(["gh", "api", f"repos/{repo}", "--jq", ".full_name"])
    if not ok:
        return Check(f"{repo}: acceso", Status.FAIL, out, "Verifica permisos o el nombre del repo")
    return Check(f"{repo}: acceso", Status.OK, "gh puede leer el repo")


# ---------- config, plantilla, estado ----------
def check_allowed_user(cfg: Config, login: str | None) -> Check:
    name = "allowed_user"
    if login is None:
        return Check(name, Status.WARN, f"{cfg.allowed_user} (no se pudo comparar con gh)")
    if login.lower() != cfg.allowed_user.lower():
        detail = f"config dice {cfg.allowed_user}, gh está logueado como {login}"
        return Check(name, Status.WARN, detail, "Solo se atienden comentarios de allowed_user")
    return Check(name, Status.OK, cfg.allowed_user)


def check_templates(cfg: Config) -> list[Check]:
    paths = {cfg.template_for(repo) for repo in cfg.repos}
    return [_check_template(p) for p in sorted(paths, key=str)]


def _check_template(path: Path | None) -> Check:
    label = str(path) if path else "incluida en el paquete"
    if path and not path.is_file():
        return Check("plantilla", Status.FAIL, f"no existe {path}", "Corrige 'template' en el config")
    load_template(path)
    return Check("plantilla", Status.OK, label)


def check_state(cfg: Config) -> Check:
    state = StateStore(cfg.state_dir).load()
    if state.last_check is None:
        return Check(
            "estado",
            Status.WARN,
            "sin inicializar: la primera pasada ignorará comentarios anteriores",
            "Ejecuta: claude-review init",
        )
    detail = f"última revisión {state.last_check:%Y-%m-%d %H:%M} UTC, {len(state.pending)} pendientes"
    return Check("estado", Status.OK, detail)
