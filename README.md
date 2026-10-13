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
- El espacio de trabajo arranca **vacío**: no crea proyectos ni notas de
  ejemplo. Un estado inicial ofrece crear el primer proyecto o empezar
  con una de las **nueve plantillas** (elegibles al crear un proyecto,
  nunca instalan nada solas).
- Enlaces entre notas desde la vista previa: `[texto](ruta)` abre esa
  nota del proyecto activo;
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
- **Documentación de uso** en `/wiki`: primeros pasos, editor, proyectos
  y plantillas, cuenta y almacenamiento, e integración MCP.

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

El servidor MCP se inicia automáticamente junto con PurpleMD; no es
necesario ejecutar un proceso adicional.

Con acceso por Google encendido, `/mcp` pide el token que emite la
propia app para la cuenta («menú → Servidor MCP», o
`POST /api/auth/mcp-token`) en la cabecera `X-PurpleMD-Token` y sirve
los datos de esa cuenta —también con `PURPLEMD_STORAGE=drive`. Sin
credenciales de Google, el token es la variable de entorno
`PURPLEMD_MCP_TOKEN` y el alcance es la raíz compartida. Sin token
responde `403`; con un token inválido o vencido, `401`.

La wiki (`/wiki#mcp`) y el panel «Servidor MCP» de la app incluyen la
guía de configuración (Claude Desktop, clientes MCP, desarrollo local).

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
| Cambiar de vista | Menú *Vista ▾* (editor y previsualización, solo previsualización, solo editor) |
| Formato menos frecuente | Menú *Más ▾* de la barra de formato |
| Sincronizar | Menú *Menú ▾* → *Sincronizar* |
| Descargar .md | Menú *Menú ▾* → *Descargar .md* |
| Exportar PDF o ZIP | Menú *Menú ▾* → *Exportar .pdf* / *Exportar .zip* |
| Compartir / ver el repo | Menú *Menú ▾* → *Compartir PurpleMD* / *Ver en GitHub* |
| Tema claro / oscuro | Botón ☀ / 🌙 de la barra superior |
| Crear o importar | Explorador (proyectos, *Importar .md* / *.zip*) |
| Plantillas | Explorador → *Empezar con una plantilla* (al crear un proyecto) |
| Documentación | Menú *Menú ▾* → *Documentación* (`/wiki`) |
| Cerrar lo que esté abierto | `Escape` |

> Superficies: una sola por menú en cualquier ancho —*Vista ▾*, *Menú ▾*
> y *Más ▾*— con el panel posicionado para no salirse de la pantalla.
> La tabla de atajos completa vive en la wiki (`/wiki#atajos`).

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

## Licencia y uso

PurpleMD es **código visible** (source-available). El código fuente está
público para inspección y auditoría, pero con todos los derechos reservados.

### Uso permitido sin autorización

- **Particulares**: uso libre y gratuito para uso personal no comercial.
- **Inspección pública**: lectura y auditoría del código fuente.
- **Evaluación técnica**: prueba interna sin fines de lucro.

### Uso que requiere acuerdo comercial

Cualquier uso corporativo, comercial o integración en productos de
terceros requiere un **plan Enterprise** o acuerdo comercial previo:

- Integración en productos o servicios de terceros.
- Uso dentro de organizaciones con fines comerciales.
- Modificación o distribución del código.
- Creación de trabajos derivados.

**Contacto empresarial**: [purple.empresas@proton.me](mailto:purple.empresas@proton.me?subject=Consulta%20Enterprise%20-%20PurpleMD)

### Restricciones

Sin autorización previa por escrito se prohíbe modificar, redistribuir,
usar comercialmente o realizar ingeniería inversa de este software.

Ver [LICENSE](LICENSE) para el texto legal completo.
