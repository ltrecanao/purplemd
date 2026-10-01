---
version: "0.1.0"
schemaVersion: 1
name: "python"
description: "Desarrollo Python: lint, types, tests, versión única, packaging moderno."
tools: [read, write, edit, shell, grep, glob]
permissions: "read-write"
model: "sonnet-4"
tags: [python, backend, lint, typecheck, test]
---

# Skill: Python

## Principios

- **Versión única de Python** en todo el proyecto. Fuentes de verdad:
  - `pyproject.toml` (`requires-python`, `target-version`, `python-version`)
  - `Dockerfile` (`FROM python:X.Y`)
  - CI (`.github/workflows/*.yml` → `PYTHON_VERSION`)
  - Render/Deploy config (`PYTHON_VERSION`)
- El CI **debe fallar** si hay divergencia entre estas fuentes.
- Usá **uv** como gestor de paquetes y runner (`uv run`, `uv sync`, `uv add`).
- Código **type-safe**: `ty check` (o `mypy`/`pyright`) en CI obligatorio.
- Lint con **ruff** (reemplaza flake8, isort, black, etc.). Config en `pyproject.toml`.
- Tests con **pytest** (o `unittest` si el proyecto lo usa). Cobertura mínima: 80%.
- **Borrá tests de código eliminado**. Tests reflejan comportamiento actual, no histórico.

## Estructura estándar (recomendada)

```text
project/
├── pyproject.toml          # Config única: deps, tools, python version
├── src/
│   └── package_name/       # Código fuente (src-layout)
├── tests/                  # Espejo de src/
├── .github/workflows/ci.yml
├── Dockerfile
├── uv.lock                 # Lockfile commitido
└── README.md
```

## Comandos canónicos (proyecto adapta en su AGENTS.md)

```bash
# Instalar deps + lock
uv sync --all-extras

# Lint
uv run ruff check .

# Type-check
uv run ty check

# Tests
uv run pytest -v --cov=src --cov-fail-under=80

# Formatear
uv run ruff format .
```

## Reglas de código

- **Imports**: absolutos desde `src` (`from package.module import X`). Sin `sys.path` hacks.
- **Tipado**: type hints en toda API pública. `py.typed` marker en paquete.
- **Errores**: Excepciones específicas, no `except Exception`. Log con `logging` (no `print`).
- **Async**: `async/await` nativo. `httpx`/`aiohttp` para I/O. Evitá blocking en loops.
- **Config**: `pydantic-settings` + `.env` (no commiteado). Settings como inmutable `BaseSettings`.
- **Dependencias**: separá `dependencies` (runtime) de `optional-dependencies` (dev, test, docs, etc.).

## Docker (multi-stage, seguro)

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

FROM base AS builder
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

FROM base AS runtime
COPY --from=builder /app/.venv .venv
ENV PATH="/app/.venv/bin:$PATH"
COPY src/ ./src
USER nobody
CMD ["python", "-m", "package_name"]
```

## CI mínimo (GitHub Actions)

```yaml
name: CI
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --all-extras --frozen
      - run: uv run ruff check .
      - run: uv run ty check
      - run: uv run pytest --cov=src --cov-fail-under=80
      - name: Versiones consistentes
        run: |
          # Script que verifica pyproject.toml == Dockerfile == CI == Render
          python scripts/check_python_version.py
```

## Checklist pre-push (skill-level)

- [ ] `uv run ruff check .` → OK
- [ ] `uv run ty check` → OK
- [ ] `uv run pytest --cov=src --cov-fail-under=80` → OK
- [ ] `uv lock` → `uv.lock` actualizado si cambié deps
- [ ] Versión Python consistente en `pyproject.toml`, `Dockerfile`, CI, deploy config

---

> **Nota**: Esta skill es **genérica**. Proyectos que la usen completan comandos exactos, rutas, y añaden
> reglas específicas en su `AGENTS.md` local (extends: base + skills: [python, ...]).
