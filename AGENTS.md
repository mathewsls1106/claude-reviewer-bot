# AGENTS.md

Guía para agentes de código (Claude Code, Codex, Gemini CLI, Cursor, etc.) que trabajen en este repositorio.

## Qué es

Bot local que revisa Pull Requests de GitHub con Claude Code. El usuario autorizado comenta
`/claude-review [instrucción]` en un PR y el bot lo detecta solo: corre como **un único proceso
de larga duración** (`uv run claude-review watch`) que hace una pasada cada `poll_interval_seconds`
(300 s por defecto, mínimo 60). **El bot nunca se opera ejecutando pasadas a mano**: `run` real queda
solo como pieza interna de `watch`; para probar se usa `run --dry-run` o los tests.
La periodicidad vive dentro del proceso: no agregues cron, systemd timers ni GitHub Actions.
Debe ser liviano: entre pasadas el proceso duerme en `threading.Event.wait` (cero CPU, sin hilos
extra ni sondeo activo) y solo lanza `claude` cuando hay un `/claude-review` nuevo.
Código, comentarios, mensajes y logs están en español.

## Comandos

```bash
uv sync                                   # instala dependencias (incluye grupo dev)
uv run pytest                             # todos los tests
uv run pytest tests/test_admin.py::test_check_clone_ok   # un test
uv run pytest -k origin                   # por nombre
uv run ruff check . && uv run ruff format --check .      # lint + formato
uv run mypy                               # tipado estricto (configurado sobre src/)

uv run claude-review doctor               # diagnóstico del entorno (solo lee)
uv run claude-review init --repo o/r=RUTA # crea config + estado inicial
uv run claude-review --dry-run --since 2026-11-25T10:00:00Z   # revisa sin publicar ni guardar estado
uv run claude-review watch [--interval N] # modo de operación: pasada cada N s (publica en GitHub)
```

Config: `~/.config/claude-review/config.toml` (o `--config` / `CLAUDE_REVIEW_CONFIG`). Estado y lock en
`~/.local/state/claude-review/`. `watch` y `run` sin `--dry-run` publican comentarios reales en repos de la org:
no lo ejecutes para probar; usa `--dry-run` o los tests.

## Arquitectura (flujo de una pasada)

`cli.py` (subcomandos `watch`, `run` por defecto, `doctor`, `init`; sin subcomando se antepone `run`).
`watch` → `runner.run_forever` instala SIGINT/SIGTERM sobre un `threading.Event` y `runner.watch` repite
`run_once(cfg)` (sin `since` ni `dry_run`) esperando `interval` entre pasadas; una pasada que falla se
registra y el bucle sigue; la señal detiene el bucle al terminar la pasada en curso. `watch` no acepta
`--dry-run` ni `--since`. Cada pasada:
`runner.run_once` toma el lock de `StateStore` → `resolve_since` (`--since` > `last_check − 2 min` > ahora) →
`CommentScanner` lista comentarios de issues y de review vía `GitHubClient` y crea `Job`s →
`ReviewService.process(job)` por cada job (pendientes primero) → se guarda el estado.

`ReviewService.review`: `gh.pull_request` → `guards.PR_RULES` → `gh.diff` → `guards.DIFF_RULES` →
`prompt.build_prompt` → `workspace.pr_worktree` (fetch `pull/N/head` + worktree temporal en el SHA) →
`Reviewer.review` (Strategy; hoy `ClaudeCliReviewer` = `claude -p --allowedTools Read,Grep,Glob`).

Semántica de resultados (`models.Outcome`), clave para no romper reintentos:
- `NotAPullRequest` (404, era un issue) → `DONE` sin comentar.
- `guards.Skip` → `DONE` y se comenta el motivo en el PR (no se reintenta).
- Cualquier otra excepción → `RETRY` hasta `max_attempts`; luego `DONE` con comentario de error.
- `--dry-run` → `DRY`: no reacciona, no publica, no guarda estado (todo efecto visible pasa por `_publish`).
- Si falla el escaneo de GitHub no se avanza `last_check`.

Invariantes que atraviesan varios archivos:
- Clave de job: `"{repo}:{kind}:{comment_id}"` (`kind` = `i` issue / `r` review), usada para deduplicar
  contra `state.done` (se recortan a los últimos 1000) y `state.pending`.
- Anti-auto-disparo: todo comentario del bot empieza con `MARKER` (`<!-- claude-review -->`), el scanner
  ignora comentarios con el marcador y el reviewer reemplaza `/claude-review` en la salida de Claude.
- El comando solo cuenta al inicio de línea (`scanner.CMD_RE`); citas con `>` no disparan.
- Seguridad: PRs desde forks se omiten; `GH_TOKEN`/`GITHUB_TOKEN` se quitan del entorno de Claude;
  Claude solo tiene herramientas de lectura; el contenido del PR va en `<pr_content>` como no confiable.

Plantilla del prompt: `src/claude_reviewer_bot/templates/review.md`, Markdown con frontmatter tipo
`SKILL.md` (se elimina al construir) y variables `string.Template` (`$repo $number $title $extra
$max_words $body $diff $command`). Se puede sobrescribir global (`template`) o por repo
(`"o/r" = { path, template }`). Claude además lee el `CLAUDE.md` del repo revisado porque corre en su worktree.

`admin/`: `checks.py` son verificaciones que devuelven `Check(name, status, detail, hint)`; `doctor.py`
las agrega y sale con 1 si hay algún `FAIL`; `init.py` escribe el TOML y fija `last_check` sin
sobrescribir config existente (salvo `--force`) ni reiniciar un `last_check` existente.
Estos comandos **solo diagnostican/configuran: nunca instalan software**.

## Calidad (obligatorio)

Antes de dar un cambio por terminado debe pasar, sin excepciones:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

La CI (`.github/workflows/ci.yml`) ejecuta lo mismo en cada push a `main` y en cada PR: job `lint`
(ruff + mypy) y job `test` (pytest en Python 3.12, 3.13 y 3.14), ambos con `uv sync --locked`, así que
si cambias dependencias hay que commitear también `uv.lock`.

### TDD
El proyecto se desarrolla con TDD (rojo → verde → refactor):
1. Escribir primero los tests que fijan el contrato del cambio y comprobar que fallan.
2. **Mostrarlos al usuario y esperar su aprobación** antes de tocar `src/`.
3. Implementar lo mínimo para que pasen; luego refactorizar con los tests en verde.
4. No modificar tests aprobados para que pasen. Si el plan estaba mal, explicarlo y pedir permiso.
Un bug se corrige primero con un test que lo reproduzca.

### Tipado estricto
- `mypy --strict` sobre `src/` (`[tool.mypy]` en `pyproject.toml`): toda función pública o privada
  lleva anotaciones completas, incluido el retorno.
- `Any` solo en fronteras con datos externos, a través del alias `models.JsonDict`
  (JSON de la API de GitHub, TOML crudo). Dentro del dominio se usan dataclasses tipadas
  (`Job`, `PullRequest`, `Config`, `Check`) y enums (`CommentKind`, `Outcome`, `Status`).
- Nada de `# type: ignore` ni `cast` sin un comentario que justifique por qué.
- Dependencias intercambiables se declaran como `Protocol` (`Reviewer`, `Notifier`).

### Lint y complejidad
- `ruff` con reglas `E F W I B UP SIM C90`, línea máx. 110 y **complejidad ciclomática máx. 8**:
  si una función la supera, se divide (no se sube el límite ni se silencia con `noqa`).
- `# noqa: BLE001` solo en los puntos donde capturar `Exception` es la política
  (reintentos del servicio, error fatal del CLI, fallo del escaneo).

### Diseño
- Una responsabilidad por módulo. Los efectos externos están aislados: GitHub solo vía
  `GitHubClient`, procesos solo vía `shell.run`/`shell.probe`, disco de estado solo vía `StateStore`.
- Dependencias por constructor (`ReviewService`, `CommentScanner`); el armado ocurre en `runner.run_once`.
- Reglas extensibles como datos: un guard nuevo es una función agregada a `guards.PR_RULES`/`DIFF_RULES`;
  un check nuevo es una función en `admin/checks.py` que devuelve `Check` con `hint` accionable.
- Configuración y modelos inmutables (`@dataclass(frozen=True)`) salvo `Job`/`State`, que mutan a propósito.
- Sin dependencias de runtime: solo biblioteca estándar. Agregar una requiere justificarlo.
- El estado se escribe de forma atómica (archivo temporal + `replace`); no romper ese patrón.

### Tests
- Sin red, sin GitHub real y sin invocar `claude`: se usan fakes (`FakeGH` en `tests/test_bot.py`) y
  `monkeypatch` sobre nombres a nivel de módulo (`checks.probe`, `checks.which`, `init.gh_login`).
  Por eso el código debe llamar a esas funciones por el nombre del módulo, no capturarlas en closures.
- `git` real sí se usa, en `tmp_path`. `checks.check_clone` usa `shell.run` y no `probe` a propósito:
  en `test_doctor_healthy_setup` `probe` está simulado.
- Estilo: funciones `test_*` planas, agrupadas con comentarios `# ---------- sección ----------`,
  `pytest.mark.parametrize` para variantes y `tmp_path` para todo archivo. Nunca tocar `~/.config`
  ni `~/.local/state` reales.
- `shell.run` lanza `CommandError`; `shell.probe` nunca lanza y devuelve `(ok, salida)` (para diagnósticos).

### Commits
Conventional Commits en español (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`), asunto en imperativo
y cuerpo explicando el porqué cuando no es obvio. Solo se hace commit/push cuando el usuario lo pide.
