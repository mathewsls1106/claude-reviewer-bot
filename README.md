<img width="1810" height="904" alt="Gemini_Generated_Image_ieib15ieib15ieib(1)" src="https://github.com/user-attachments/assets/9e8a2b70-aeac-4737-b647-0d1c1047bf98" />


Revisa Pull Requests de GitHub con Claude Code cuando el usuario autorizado comenta
`/claude-review [instrucción opcional]` en el PR. Corre como un proceso periódico liviano (`watch`).

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
uv run claude-review --dry-run --since 2026-11-25T10:00:00Z
uv run claude-review watch          # modo de operación: una pasada cada 300 s
uv run claude-review watch --interval 120
```
- `init` toma `allowed_user` de tu sesión de `gh` si no pasas `--allowed-user`; en una terminal
  pregunta lo que falte. No sobrescribe un config existente (salvo `--force`) ni reinicia el estado.
- `doctor` solo diagnostica (no instala nada) y sale con código 1 si hay algún ❌.
- Todos los comandos aceptan `--config RUTA`.

El bot no se opera a mano: se deja corriendo `claude-review watch`, que hace una pasada cada
`poll_interval_seconds` (300 s por defecto, mínimo 60, o `--interval N`). Basta comentar
`/claude-review` en el PR y la revisión llega en la siguiente pasada. Entre pasadas el proceso duerme
sin consumir CPU y solo lanza `claude` cuando hay un comando nuevo. Ctrl+C o SIGTERM lo detienen al
terminar la pasada en curso. `run` (una sola pasada) queda para probar con `--dry-run`.

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
| `runner.py` | una pasada (lock, buscar comentarios, procesar, guardar estado) y el bucle periódico de `watch` |
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
