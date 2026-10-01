# PurpleMD

[![Python](https://img.shields.io/badge/python-3.13%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-E93E4A?logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)

Editor de markdown con backend **FastAPI**, frontend en HTML, CSS y
JavaScript vanilla, un solo proceso y un solo contenedor. Todo el
contenido vive en `{PURPLEMD_DIR}/projects/{proyecto}/`: cada nota es un
archivo `*.md` dentro de un proyecto, con subcarpetas, y la vista
previa se renderiza en el backend con `markdown-it-py`.

Es una alternativa mínima a editores pesados. Qué hace hoy, qué no hace
y hasta dónde llegan sus límites están listados abajo.

## Qué hace hoy

- Crear y leer proyectos y notas, y reemplazar el contenido de una nota,
  desde la interfaz o desde la API.
- Renombrar proyectos; renombrar y mover notas y carpetas dentro del
  mismo proyecto, sin tocar el contenido.
- Eliminar proyectos (con todo su contenido, recursivamente), notas y
  carpetas.
- Árbol de carpetas por proyecto: subcarpetas plegables con notas
  anidadas, carpetas primero y notas después.
- Vista previa en vivo: el backend convierte markdown a HTML (CommonMark
  más tablas, tachado y task lists) y el cliente lo pide con debounce.
- Escapar el HTML crudo: un `<script>` escrito en la nota se muestra
  como texto y no se ejecuta (`renderer.py`, `html: False`).
- Guardado manual con el botón «Guardar» o `Ctrl`/`Cmd`+`S`, con
  indicador de cambios sin guardar, y descarga de la nota abierta como
  archivo `.md`.
- Validación de nombres y rutas (sin path traversal, hasta 10 segmentos
  y 200 bytes por ruta) y de tamaños (1 MB por nota, 200 KB por render).
- Escrituras atómicas: si el proceso muere a mitad de escritura, la nota
  anterior queda intacta. Renombres y movimientos también son atómicos
  dentro del mismo filesystem.
- Nota de bienvenida: el proyecto **Bienvenida** con la nota
  `primeros-pasos` se crea si falta y es la que se abre por defecto al
  arrancar.
- `GET /health` con el estado real del servicio en el body.
- Frontend servido por el mismo proceso, sin build ni dependencias de
  JavaScript.
- Imagen de contenedor en tres etapas con sonda de salud.
- Despliegue en Render con `render.yaml`.

## Qué no hace hoy

- Grafos ni wikilinks.
- Autenticación: no hay usuarios ni tokens. El aislamiento lo da el
  namespace de cada navegador (el prefijo `u_…` que lleva cada proyecto
  y que el frontend filtra al listar): cada navegador ve solo sus
  proyectos. No es una sesión: quien hable con la API directamente ve
  todos.
- Colaboración en tiempo real.
- Sincronización entre dispositivos.
- Plugins ni extensiones.
- Búsqueda de texto en las notas.
- Autoguardado: los cambios solo se escriben en disco con «Guardar» o
  `Ctrl`/`Cmd`+`S`.
- Mover contenido de un proyecto a otro: los `PATCH` de notas y
  directorios solo aceptan rutas dentro del mismo proyecto.
- Borrado sin confirmación ni deshacer: los `DELETE` responden en
  seguida y no se revierten; la confirmación la hace el frontend.
- Adjuntos: solo texto markdown, sin subida de archivos.
- Export a HTML (ver «No implementado»).
- Templates (ver «No implementado»).
- Servidor MCP (ver «No implementado»).

## Backends de almacenamiento

PurpleMD soporta dos backends de persistencia, seleccionables con la variable
de entorno `PURPLEMD_STORAGE`:

| Backend | Variable | Descripción |
|---|---|---|
| **filesystem** | `PURPLEMD_STORAGE=filesystem` (default) | Persistencia en disco local (`{PURPLEMD_DIR}/projects/`). Escrituras atómicas, sobrevive a restarts del proceso. |
| **memory** | `PURPLEMD_STORAGE=memory` | Solo RAM. Se pierde en cualquier restart (deploy, crash, scale to 0). Ideal para entornos efímeros como Render free tier. |

El frontend usa **localStorage** para generar un namespace único por navegador
(`u_AbCdEf12`). Cada usuario ve solo sus proyectos (`u_AbCdEf12_proyecto`),
aislando datos casuales sin autenticación real. El prefijo es un detalle de
transporte: junto a un nombre nunca se muestra (la lista, el título de la
nota, los formularios de renombrar y los avisos de eliminar lo quitan) y se
agrega solo al armar cada pedido a la API. La única pista del namespace en
pantalla es el badge `👤 u_AbCdEf12` de la barra superior.

### Exportar / Importar proyecto (.zip)

- **Exportar**: `GET /api/projects/{project}/export` → descarga `.zip` con
  `.purplemd.json` (metadata) + todos los `.md` preservando estructura de carpetas.
- **Importar**: `POST /api/projects/{project}/import` (multipart, `.zip`) →
  restaura notas, crea carpetas, reporta `creadas`, `actualizadas`, `omitidas`, `errores`.
- El `.zip` es portable: las notas viajan con rutas relativas al proyecto,
  sin el prefijo de namespace, y al importar el nombre del proyecto sale de
  la URL, no de la metadata. La metadata `.purplemd.json` sí guarda el
  nombre tal cual (con el prefijo), pero el import solo lee su versión, así
  que el archivo puede migrarse entre usuarios e instancias.

## Requisitos

- Python 3.13 o superior.
- [uv](https://docs.astral.sh/uv/) para el entorno virtual y las
  dependencias.
- Librerías de sistema para `weasyprint` (Pango, HarfBuzz y Fontconfig):
  `api.py` importa `weasyprint` al arrancar y sin ellas el proceso no
  levanta. El `Dockerfile` y el job de tests del CI ya las instalan.

## Instalación

```bash
uv sync
```

Crea `.venv` e instala las dependencias de producción (`fastapi`,
`uvicorn`, `markdown-it-py`, `mdit-py-plugins`, `pygments`,
`weasyprint` y `python-multipart`) y las de desarrollo (`pytest`,
`httpx`, `ruff` y `ty`). Las versiones quedan fijadas en `uv.lock`.

## Arranque en desarrollo

```bash
uv run uvicorn api:app --reload
```

El servidor queda en `http://127.0.0.1:8000`. Rutas reales:

| Ruta | Qué responde |
|---|---|
| `/` | Frontend (`static/index.html`). |
| `/static/css/style.css` | Hoja de estilos del frontend. |
| `/static/js/app.js` | Módulo JavaScript del frontend. |
| `/docs` | Documentación interactiva (Swagger UI). |
| `/redoc` | Documentación alternativa (Redoc). |
| `/openapi.json` | Esquema OpenAPI. |
| `/health` | Estado del servicio. |

Las rutas de datos (`/api/...`) están en la tabla de endpoints.

## Estructura de datos

Todo el contenido vive bajo `{PURPLEMD_DIR}/projects/`, con proyectos y
subcarpetas. No hay notas sueltas:

```text
local/purplemd/
└── projects/
    ├── cuaderno/
    │   ├── portada.md
    │   └── diseños/
    │       └── logo.md
    └── otro-proyecto/
        └── idea.md
```

- Cada proyecto es un directorio dentro de `projects/` y cada nota, un
  archivo `*.md` en cualquier nivel del proyecto. Un archivo suelto en
  `projects/` (fuera de un proyecto) no aparece en ningún listado.
- La ruta de la nota (`diseños/logo`) se indica al crearla y la capa de
  persistencia agrega la extensión `.md`.
- Lo que el editor no creó (archivos que no son `*.md`, nombres
  inválidos, directorios ocultos) se omite en los listados en vez de
  romperlos.
- Renombrar un proyecto mueve su directorio con todo su contenido;
  eliminarlo lo borra recursivamente.

## Endpoints

| Método | Ruta | Códigos | Descripción |
|---|---|---|---|
| `GET` | `/api/projects` | `200` | `{projects: [{name, modified}]}`, del más reciente al más antiguo. |
| `POST` | `/api/projects` | `201`, `409`, `422` | Crea un proyecto. |
| `PATCH` | `/api/projects/{project}` | `200`, `404`, `409`, `422` | Renombra el proyecto (recibe `{"name"}`). |
| `DELETE` | `/api/projects/{project}` | `204`, `404`, `422` | Borra el proyecto con todo su contenido, recursivamente. |
| `GET` | `/api/projects/{project}/tree` | `200`, `404`, `422` | Árbol del proyecto: carpetas primero y notas después, cada grupo en orden alfabético. |
| `POST` | `/api/projects/{project}/notes` | `201`, `404`, `409`, `422` | Crea una nota y las carpetas intermedias que falten. |
| `GET` | `/api/projects/{project}/notes/{path}` | `200`, `404`, `422` | Devuelve `{project, path, content, modified}`. |
| `PUT` | `/api/projects/{project}/notes/{path}` | `200`, `404`, `422` | Reemplaza todo el contenido (recibe `{"content"}`). |
| `PATCH` | `/api/projects/{project}/notes/{path}` | `200`, `404`, `409`, `422` | Renombra o mueve la nota (recibe `{"path"}`). |
| `DELETE` | `/api/projects/{project}/notes/{path}` | `204`, `404`, `422` | Borra la nota; deja las carpetas vacías. |
| `GET` | `/api/projects/{project}/notes/{path}/pdf` | `200`, `404`, `422` | Exporta la nota como PDF. `?sin_marca=1` omite el pie «Generado con PurpleMD ♥»: es una preferencia, no una protección. |
| `PATCH` | `/api/projects/{project}/dirs/{path}` | `200`, `404`, `409`, `422` | Renombra o mueve el directorio con su contenido. |
| `DELETE` | `/api/projects/{project}/dirs/{path}` | `204`, `404`, `409`, `422` | Borra el directorio; con `?recursive=true`, con todo su contenido. |
| `GET` | `/api/projects/{project}/export` | `200`, `404`, `422` | Exporta el proyecto completo como `.zip`. |
| `POST` | `/api/projects/{project}/import` | `200`, `422` | Importa un proyecto desde `.zip` (multipart/form-data); lo crea si no existe. |
| `POST` | `/api/render` | `200`, `422` | Convierte markdown en HTML. |
| `GET` | `/api/notifications` | `200` | Notificaciones no leídas en `{"notifications": [{id, titulo, mensaje}]}`. |
| `POST` | `/api/notifications` | `201`, `422` | Crea una notificación (recibe `{"titulo", "mensaje"}`). |
| `POST` | `/api/notifications/{notif_id}/read` | `204` siempre | Marca la notificación como leída; con un id desconocido también `204`. |
| `GET` | `/health` | `200` siempre | `{"estado": "ok"}` o `{"estado": "degradado"}`. |

`PUT` y `PATCH` no hacen lo mismo sobre una nota:

- `PUT .../notes/{path}` guarda el contenido: reemplaza todo el texto de
  la nota. Es el que usa el botón «Guardar».
- `PATCH .../notes/{path}` no toca el contenido: renombra o mueve la
  nota a otra ruta relativa del proyecto.

Los dos `PATCH` (notas y directorios) consumen el mismo cuerpo, con la
ruta destino completa dentro del proyecto.

Borrado de directorios:

- Sin `recursive=true` solo se borran directorios vacíos; uno no vacío
  responde `409` con «el directorio 'X' no está vacío; se necesita
  recursive=true para borrarlo con todo su contenido».
- Con `?recursive=true` borra el directorio con todo su contenido. El
  endpoint responde directo: la confirmación destructiva la hace el
  frontend antes de llamar.
- `DELETE` no es idempotente: el segundo `DELETE` del mismo recurso
  responde `404`. `PATCH` al mismo nombre o ruta responde `200`.

Cuerpos de los requests:

- `POST /api/projects` y `PATCH /api/projects/{project}`:
  `{"name": "..."}`.
- `POST /api/projects/{project}/notes`: `{"path": "...",
  "content": "..."}`. Los dos campos son obligatorios; uno faltante o un
  campo no previsto da `422`.
- `PUT .../notes/{path}`: `{"content": "..."}`.
- `PATCH` de notas y de directorios: `{"path": "..."}`.
- `POST /api/render`: `{"markdown": "..."}`.

Los errores usan `{"detail": "..."}` con mensajes en español. Las
validaciones de Pydantic vienen como lista de objetos con `loc` y `msg`.
Un error no previsto responde `500` con
`{"detail": "error interno al procesar la solicitud"}`, sin stack trace.

Cuándo cae cada código de error:

- `404`: recurso inexistente (proyecto, nota o directorio).
- `409`: crear un proyecto o una nota que ya existe; un `PATCH` cuyo
  destino está ocupado; y `DELETE` de un directorio no vacío sin
  `recursive=true`. En ningún caso se pisa contenido.
- `422`: nombre, ruta o destino inválido (incluye rutas que escapan del
  proyecto con `../` y un directorio que terminaría dentro de sí mismo
  o de un ancestro), contenido por encima de 1 MB, markdown por encima
  de 200 KB, y campos faltantes o de más.

Ejemplos:

```bash
curl -s -X POST http://127.0.0.1:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{"name":"cuaderno"}'
```

```bash
curl -s -X POST http://127.0.0.1:8000/api/projects/cuaderno/notes \
  -H "Content-Type: application/json" \
  -d '{"path":"diseños/logo","content":"hola **mundo**"}'
```

```bash
curl -s -X PATCH http://127.0.0.1:8000/api/projects/cuaderno \
  -H "Content-Type: application/json" \
  -d '{"name":"cuaderno-2026"}'
```

```bash
curl -s -X POST http://127.0.0.1:8000/api/render \
  -H "Content-Type: application/json" \
  -d '{"markdown":"# hola"}'
```

## Límites

- Nota: `MAX_BYTES = 1_048_576` (1 MB) en
  `purplemd_storage/protocol.py`. Cuenta bytes
  UTF-8, no caracteres, y aplica al crear y al guardar.
- Render: `MAX_RENDER_BYTES = 204_800` (200 KB) en `api.py`, por request
  a `/api/render`.
- Nombres de proyecto y segmentos de ruta: sin separadores de ruta, sin
  `..`, sin punto inicial; solo letras y dígitos (acepta tildes y `ñ`),
  espacio, `_` y `-`. Se acepta con o sin `.md`, y la extensión se
  descarta.
- Rutas de nota: hasta `MAX_PROFUNDIDAD = 10` segmentos (nueve
  subcarpetas más la nota) y `MAX_RUTA_BYTES = 200` bytes UTF-8.
- Directorio de datos: `PURPLEMD_DIR`, por defecto `./local/purplemd`.
  Se crea si no existe y se resuelve en cada llamada. Todo su contenido
  vive en `projects/{proyecto}/`.
- El listado de proyectos omite los archivos sueltos de `projects/` y
  los directorios con nombre inválido; el árbol omite lo que no sea un
  `*.md` con nombre válido.
- No hay límite de concurrencia ni de cantidad de proyectos o notas.
- `/health` responde `200` siempre y el estado real está en el body: una
  comprobación solo del código HTTP no detecta el fallo.

## Frontend

Compuesto por `static/index.html`, `static/css/style.css` y
`static/js/app.js` (módulo ES, sin dependencias externas).

- Tres paneles: explorador (proyectos y árbol), editor y vista previa.
- En pantallas angostas (menos de 48rem) el explorador no es una
  columna: arranca oculto y es un desplegable superpuesto que se abre
  con el botón «Explorador» de la barra superior, cae ancho completo
  justo debajo de ella (con scroll interno si el contenido es largo) y
  se cierra con `Escape`, al pulsar el botón de nuevo o al abrir una
  nota. Cambiar de proyecto no cierra el desplegable. Desde 48rem el
  explorador ya es columna (estrecha y solo iconos hasta 60rem, ancha
  desde ahí) y el botón «Explorador» no se ve.
- Menú «Más acciones» (☰): la superficie angosta (menos de 48rem) de
  vistas y archivo. Agrupa sus ítems en tres grupos con nombre,
  «Visualizador», «Archivo» y «Difusión». «Visualizador» ofrece tres
  opciones exclusivas como `menuitemradio` con `aria-checked`:
  «Editor y previsualización» (estado inicial), «Solo previsualización»
  y «Solo editor»; «Archivo» agrupa «Descargar .md» (con una nota
  abierta) y «Exportar .zip» (con proyecto activo), y «Difusión» lleva
  «Compartir PurpleMD», siempre disponible. El PDF no está en este
  menú: vive solo en «Exportar ▾», de la barra ancha. Al elegir una
  opción, `aria-checked` se sincroniza con `zona[data-vista]`, el menú
  se cierra y el foco vuelve al botón ☰ (igual que con `Escape`, que
  solo cierra). Ocultar es solo `display:none` en CSS: el DOM no se
  toca, así que el texto del editor, el HTML renderizado, el scroll y
  el cursor se conservan. `Guardar` y `Ctrl`/`Cmd`+`S` funcionan en las
  tres vistas. La vista no se persiste: al recargar vuelve al estado
  inicial, «Editor y previsualización».
- Barra de acciones (48rem o más): la superficie ancha, con un corte
  único de 48rem (768px) que oculta el ☰ y muestra, en ese orden, el
  segmentado de vistas («Radio Group» de la WAI-ARIA APG con HTML nativo:
  `fieldset` + `legend` oculto «Visualizador» + tres `radio`, sin
  `role="toolbar"`, que exigiría roving tabindex), «Descargar .md» y el
  menú «Exportar ▾» («Menu Button» de la APG con el mismo ciclo de vida
  que el ☰ y el panel anclado bajo su trigger, no a ancho completo, con
  «Exportar .pdf», «Marca de agua en el PDF», «Exportar .zip» y
  «Compartir PurpleMD» adentro). «Descargar .md» y «Exportar .zip» están
  en las dos superficies con la misma etiqueta y habilitación (una sola
  regla por acción, `data-accion`: nota abierta para descargar y
  proyecto activo para el zip); «Exportar .pdf» y la opción de marca de
  agua viven solo en la barra ancha, y el trigger «Exportar» se apaga
  cuando no hay ni nota ni proyecto. «Marca de agua en el PDF» es un
  `menuitemcheckbox` con `aria-checked` y ✓ visible: alterna un estado,
  no exporta, y por eso no depende de tener una nota abierta. El PDF sale
  con el pie «Generado con PurpleMD ♥» por defecto; con el ítem
  desactivado viaja `?sin_marca=1` y el backend omite ese pie (el número
  de página se mantiene: es paginación, no branding). **Es una
  preferencia, no una protección**: no hay autenticación, así que
  cualquiera puede pedir el parámetro. Si las etiquetas no
  entran, la barra envuelve en varias filas: nunca se truncan ni se
  achican y los targets siguen teniendo 44px (WCAG 2.5.5). Al cruzar el
  corte se cierra el menú del lado opuesto y, si el foco quedó en un
  control recién ocultado, pasa al primer control enfocable visible de
  la barra (WCAG 2.4.3).
- Regla de superficies: el explorador importa y crea; en angosto el menú
  ☰ descarga y exporta; en ancho la barra muestra vistas y descarga, y el
  menú `Exportar` reúne las exportaciones. Importar avisa su **éxito**
  con un toast y su **error** en `#importar-estado`, junto a los botones
  de la fila.
- Al arrancar se asegura la semilla de bienvenida: si el proyecto
  **Bienvenida** o la nota `primeros-pasos` faltan, los crea —nunca pisa
  el contenido ya existente, que el usuario puede editar o vaciar— y esa
  es la nota que se muestra por defecto. Solo si la semilla no se puede
  crear se vuelve al comportamiento previo: proyecto más reciente y
  ninguna nota abierta.
- Dos formularios de creación, de proyecto y de nota (esta última con
  ruta, p. ej. `diseños/logo`); los errores `404`, `409` y `422` se
  muestran ahí, en español y de forma persistente, junto al formulario
  que los provocó. El éxito, en cambio, se avisa con un toast que se
  retira solo («Proyecto «X» creado.», «Nota «r» creada.»).
- Feedback de cada operación: **éxito efímero, error persistente junto a
  su control** (Carbon + Material 3 + WCAG 2.2 SC 4.1.3). El éxito va a
  un toast apilado —la más reciente arriba, con un tope de 3 en pantalla,
  sin robar nunca el foco— que vive 6 segundos, con el auto-cierre en
  pausa mientras el puntero o el foco están sobre él (reanuda con el
  tiempo restante, no desde cero) y cancelable en cualquier momento con
  la X. Aparece abajo en pantallas angostas (menos de 48rem) y, desde
  48rem, arriba a la derecha y debajo de la barra superior. Les queda
  por encima el panel de acción (renombrar/eliminar), que abre con el
  foco en su control principal: un aviso transitorio nunca lo oculta por
  completo ni le intercepta el clic (WCAG 2.2 SC 2.4.11). Cada toast
  lleva `role="status"` con `aria-live="polite"` si es éxito, o
  `role="alert"` **sin auto-cierre** si es error: así los errores de
  exportación (que viven en la barra ☰/Exportar, que puede estar cerrada)
  solo los cierra la X. El error de importación no va al toast: queda en
  `#importar-estado`.
- Cada fila de proyecto, carpeta y nota tiene dos botones: renombrar y
  eliminar. Renombrar abre un formulario inline con la ruta actual (con
  el nombre del proyecto sin el prefijo de namespace; el botón dice
  «Renombrar» en proyectos y «Mover» en notas y carpetas);
  eliminar abre una confirmación inline con el aviso de lo que se
  pierde. No hay `alert()` ni `confirm()`.
- El backend borra sin preguntar: la confirmación es del frontend, que
  además bloquea la eliminación de una nota o carpeta si hay cambios sin
  guardar.
- Renombrar o mover una carpeta reescribe la ruta de la nota abierta si
  vivía adentro, sin tocar el contenido del editor.
- Con cambios sin guardar no deja cambiar de nota ni de proyecto, ni
  crear proyectos o notas.
- Carpetas plegables con `<details>`; el plegado se guarda por ruta y
  se reescribe cuando la carpeta cambia de lugar.
- El `Tab` del editor escribe dos espacios; `Shift`+`Tab` sale del
  textarea.
- La vista previa pide `POST /api/render` 400 ms después de la última
  tecla; con el panel de vista previa oculto no se pide nada, y al
  mostrarla de nuevo solo se pide si el texto cambió.
- Los HTML ya renderizados se cachean por hash del texto, con un tope de
  100 entradas; una respuesta vieja no pisa a una más nueva.
- Guardado manual (botón «Guardar» o `Ctrl`/`Cmd`+`S`): mientras hay
  cambios sin guardar no deja cambiar de nota. El botón «Descargar .md»
  arma el archivo en el cliente, sin endpoint de descarga; aparece en las
  dos superficies (barra desde 48rem e ítem del menú ☰) con el mismo
  manejador y la misma habilitación (`data-accion="descargar"`).
- No hay frameworks, bundlers ni librerías de JavaScript en el cliente:
  el render lo hace el backend.

## Pruebas

La suite está escrita con `unittest` (clases `TestCase`), se corre con
`pytest` y tiene 256 tests, más 155 subtests de `self.subTest()`:

- 95 en `tests/test_purplemd.py`.
- 94 en `tests/test_api.py`.
- 47 en `tests/test_storage.py`.
- 20 en `tests/test_renderer.py`.

```bash
uv run pytest -q
```

Lint y type checking:

```bash
uv run ruff check .
uv run ty check .
```

El frontend no tiene suite propia: casi todo lo que usa está cubierto por
`tests/test_api.py` (proyectos, notas, directorios, PDF y render); el
export/import de `.zip` y las tres rutas de `/api/notifications` todavía
no tienen tests.

El workflow `.github/workflows/ci.yml` define cinco jobs: consistencia
de versiones entre `Dockerfile`, `render.yaml` y `pyproject.toml`, lint,
type check, tests (instala Pango porque la suite exporta PDFs reales) y
build de imagen (`podman build --format docker` más un smoke test).

## Contenedor

La imagen se arma en tres etapas (`deps` → `build` → `final`) y corre
como usuario sin privilegios.

La etapa `final` instala las libs nativas que `weasyprint` abre al
importar (Pango, HarfBuzz y Fontconfig): `libpango-1.0-0`,
`libpangoft2-1.0-0` y `libharfbuzz-subset0`, la lista que la doc
oficial de WeasyPrint da para Debian con wheels. `api.py` importa
`weasyprint` al arrancar: sin esas libs `import api` falla y la imagen
no levanta.

### Build

```bash
podman build --format docker -t purplemd:local .
```

`--format docker` hace falta porque Podman genera imágenes en formato OCI
por defecto y ahí `HEALTHCHECK` se descarta con el warning
`HEALTHCHECK is not supported for OCI image format and will be ignored.
Must use 'docker' format`. En formato OCI, `podman inspect` devuelve
`State.Health = null`; con formato `docker` la sonda corre. La imagen
final pesa 237 MB.

### Run

```bash
podman run -d --name purplemd -p 8002:8000 -e PORT=8000 \
  -v "$PWD/local/purplemd:/app/local/purplemd" purplemd:local
```

El puerto del host es `8002` porque el `8000` lo puede estar usando el
dev server local (`uvicorn --reload`): el ejemplo tiene que poder correr
tal cual. El contenedor sigue escuchando en `8000` (`PORT=8000`); solo
cambia el mapeo del host.

El contenedor corre como usuario `purplemd` (uid 10001) y `PORT` tiene
por defecto `8000`. Los datos viven en el volumen, por lo que sobreviven
a reinicios y a rebuilds de la imagen.

### Verificación

```bash
podman inspect purplemd --format '{{.State.Health.Status}}'
curl -s http://127.0.0.1:8002/health
```

Usá `127.0.0.1` y no `localhost`: `localhost` puede resolver primero a
`::1` (IPv6) y el forwarder de red de Podman (`pasta`) solo escucha en
IPv4, con lo que `curl` contra `localhost` falla.

La sonda es `python -c` con `urllib`, porque la imagen no trae `curl`.
Lee el body de `/health` y exige `estado == "ok"`: el código HTTP es
`200` también cuando el directorio de datos no funciona. Corre cada 30 s
con `--start-period=10s`.

### Permisos del directorio de datos

Limitación conocida, verificada con Podman rootless:

- El contenedor escribe con uid 10001 y en el host esos archivos quedan
  con uid `110000` y modo `600`. El usuario del host no puede leer el
  contenido (`cat` devuelve `Permission denied`); dentro del contenedor
  se lee normal.
- El directorio montado necesita permiso de escritura para «otros»
  (`chmod 777`). Con `755` el healthcheck responde
  `{"estado": "degradado"}` y `POST /api/projects` responde `500`; con
  `chmod 777` pasa a `ok` y `201`.
- Solución posible, no implementada: levantar el contenedor con
  `--userns=keep-id` o escribir los archivos con modo `0644`.

## Despliegue en Render

[`render.yaml`](render.yaml) configura un servicio (`name: purplemd`)
con el buildpack de Python (`runtime: python`), no con el `Dockerfile`:

```bash
uv sync --no-dev
uv run uvicorn api:app --host 0.0.0.0 --port $PORT
```

Con `PYTHON_VERSION=3.13`.

Advertencia: `render.yaml` fija `PURPLEMD_STORAGE=memory`, así que en
Render no se escribe nada en disco: las notas viven en RAM y se pierden
en cualquier restart del proceso (deploy, crash, scale to 0). El modo
`filesystem` (el defecto, escribe en `./local/purplemd`) no está activo
ahí porque el disco de Render es efímero y no se agregó un volumen
montado sobre esa ruta porque no se pudo verificar.

## No implementado

No hay código ni tests para nada de esto hoy, y no forma parte del
valor del proyecto:

- Servidor MCP.
- Templates.
- Export a HTML.

## Licencia

Distribuido bajo la licencia [MIT](LICENSE).
