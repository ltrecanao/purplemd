# API de PurpleMD

El backend expone la API bajo `/api/...` más `/health`. La referencia
interactiva vive en `/docs` (Swagger UI) y `/redoc` (Redoc), y el
esquema completo en `/openapi.json`. En la instancia pública las mismas
rutas cuelgan de `https://purplemd.onrender.com`.

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
| `GET` | `/api/projects/{project}/notes/{path}/pdf` | `200`, `404`, `422` | Exporta la nota como PDF, siempre con el pie «Generado con PurpleMD ♥». |
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

## Recursos estáticos

Además de `/api`, el servidor monta dos directorios de solo lectura:

| Ruta | Contenido |
|---|---|
| `/static/...` | Frontend: `index.html`, `css/`, `js/`, `assets/`. |
| `/plantillas/...` | Plantillas de documentos (`.md`) y su manifiesto `indice.json`. |

Las plantillas no viven en el código: el frontend las lee de
`/plantillas` y las copia al proyecto «Plantillas» en el primer
arranque (idempotente y no destructiva). Agregar una plantilla es
dropear el `.md` en `plantillas/{empresas,clientes}/` y sumarlo al
manifiesto; un test del CI falla si el directorio y el manifiesto
divergen.

## Borrado de directorios

- Sin `recursive=true` solo se borran directorios vacíos; uno no vacío
  responde `409` con «el directorio 'X' no está vacío; se necesita
  recursive=true para borrarlo con todo su contenido».
- Con `?recursive=true` borra el directorio con todo su contenido. El
  endpoint responde directo: la confirmación destructiva la hace el
  frontend antes de llamar.
- `DELETE` no es idempotente: el segundo `DELETE` del mismo recurso
  responde `404`. `PATCH` al mismo nombre o ruta responde `200`.

## Cuerpos de los requests

- `POST /api/projects` y `PATCH /api/projects/{project}`:
  `{"name": "..."}`.
- `POST /api/projects/{project}/notes`: `{"path": "...",
  "content": "..."}`. Los dos campos son obligatorios; uno faltante o un
  campo no previsto da `422`.
- `PUT .../notes/{path}`: `{"content": "..."}`.
- `PATCH` de notas y de directorios: `{"path": "..."}`.
- `POST /api/render`: `{"markdown": "..."}`.

## Errores

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

## Ejemplos

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

## Exportar / Importar proyecto (.zip)

- **Exportar**: `GET /api/projects/{project}/export` → descarga `.zip` con
  `.purplemd.json` (metadata) + todos los `.md` preservando estructura de carpetas.
- **Importar**: `POST /api/projects/{project}/import` (multipart, `.zip`) →
  restaura notas, crea carpetas, reporta `creadas`, `actualizadas`, `omitidas`, `errores`.
- El `.zip` es portable: las notas viajan con rutas relativas al proyecto,
  sin el prefijo de namespace, y al importar el nombre del proyecto sale de
  la URL, no de la metadata. La metadata `.purplemd.json` sí guarda el
  nombre tal cual (con el prefijo), pero el import solo lee su versión, así
  que el archivo puede migrarse entre usuarios e instancias.

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
