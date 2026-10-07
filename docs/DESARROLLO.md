# Desarrollo

Requisitos, arranque local, pruebas, contenedor y despliegue. Cómo está
armado el frontend y los datos está en [ARQUITECTURA.md](ARQUITECTURA.md);
la referencia HTTP, en [API.md](API.md).

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

Las rutas de datos (`/api/...`) están en la
[tabla de endpoints](API.md#endpoints).

En la instancia pública las mismas rutas cuelgan de
`https://purplemd.onrender.com`: por ejemplo
[`/health`](https://purplemd.onrender.com/health),
[`/docs`](https://purplemd.onrender.com/docs) y
[`/openapi.json`](https://purplemd.onrender.com/openapi.json).

## Acceso con Google en desarrollo

Con credenciales, el arranque es el mismo y solo cambian las variables:

```bash
export GOOGLE_CLIENT_ID=....apps.googleusercontent.com
export GOOGLE_CLIENT_SECRET=...
export PURPLEMD_SECRET_KEY=$(openssl rand -hex 32)
uv run uvicorn api:app --reload
```

Sin las tres, la app se comporta idéntica a la de siempre y avisa en el
log qué le falta. Con ellas, al abrir `/` aparece la pantalla de acceso.

Para probarlo en local hacen falta dos cosas en Google Cloud: el
redirect URI `http://localhost:8000/api/auth/callback` en las
credenciales, y el correo propio en **Usuarios de prueba** de la
pantalla de consentimiento. El detalle completo (incluida la
publicación de la app para que los refresh tokens no venzan a los 7
días) está en [AUTH.md](AUTH.md).

Otras variables útiles en desarrollo:

| Variable | Para probar |
|---|---|
| `PURPLEMD_AUTH=off` | Apagar la integración aunque haya credenciales |
| `PURPLEMD_STORAGE=memory` | Backend efímero (es lo que usa la demo) |
| `PURPLEMD_STORAGE=drive` | Backend de Drive (exige sesión) |
| `PURPLEMD_MCP_TOKEN=...` | El token del servidor MCP |
| `PURPLEMD_DIR=/tmp/purplemd` | Datos en un directorio descartable |

## Pruebas

La suite está escrita con `unittest` (clases `TestCase`), se corre con
`pytest` y tiene 416 tests, más 286 subtests de `self.subTest()`:

- 105 en `tests/test_api.py`.
- 95 en `tests/test_purplemd.py`.
- 64 en `tests/test_auth.py` (credenciales, sesiones, OAuth/PKCE,
  aislamiento, CSRF, cabeceras y MCP).
- 47 en `tests/test_storage.py`.
- 33 en `tests/test_drive.py` (contrato de los tres backends, los
  detalles propios de Drive y la traducción de errores en la API).
- 23 en `tests/test_zip.py`.
- 21 en `tests/test_renderer.py`.
- 19 en `tests/test_notificaciones.py`.
- 6 en `tests/test_contraste.py`.
- 3 en `tests/test_texto_visible.py`.

```bash
uv run pytest -q
```

Ningún test de auth o de Drive toca la red: Google se intercepta con
`httpx.MockTransport` y Drive se simula con un `DriveFalso` que
implementa los cuatro endpoints que usa `ClienteDrive`.

Lint y type checking:

```bash
uv run ruff check .
uv run ty check .
```

El frontend no tiene suite propia: casi todo lo que usa está cubierto por
`tests/test_api.py` (proyectos, notas, directorios, PDF y render). El
export/import de `.zip` cubre `tests/test_zip.py` y las tres rutas de
`/api/notifications`, `tests/test_notificaciones.py`. Del CSS sí hay un
test por regla que lo pide, leyendo el archivo: la paleta
(`tests/test_contraste.py`, más abajo) y el texto visible del explorador
(`tests/test_texto_visible.py`). Lo único del HTML que se testea: que
`index.html` no tenga `style=` ni `onclick=` inline, porque la CSP del
backend no los permitiría (`tests/test_auth.py::CabecerasTests`).

La paleta de color se valida sola: `tests/test_contraste.py` lee
`static/css/style.css`, recalcula los 26 pares de tokens de ambos temas y
falla si alguno baja de AA (4.5:1), si el texto principal baja de AAA
(7:1) o si las mediciones dejan de coincidir con las de
[ACCESIBILIDAD.md](ACCESIBILIDAD.md).

El workflow `.github/workflows/ci.yml` define cinco jobs: consistencia
de versiones entre `Dockerfile` y `pyproject.toml`, lint,
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

## Despliegue

El repo se despliega **solo con contenedor**: no hay manifiestos de
plataforma; el `render.yaml` del buildpack de Python se eliminó. El
flujo es el de la sección [Contenedor](#contenedor): dentro de la
imagen, `uvicorn` sirve en `${PORT:-8000}` (si el host inyecta `PORT`,
se usa ese).

La instancia pública sigue en
[purplemd.onrender.com](https://purplemd.onrender.com/): `GET /health`
responde `200` y Swagger (`/docs`) publica las **20 operaciones** de
las **13 rutas** de OpenAPI (`/openapi.json`).

Para encender el acceso de Google en producción, las tres variables
(`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PURPLEMD_SECRET_KEY`)
van en las variables de entorno de Render —nunca en el repo— y el
redirect URI autorizado en Google Cloud tiene que ser exactamente
`https://purplemd.onrender.com/api/auth/callback`. Si además se usa
`PURPLEMD_STORAGE=drive`, hay que agregar el origen
`https://purplemd.onrender.com` a los orígenes CORS permitidos de la
*Pantalla de consentimiento* de Google. Detalle completo en
[AUTH.md](AUTH.md).

Con `PURPLEMD_STORAGE=memory` —así corre la demo— no se escribe nada en
disco: las notas viven en RAM y se pierden en cualquier restart del
proceso (deploy, crash, scale to 0). El modo `filesystem` (el defecto,
escribe en `./local/purplemd`) necesita un disco persistente; ver
volúmenes y permisos en [Contenedor](#contenedor).
