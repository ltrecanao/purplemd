---
version: "0.1.0"
schemaVersion: 1
name: "purplemd"
extends: "base"
skills: [python, container, markdown, git, frontend, uiux, seguridad]
model: "sonnet-4"
description: "Agente de PurpleMD: editor de notas Markdown en FastAPI + frontend vanilla. Coordina subagentes por dominio y aplica las reglas del proyecto."
language: "es"
---

# Agente de PurpleMD

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

## Comandos del proyecto

Todo corre con [`uv`](https://docs.astral.sh/uv/), no con `pip` ni `venv` a mano. La suite es `unittest` corriendo
sobre `pytest`; no hay `package.json` ni paso de build para el frontend (JS vanilla servido tal cual).

| Qué | Comando |
|---|---|
| Instalar/actualizar el entorno | `uv sync` |
| Tests | `uv run pytest -q` |
| Un solo archivo de tests | `uv run pytest tests/test_api.py -q` |
| Lint | `uv run ruff check .` |
| Auto-corregir lint | `uv run ruff check . --fix` |
| Type check | `uv run ty check .` |
| Servir en desarrollo | `uv run uvicorn api:app --port 8000` |
| Probar el frontend | Abrir `http://localhost:8000/` (lo sirve la misma app) |
| Imagen | `podman build --format docker -t purplemd .` |

Los tres checks (`pytest`, `ruff`, `ty`) tienen que salir **verdes antes** de cualquier commit. El CI
(`.github/workflows/ci.yml`) los repite y además falla si diverge la versión de Python.

## Estructura del código

- `api.py` — FastAPI: las ~20 rutas, validación de entrada, PDF y avisos, **middleware de sesión y
  cabeceras de seguridad**, y las 4 rutas `/api/auth/*`.
- `purplemd.py` — lógica de negocio y validaciones, sin saber nada de HTTP.
- `purplemd_storage/` — interfaz `Storage` con tres implementaciones: `filesystem` (local),
  `memory` (demo) y `drive` (Google Drive del usuario). `zipio.py` trae lo que comparten.
- `purplemd_auth/` — integración con Google: `config.py` (credenciales), `oauth.py` (Authorization
  Code + PKCE), `sesiones.py` (cookie firmada HMAC-SHA256) y `tokens.py` (refresh tokens en disco).
- `renderer.py` — markdown-it con `html: False` (no se inyecta HTML crudo) y resaltado con Pygments.
- `static/` — frontend sin dependencias: `index.html`, `css/style.css`, `js/app.js`.
- `plantillas/` — documentos `.md` de ejemplo y su manifiesto `indice.json`; se sirven en `/plantillas`.
- `docs/` — `API.md`, `ARQUITECTURA.md`, `DESARROLLO.md`, `ACCESIBILIDAD.md`, `AUTH.md`.

## Consistencia de versiones (Python)

- El proyecto vive en **Python 3.13** en todos lados. Archivos que deben coincidir:
  `Dockerfile` (`FROM python:3.13-slim-…`), CI (`PYTHON_VERSION`),
  `pyproject.toml` (`requires-python`, `[tool.ruff] target-version`, `[tool.ty] python-version`).
- Si cambiás la versión, cambiala en todos ellos. El CI ya falla solo si hay divergencia.

## Frontend

- **Rutas absolutas desde la raíz** (`/static/css/style.css`, `/static/js/app.js`): el frontend lo sirve
  la misma app en la raíz del dominio, sin subpath. Si algún día se expone detrás de un prefijo, hay que
  pasarlas a relativas.
- **Sin librerías en el cliente.** No meter frameworks ni CDN: es una decisión de diseño del proyecto,
  documentada en el `README`.
- El frontend no tiene suite propia. Lo que toca la API se testea en `tests/test_api.py` (proyectos, notas,
  directorios, PDF, render), en `tests/test_zip.py` (export/import) y en
  `tests/test_notificaciones.py` (avisos).
- Lo único del frontend que sí se testea: `tests/test_auth.py::CabecerasTests` lee `index.html` y
  exige que **no** haya `style=` ni `onclick=` inline, porque la CSP del backend no los permitiría.

## CORS (FastAPI)

- El frontend lo sirve la **misma app**, en la raíz: las llamadas a `/api` son same-origin y CORS no interviene
  en el uso normal. Solo importa para consumidores externos de la API.
- **No uses wildcards** en `allow_origins` ni `allow_methods`/`allow_headers`.
- Usá origen explícito de producción + `allow_origin_regex` para localhost:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://purplemd.onrender.com"],
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)
```

- **Estado**: cumplido en `api.py`. Si cambiás el dominio de producción, cambialo de los dos lados:
  de `allow_origins` y del README.

## Sesión con Google

- El login **solo está exigido** cuando hay credenciales completas
  (`GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` + `PURPLEMD_SECRET_KEY`). Sin ellas, la app se
  comporta exactamente como siempre: sin pantalla de acceso y sin 401. `tests/test_auth.py` cubre
  los dos lados.
- Secretos **solo** en variables de entorno. Nunca en el repo, nunca en una URL, nunca en un
  `repr` (`ConfigAuth` los marca `repr=False` por eso).
- Con sesión, el aislamiento lo hace el backend (carpeta por `sha256(sub)` o el Drive de la
  cuenta): el frontend **deja de poner el prefijo** `u_xxxx_` en los nombres de proyecto. Los dos
  mecanismos conviven según `requiere_sesion`.
- Ver `docs/AUTH.md` para el flujo completo, las variables y el troubleshooting.

## Testing

- **Borrá tests de endpoints/funcionalidad eliminada**. Tests deben reflejar comportamiento actual, no histórico.
- Tests automatizados para reglas críticas (ej: contraste WCAG, consistencia de versiones).
- **Cada regla de seguridad nueva nace con su test** (regla de `skills/seguridad/SKILL.md`).
  Las de sesión, CSRF y cabeceras están en `tests/test_auth.py`; las de Drive en
  `tests/test_drive.py`, que además corre el mismo guion contra los tres backends.

## Accesibilidad

- Contraste mínimo **WCAG AA 4.5:1** en todo texto, y **AAA 7:1** en el texto principal (`--texto` sobre
  `--fondo` y sobre `--panel`).
- Todo par que baje de AA es un bug a corregir; los que quedan entre AA y AAA son una decisión de diseño
  registrada en `docs/ACCESIBILIDAD.md`.
- **Hay que mantener el test automatizado de paleta**: `tests/test_contraste.py` lee `static/css/style.css`,
  recalcula los 26 pares de ambos temas y falla si alguno baja de su umbral o si las mediciones publicadas
  dejan de coincidir. Cualquier cambio de token obliga a volver a medir y a actualizar esa tabla.
- **El texto del explorador no puede quedar invisible**: entre 48rem y 60rem el colapso
  (`font-size: 0` recuperado por `attr(title)`) solo aplica donde hay `title` que reemplazar, y lo
  que se escribe en un input nunca colapsa. `tests/test_texto_visible.py` lo hace cumplir: si
  agregás un `font-size: 0`, agregá el `[title]`.

## Checklist pre-push

```bash
uv run pytest -q
uv run ruff check .
uv run ty check .
uv run uvicorn api:app --port 8000   # y probar http://localhost:8000/ a mano
```

- Tests: `✓`
- Lint: `✓`
- Type-check: `✓`
- Prueba local (backend + frontend): `✓`
- Commit message convencional (`feat:`, `fix:`, `chore:`, `docs:`): `✓`
- Push → CI pasa → Deploy → Verificar en producción: `✓`
