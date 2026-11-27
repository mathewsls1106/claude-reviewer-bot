"""Construye el prompt a partir de una plantilla Markdown.

La plantilla usa variables ``$nombre`` / ``${nombre}`` (``string.Template``), así
llaves ``{}`` y código dentro del Markdown no rompen nada. Variables disponibles:

    $repo $number $title $extra $max_words $body $diff $command
"""

from importlib.resources import files
from pathlib import Path
from string import Template

from .models import COMMAND, PullRequest

DEFAULT_TEMPLATE = "review.md"


def load_template(path: Path | None = None, name: str = DEFAULT_TEMPLATE) -> Template:
    """Carga ``path`` o, si no se da, la plantilla ``name`` incluida en el paquete."""
    source = path or files(__package__).joinpath("templates", name)
    text = source.read_text(encoding="utf-8")
    return Template(_strip_frontmatter(text))


def _strip_frontmatter(text: str) -> str:
    """Permite metadatos YAML (``---``) al inicio de la plantilla, como en un SKILL.md."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :].lstrip("\n")
    return text


def build_prompt(
    template: Template, pr: PullRequest, diff: str, extra: str, max_words: int, command: str = COMMAND
) -> str:
    return template.safe_substitute(
        repo=pr.repo,
        number=pr.number,
        title=pr.title,
        extra=extra or "(ninguna: revisión general)",
        max_words=max_words,
        body=pr.body or "(sin descripción)",
        diff=diff,
        command=command,
    )
