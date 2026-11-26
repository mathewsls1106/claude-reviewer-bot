"""Reglas que deciden si un PR se puede revisar (cadena de validadores).

Cada regla devuelve un motivo (str) para omitir o ``None`` si pasa.
Agregar una regla = agregar una función a ``PR_RULES`` o ``DIFF_RULES``.
"""

from collections.abc import Callable, Iterable

from .config import Config
from .models import PullRequest


class Skip(Exception):
    """Motivo por el que no se revisa; se avisa en la PR y NO se reintenta."""


PrRule = Callable[[PullRequest, Config], str | None]
DiffRule = Callable[[str, Config], str | None]


def is_open(pr: PullRequest, _: Config) -> str | None:
    return None if pr.state == "open" else "El PR no está abierto."


def not_from_fork(pr: PullRequest, _: Config) -> str | None:
    return "PR desde un fork: no se revisa automáticamente por seguridad." if pr.is_fork else None


def within_file_limit(pr: PullRequest, cfg: Config) -> str | None:
    if pr.changed_files <= cfg.max_files:
        return None
    return (
        f"El PR toca {pr.changed_files} archivos (límite {cfg.max_files}). "
        "Acótalo o pide la revisión por partes."
    )


def within_diff_limit(diff: str, cfg: Config) -> str | None:
    if len(diff) <= cfg.max_diff_chars:
        return None
    return f"El diff es demasiado grande ({len(diff)} caracteres, límite {cfg.max_diff_chars})."


PR_RULES: tuple[PrRule, ...] = (is_open, not_from_fork, within_file_limit)
DIFF_RULES: tuple[DiffRule, ...] = (within_diff_limit,)


def enforce[T](rules: Iterable[Callable[[T, Config], str | None]], subject: T, cfg: Config) -> None:
    for rule in rules:
        if reason := rule(subject, cfg):
            raise Skip(reason)
