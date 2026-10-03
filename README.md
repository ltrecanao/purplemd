# PurpleMD

[![Python](https://img.shields.io/badge/python-3.13%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-E93E4A?logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![Demo](https://img.shields.io/badge/demo-purplemd.onrender.com-7C3AED)](https://purplemd.onrender.com/)

Editor de markdown con backend **FastAPI**, frontend en HTML, CSS y
JavaScript vanilla (sin frameworks ni build), un solo proceso y un solo
contenedor. Todo el contenido vive en `{PURPLEMD_DIR}/projects/{proyecto}/`:
cada nota es un archivo `*.md` con subcarpetas, y la vista previa se
renderiza en el backend con `markdown-it-py`.

Demo en vivo: [purplemd.onrender.com](https://purplemd.onrender.com/) ·
Swagger: [/docs](https://purplemd.onrender.com/docs) ·
estado: [/health](https://purplemd.onrender.com/health).

Es una alternativa mínima a editores pesados: sin cuentas, sin
dependencias en el cliente y sin autoguardado.

## Qué hace hoy

- Crear, leer, renombrar, mover y eliminar proyectos, carpetas y notas,
  desde la interfaz o desde la API.
- Vista previa en vivo renderizada en el backend (CommonMark + tablas,
  tachado y task lists), con el HTML crudo escapado: un `<script>` se
  muestra como texto y no se ejecuta.
- Guardado manual (botón «Guardar» o `Ctrl`/`Cmd`+`S`) con indicador de
  cambios sin guardar.
- Exportar la nota como `.md` o PDF (siempre con el pie «Generado con
  PurpleMD ♥») y el proyecto completo como `.zip`, con su import.
- Árbol de carpetas plegable, validación de rutas y tamaños (sin path
  traversal; 1 MB por nota), escrituras atómicas y `GET /health`.
- Al arrancar crea el proyecto **Bienvenida** con su nota
  `primeros-pasos` si falta —nunca pisa lo que ya existe—.

## Qué no hace hoy

- Grafos ni wikilinks · autenticación (cada navegador ve solo sus
  proyectos, pero la API no tiene usuarios ni tokens) · colaboración en
  tiempo real · sincronización entre dispositivos · plugins · búsqueda
  de texto · autoguardado · mover contenido entre proyectos · deshacer
  de borrados · adjuntos (solo texto markdown).
- Tampoco hay servidor MCP ni export a HTML: no hay código ni tests para
  eso y no forma parte del valor del proyecto.

## Arranque rápido

### Desarrollo

Requisitos: Python 3.13+, [uv](https://docs.astral.sh/uv/) y las libs
de sistema de `weasyprint` (Pango, HarfBuzz y Fontconfig — el
`Dockerfile` y el CI ya las instalan).

```bash
uv sync
uv run uvicorn api:app --reload
```

Queda en `http://127.0.0.1:8000`: frontend en `/`, Swagger en `/docs`,
Redoc en `/redoc` y estado en `/health`.

### Contenedor

```bash
podman build --format docker -t purplemd:local .
podman run -d --name purplemd -p 8002:8000 -e PORT=8000 \
  -v "$PWD/local/purplemd:/app/local/purplemd" purplemd:local
```

`--format docker` hace falta para que la sonda `HEALTHCHECK` no se
descarte (el formato OCI la ignora). Verificación, permisos y detalle:
[docs/DESARROLLO.md](docs/DESARROLLO.md#contenedor).

## Uso esencial

| Acción | Dónde |
|---|---|
| Guardar | Botón *Guardar* o `Ctrl`/`Cmd`+`S` |
| Cambiar de vista | Segmentado de la barra o menú ☰ → *Visualizador* |
| Descargar .md | Menú ☰ / *Menú ▾* → *Descargar .md* |
| Exportar PDF o ZIP | Menú ☰ / *Menú ▾* → *Exportar .pdf* / *Exportar .zip* |
| Compartir / ver el repo | Menú ☰ / *Menú ▾* → *Compartir PurpleMD* / *Ver en GitHub* |
| Crear o importar | Explorador (proyectos, *Importar .md* / *.zip*) |
| Cerrar lo que esté abierto | `Escape` |

> Superficies: en pantallas angostas (menos de 48rem) todo vive en el
> menú **☰**; desde 48rem la barra superior muestra el visualizador y el
> menú **Menú ▾**. La nota de bienvenida que abre la app incluye la
> tabla de atajos.

## Almacenamiento

`PURPLEMD_STORAGE=filesystem` (por defecto: escrituras atómicas en
`{PURPLEMD_DIR}/projects/`) o `=memory` (solo RAM, se pierde al
reiniciar — lo que usa la demo de Render). Detalle en
[docs/ARQUITECTURA.md](docs/ARQUITECTURA.md#backends-de-almacenamiento).

## API

20 operaciones en 13 rutas, con referencia interactiva en `/docs`.
Tabla completa, cuerpos, errores y límites en
[docs/API.md](docs/API.md).

## Documentación

- 📄 [docs/API.md](docs/API.md) — endpoints, cuerpos, errores y límites
- 🏗️ [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) — datos, backends y frontend
- ♿ [docs/ACCESIBILIDAD.md](docs/ACCESIBILIDAD.md) — contraste, foco, teclado
- ⚙️ [docs/DESARROLLO.md](docs/DESARROLLO.md) — pruebas, CI, contenedor, Render
- 🤝 [CONTRIBUTING.md](CONTRIBUTING.md) — cómo contribuir (commits convencionales, checklist, CoC)

## Licencia

Distribuido bajo la licencia [MIT](LICENSE).
