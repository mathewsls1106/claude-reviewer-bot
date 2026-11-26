"""Carga y validación de la configuración (TOML)."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path.home() / ".config/claude-review/config.toml"
DEFAULT_STATE_DIR = Path.home() / ".local/state/claude-review"


class ConfigError(ValueError):
    """La configuración es inválida o falta."""


@dataclass(frozen=True)
class RepoConfig:
    name: str  # "owner/repo"
    clone_path: Path  # clon local usado para crear worktrees
    template: Path | None = None  # plantilla de prompt propia de este repo


@dataclass(frozen=True)
class Config:
    allowed_user: str
    repos: dict[str, RepoConfig]
    max_diff_chars: int = 150_000
    max_files: int = 60
    timeout_seconds: int = 900
    max_attempts: int = 3
    max_words: int = 700
    model: str = ""
    template: Path | None = None  # plantilla global; None = la incluida en el paquete
    state_dir: Path = field(default=DEFAULT_STATE_DIR)

    def template_for(self, repo: str) -> Path | None:
        return self.repos[repo].template or self.template


def config_path() -> Path:
    return Path(os.environ.get("CLAUDE_REVIEW_CONFIG", DEFAULT_CONFIG_PATH))


def _path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def _parse_repo(name: str, value: str | dict[str, Any]) -> RepoConfig:
    """Acepta ``"owner/repo" = "~/clon"`` o ``"owner/repo" = { path = "...", template = "..." }``."""
    if isinstance(value, str):
        return RepoConfig(name, Path(value).expanduser())
    if "path" not in value:
        raise ConfigError(f"repos.'{name}' necesita 'path'")
    return RepoConfig(name, Path(value["path"]).expanduser(), _path(value.get("template")))


def parse_config(raw: dict[str, Any]) -> Config:
    for key in ("allowed_user", "repos"):
        if key not in raw:
            raise ConfigError(f"falta la clave obligatoria '{key}'")
    repos = {name: _parse_repo(name, v) for name, v in raw.pop("repos").items()}
    if not repos:
        raise ConfigError("'repos' está vacío")
    known = Config.__dataclass_fields__.keys()
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"claves desconocidas: {', '.join(sorted(unknown))}")
    for key in ("template", "state_dir"):
        if key in raw:
            raw[key] = _path(raw[key])
    return Config(repos=repos, **raw)


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        raise ConfigError(f"no existe {path} (copia config.example.toml)")
    with open(path, "rb") as f:
        return parse_config(tomllib.load(f))
