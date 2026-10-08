# PurpleMD

[![Python](https://img.shields.io/badge/python-3.13%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-E93E4A?logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![Demo](https://img.shields.io/badge/demo-purplemd.onrender.com-7C3AED)](https://purplemd.onrender.com/)

Editor de markdown con backend **FastAPI**, frontend en HTML, CSS y
JavaScript vanilla (sin frameworks ni build), un solo proceso y un solo
contenedor. Cada nota es un archivo `*.md` con subcarpetas, y la vista
previa se renderiza en el backend con `markdown-it-py`.

Por defecto todo vive en `{PURPLEMD_DIR}/projects/{proyecto}/`. Con
credenciales de Google, cada cuenta escribe en su propia carpeta —o en
**su** Google Drive— y el sitio pide entrar antes de mostrar nada
(see [docs/AUTH.md](docs/AUTH.md)).

Demo en vivo: [purplemd.onrender.com](https://purplemd.onrender.com/) ·
Swagger: [/docs](https://purplemd.onrender.com/docs) ·
estado: [/health](https://purplemd.onrender.com/health).

Es una alternativa mínima a editores pesados: sin dependencias en el
cliente, sin autoguardado, y con acceso opcional vía Google.

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
- Al arrancar crea el proyecto **Bienvenida** con sus notas
  `nota-de-bienvenida`, `tutorial` y **`mcp`** si faltan —nunca pisa lo que ya
  existe—.
- Enlaces entre notas desde la vista previa: `[texto](ruta)` abre esa
  nota del proyecto activo (es como viaja la bienvenida a su tutorial);
  los enlaces externos quedan para el navegador.
- Servidor **MCP** integrado para que clientes compatibles con MCP puedan
consultar y gestionar proyectos y notas mediante herramientas.
- **Acceso con Google (opcional)**: con tres variables de entorno, el
  sitio muestra una pantalla de entrada y cada cuenta ve solo lo suyo.
  Authorization Code + PKCE, cookie firmada de 30 días y los tokens de
  Google guardados en disco con permisos `0600`.
- **Google Drive como backend (opcional)**: `PURPLEMD_STORAGE=drive`
  guarda los proyectos en la carpeta oculta `appDataFolder` de la cuenta
  de cada usuario, con reintentos ante límite de cuota.
- **Modo invitado (sin cuenta)**: la pantalla de acceso ofrece
  «Continuar sin cuenta» — todo vive en `localStorage` del navegador,
  el servidor no recibe ni conserva nada.
- **Política de Privacidad** y **Condiciones del Servicio** disponibles
  en la pantalla de acceso (`/privacy`, `/terms`).

## Qué no hace hoy

- Grafos ni wikilinks · colaboración en tiempo real · sincronización
  entre dispositivos · plugins · autoguardado · mover contenido entre
  proyectos · deshacer de borrados · adjuntos (solo texto markdown).
- **Sin credenciales de Google sigue sin haber autenticación**: cada
  navegador ve sus proyectos por un prefijo en el nombre, y la API no
  tiene usuarios ni tokens propios.
- **El modo invitado usa `localStorage`**: no es un backend real, no hay
  cifrado en reposo y los datos se pierden si se limpia el navegador.

## MCP

Endpoint: `/mcp`

PurpleMD incluye un servidor MCP integrado en la misma aplicación FastAPI, utilizando Streamable HTTP.

Actualmente expone herramientas para consultar y gestionar proyectos y
notas:

- **list_projects**
- **get_project_tree**
- **read_note**
- **create_note**
- **update_note**
- **move_note**
- **delete_note**
- **search_notes**
- **create_project**
- **delete_project**

El servidor MCP se inicia automáticamente junto con PurpleMD; no es
necesario ejecutar un proceso adicional.

Con acceso por Google encendido, `/mcp` pide un token propio en la
cabecera `X-PurpleMD-Token` (variable `PURPLEMD_MCP_TOKEN`), y con
`PURPLEMD_STORAGE=drive` queda apagado del todo: un cliente externo no
puede apuntar al Drive de una cuenta concreta.

La nota `mcp` del proyecto **Bienvenida** incluye guía completa de
configuración (Claude Desktop, clientes MCP, desarrollo local).

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

### Con acceso de Google (opcional)

```bash
export GOOGLE_CLIENT_ID=...
export GOOGLE_CLIENT_SECRET=...
export PURPLEMD_SECRET_KEY=$(openssl rand -hex 32)
uv run uvicorn api:app --reload
```

Con las tres variables el sitio pasa a pedir entrar. Si falta alguna, la
app se comporta exactamente igual que sin integración y avisa en el log.
Pasos en Google Cloud, alcance OAuth y troubleshooting:
[docs/AUTH.md](docs/AUTH.md).

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
| Buscar / reemplazar | Barra de formato o `Ctrl`/`Cmd`+`F` / `Ctrl`/`Cmd`+`H` |
| Deshacer / rehacer | Barra de formato o `Ctrl`/`Cmd`+`Z` / `Ctrl`/`Cmd`+`Y` |
| Cambiar de vista | Segmentado de la barra o menú ☰ → *Visualizador* |
| Descargar .md | Menú ☰ / *Menú ▾* → *Descargar .md* |
| Exportar PDF o ZIP | Menú ☰ / *Menú ▾* → *Exportar .pdf* / *Exportar .zip* |
| Compartir / ver el repo | Menú ☰ / *Menú ▾* → *Compartir PurpleMD* / *Ver en GitHub* |
| Crear o importar | Explorador (proyectos, *Importar .md* / *.zip*) |
| Cerrar lo que esté abierto | `Escape` |

> Superficies: en pantallas angostas (menos de 48rem) todo vive en el
> menú **☰**; desde 48rem la barra superior muestra el visualizador y el
> menú **Menú ▾**. La nota `tutorial` que crea la app incluye la
> tabla de atajos completa.

## Almacenamiento

`PURPLEMD_STORAGE=filesystem` (por defecto: escrituras atómicas en
`{PURPLEMD_DIR}/projects/`), `=memory` (solo RAM, se pierde al
reiniciar — lo que usa la demo de Render) o `=drive` (el Google Drive de
cada cuenta, exige login). Con sesión, `filesystem` escribe en
`{PURPLEMD_DIR}/users/{sha256(sub)}/projects/` para que dos cuentas no
se pisen. Detalle en
[docs/ARQUITECTURA.md](docs/ARQUITECTURA.md#backends-de-almacenamiento).

## API

20 operaciones en 13 rutas, con referencia interactiva en `/docs`, más
cuatro rutas de sesión (`/api/auth/*`) que no aparecen en el esquema.
Tabla completa, cuerpos, errores y límites en
[docs/API.md](docs/API.md).

## Documentación

- 🔑 [docs/AUTH.md](docs/AUTH.md) — acceso con Google, Drive y MCP
- 📄 [docs/API.md](docs/API.md) — endpoints, cuerpos, errores y límites
- 🏗️ [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) — datos, backends y frontend
- ♿ [docs/ACCESIBILIDAD.md](docs/ACCESIBILIDAD.md) — contraste, foco, teclado
- ⚙️ [docs/DESARROLLO.md](docs/DESARROLLO.md) — pruebas, CI, contenedor, Render
- 🤝 [CONTRIBUTING.md](CONTRIBUTING.md) — cómo contribuir (commits convencionales, checklist, CoC)

## Licencia

Distribuido bajo la licencia [MIT](LICENSE).
