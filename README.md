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
uv run claude-review init --repo org/repo=~/ruta/del/clon   # crea config y estado inicial
uv run claude-review doctor         # verifica herramientas, sesiones, config y repos
uv run claude-review --dry-run      # imprime la revisión, no publica ni guarda estado
uv run claude-review                # una pasada normal (equivale a `run`)
uv run claude-review --since 2026-11-25T10:00:00Z
```
- `init` toma `allowed_user` de tu sesión de `gh` si no pasas `--allowed-user`; en una terminal
  pregunta lo que falte. No sobrescribe un config existente (salvo `--force`) ni reinicia el estado.
- `doctor` solo diagnostica (no instala nada) y sale con código 1 si hay algún ❌.
- Todos los comandos aceptan `--config RUTA`.

El bot se ejecuta a mano: comenta `/claude-review` en el PR y luego corre `uv run claude-review`.

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
| `cli.py` | subcomandos `run`, `doctor`, `init` (Command: tabla de handlers) |
| `runner.py` | una pasada: lock, buscar comentarios, procesar, guardar estado |
| `admin/checks.py` | verificaciones del entorno, cada una devuelve un `Check` con pista |
| `admin/doctor.py` | junta los checks, imprime el reporte y el código de salida |
| `admin/init.py` | genera el config y el estado inicial |
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
