# claude-reviewer-bot

Revisa Pull Requests de GitHub con Claude Code cuando el usuario autorizado comenta
`/claude-review [instrucción opcional]` en el PR. Pensado para correr periódicamente (cron / systemd timer).

## Requisitos
- Python ≥ 3.12 y [uv](https://docs.astral.sh/uv/)
- `gh` autenticado (`gh auth login`) y `claude` (Claude Code CLI) en el `PATH`
- Un clon local de cada repo a vigilar

## Instalación y uso
```bash
uv sync
cp config.example.toml ~/.config/claude-review/config.toml   # y editarlo
uv run claude-review --dry-run      # imprime la revisión, no publica ni guarda estado
uv run claude-review                # ciclo normal
uv run claude-review --since 2026-11-25T10:00:00Z
```
Cron cada 2 minutos:
```
*/2 * * * * cd /ruta/claude-reviewer-bot && uv run claude-review >> ~/.local/state/claude-review/log 2>&1
```

## Plantilla del prompt
La plantilla es un Markdown en `src/claude_reviewer_bot/templates/review.md`, con frontmatter
estilo `SKILL.md` (se ignora al construir el prompt). Variables: `$repo $number $title $extra
$max_words $body $diff $command`. Las llaves `{}` y el código dentro del Markdown no molestan.

Para personalizar: copia la plantilla y apunta a ella en el config con `template = "..."` (global)
o `"org/repo" = { path = "...", template = "..." }` (por repo).

Además, como Claude corre dentro del worktree del PR, lee automáticamente el `CLAUDE.md` del repo
revisado: las convenciones propias de cada proyecto se aplican sin tocar el bot.

## Arquitectura
| Módulo | Responsabilidad |
|---|---|
| `cli.py` | argumentos, lock, armado de dependencias, ciclo |
| `config.py` | carga y validación del TOML (dataclasses inmutables) |
| `state.py` | `StateStore` (Repository): JSON atómico + lock |
| `github.py` | `GitHubClient` (Facade sobre `gh`) |
| `scanner.py` | detecta comentarios `/claude-review` → `Job` |
| `guards.py` | reglas de validación del PR (cadena de validadores) |
| `prompt.py` + `templates/` | construye el prompt desde la plantilla Markdown |
| `workspace.py` | worktree temporal (context manager) |
| `reviewer.py` | `Reviewer` (Strategy) → `ClaudeCliReviewer` |
| `notifier.py` | notificaciones de escritorio (Strategy / Null Object) |
| `service.py` | `ReviewService`: orquesta un job y devuelve un `Outcome` |

## Desarrollo
```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
