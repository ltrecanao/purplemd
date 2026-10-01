---
version: "0.1.0"
schemaVersion: 1
name: "base"
extends: null
skills: [python, container, markdown, git, frontend, uiux]
model: "sonnet-4"
description: "Agente base genérico. Coordina subagentes por dominio, aplica reglas transversales y delega a skills especializadas."
language: "es"
---

# Agente Base

## Principios generales

- Respondé y documentá en **español**.
- Usá inglés solo para identificadores, nombres propios, comandos y contenido técnico literal.
- **Delegación por dominio**: `skills/` contiene habilidades especializadas. Delegá tareas al subagente con la
  skill correspondiente. Coordiná vos; no ejecutás tareas de dominio directamente.
- Si una tarea no tiene skill aplicable, ejecutala vos directamente.
- No comitees secretos ni archivos generados.
- Leé las skills aplicables y archivos relevantes antes de modificar.
- Hacé cambios pequeños y enfocados.
- No amplíes el alcance ni asumas decisiones faltantes.
- No hagas commits, pushes, merges, borrados ni renombres sin autorización explícita.
- **Límite de contexto**: Archivos `.md` (AGENTS.md, SKILL.md) **no superan 300 líneas**. Si crecen, dividí en skills/sub-agentes.

## Consistencia de versiones (Python)

- Mantené una **sola versión de Python** en todo el proyecto.
- Archivos que deben coincidir: `render.yaml` (`PYTHON_VERSION`), `Dockerfile` (`FROM python:X`), CI
  (`PYTHON_VERSION`), `pyproject.toml` (`requires-python`, `target-version`, `python-version`).
- El CI debe fallar si hay divergencia.

## Frontend y despliegue (GitHub Pages / subpath)

- Usá **rutas relativas** en HTML/CSS/JS (ej: `css/style.css`, `js/app.js`, `import ... from "./config.js"`).
  Nunca rutas absolutas desde raíz de dominio.
- La URL de la API **solo** en un archivo de configuración del frontend (ej: `docs/js/config.js` o
  `public/config.js`). No hardcodear en código de aplicación.

## CORS (FastAPI / backends)

- **No uses wildcards** en `allow_origins` (`https://*.github.io` no funciona).
- Usá origen explícito de producción + `allow_origin_regex` para localhost:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://TU-DOMINIO-PROD"],
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
```

## Testing

- **Borrá tests de endpoints/funcionalidad eliminada**. Tests deben reflejar comportamiento actual, no histórico.
- Tests automatizados para reglas críticas (ej: contraste WCAG, consistencia de versiones).

## Accesibilidad

- Contraste mínimo **WCAG AAA 7:1** para texto normal.
- Incluir test automatizado que valide paletas.

## Checklist pre-push (plantilla)

- Tests: `✓`
- Lint: `✓`
- Type-check: `✓`
- Prueba local (backend + frontend): `✓`
- Commit message convencional (`feat:`, `fix:`, `chore:`, `docs:`): `✓`
- Push → CI pasa → Deploy → Verificar en producción: `✓`

> **Nota**: Cada proyecto adapta los comandos exactos (ej: `uv run ...`, `pnpm test`, etc.) en su `AGENTS.md`
> local extendiendo este base.
