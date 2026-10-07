---
version: "0.1.0"
schemaVersion: 1
name: "seguridad"
description: "Seguridad de PurpleMD: tope a todo lo que entra, SSRF, concurrencia, errores y logging, CORS/cabeceras y sesión con Google. Cada regla nace con su test."
tools: [read, write, edit, shell, grep, glob]
permissions: "read-write"
model: "sonnet-4"
tags: [security, ssrf, dos, limits, validation, cors, headers, logging, auth, oauth, csrf, cookies]
---

# Skill: Seguridad

## Principio rector

> **Toda regla de seguridad nace con su test.** Si nada falla cuando la regla se rompe, la regla no existe.
> **PurpleMD corre sin autenticación y con una demo pública**: cada visitante es «usuario», y el
> servidor nunca actúa sobre una URL, un archivo o un ZIP que venga del cliente sin antes acotarlo.
> Cuando hay credenciales de Google (ver `docs/AUTH.md`), la sesión cambia la amenaza de «todos
> contra todos» a «cada cuenta contra su propia carpeta», y aparecen CSRF, cookies y secretos como
> superficie nueva — pero el servidor sigue sin confiar en nada que venga del cliente.

---

## Modelo de amenazas (qué protege y cómo está hoy)

| Activo | Amenaza | Estado |
|---|---|---|
| Disco `{PURPLEMD_DIR}` | path traversal (`..`, rutas absolutas) | ✅ `validar_nombre` / `validar_ruta` + tests |
| HTML del preview y del PDF | XSS (HTML crudo, `javascript:`) | ✅ `html: False` + Pygments escapa + `validateLink` |
| Red saliente | SSRF: el servidor baja URLs del usuario | ✅ `FETCHER_PDF` solo `data:` + test con servidor local |
| Memoria / disco / CPU | zip bombs, subidas sin tope, payloads enormes | ✅ tope antes de leer (413 + `file_size`) + tests |
| Event loop | trabajo bloqueante dentro de `async def` | ✅ tramo pesado fuera del loop (`def` / `run_in_threadpool`) |
| Diagnóstico | excepciones tragadas sin registro | ✅ logger `purplemd` con traceback + tests (`logging`, nunca `print` ni `pass`) |
| API pública | CORS con wildcards, cabeceras ausentes | ✅ origen prod literal + regex localhost, CSP y cabeceras + `tests/test_auth.py` |
| Sesión con Google | CSRF, cookie forjada, open redirect, token filtrado | ✅ `SameSite=Lax` + chequeo de `Origin` + `state` PKCE + cookie HttpOnly + tests |
| Estado global | listas que crecen sin límite (notificaciones) | ⚠️ acotar o expirar |
| Servidor MCP | endpoint sin sesión accesible desde la red | ✅ exige `PURPLEMD_MCP_TOKEN`; 403 con `PURPLEMD_STORAGE=drive` + tests |

---

## Reglas

### 1. El servidor no fetcha URLs del usuario (SSRF)

- Todo lo que resuelva recursos externos (WeasyPrint en el PDF, un futuro import de imágenes,
  un webhook, un fetch a una API) pasa por un **fetcher propio** que solo acepta `data:` y
  bloquea `http`, `https`, `file` y rutas relativas. Los recursos bloqueados se omiten, no rompen
  el documento.
- Prohibido pasar `url_fetcher` por defecto ni `base_url` a un directorio del usuario.
- Verificación: servidor local en un hilo + nota con `![x](http://127.0.0.1:PUERTO/a.png)` +
  `GET .../pdf` ⇒ **cero peticiones**.

### 2. Toda entrada tiene tope, y el chequeo va antes de consumir el recurso

| Entrada | Tope | Dónde se aplica |
|---|---|---|
| Contenido de nota | `MAX_BYTES` (1 MB) | pydantic + núcleo + storage |
| Markdown a renderizar | `MAX_RENDER_BYTES` (200 KB) | `RenderRequest` |
| ZIP subido | `MAX_IMPORT_ZIP_BYTES` | `file.read(MAX_IMPORT_ZIP_BYTES + 1)`: el byte de más delata el exceso sin cargarlo entero |
| Entrada individual del ZIP | `MAX_BYTES` | mirando `zip_info.file_size` **antes** de `zf.read()` |
| Suma descomprimida del ZIP | `MAX_IMPORT_TOTAL_BYTES` | acumulando `file_size` antes de leer cada entrada |

- `zf.read()` sobre una entrada gigante **ya** consume la memoria: el tope se mira en el
  **central directory** (`file_size`), no en el bytes leídos.
- Preferir responder `413` (payload too large) a dejar que el servidor lo descubra.

### 3. Ningún trabajo bloqueante en el event loop

- Endpoint `def` ⇒ FastAPI lo corre en el threadpool: es la opción por defecto
  para disco y CPU (export de ZIP, render, PDF).
- Endpoint `async def` que sí necesita `await` (p. ej. `file.read`, que ya va
  al threadpool por su cuenta) manda el tramo pesado a `run_in_threadpool`:
  `POST /api/projects/{p}/import` es el ejemplo.
- Regla práctica: si en un `async def` no hay `await`, sobra el `async`; si lo
  hay y además hay trabajo pesado, el pesado va al threadpool.

### 4. Ninguna excepción sin registro

- `logging` con logger de módulo (`logging.getLogger(__name__)` o un logger nombrado del proyecto),
  **nunca** `print` ni `pass`.
- El handler 500 debe registrar el traceback (`logger.error(..., exc_info=...)`) y responder el
  `{"detail": ...}` genérico **sin** filtrar el stack al cliente.
- Los fallbacks que devuelven contenido «por si acaso» (p. ej. `renderer.renderizar`) también
  registran en `WARNING`: un fallback silencioso es un bug invisible en producción.

### 5. Validación en el servidor, siempre

- El cliente filtra por comodidad; el servidor defiende. Nombres, rutas, tamaños y tipos de
  archivo se re-validan en cada capa (pydantic → núcleo → storage).
- `extra="forbid"` en los modelos: un campo mal escrito responde 422, no se descarta en silencio.

### 6. CORS, CSRF y cabeceras

- **Sin wildcards** en `allow_origins`, `allow_methods` ni `allow_headers`; origen de producción
  explícito (`https://purplemd.onrender.com`) + `allow_origin_regex` para localhost.
- `allow_credentials=True` solo con orígenes exactos (nunca con regex amplia ni wildcard).
- **CSRF en dos barreras**, y solo cuando hay sesión (es cuando hay algo que forging):
  1. cookie `SameSite=Lax`: el navegador no la manda en un `POST` cross-site;
  2. chequeo de `Origin` en los verbos **no seguros**: si viene y el host no coincide con
     `Host` ⇒ 403. Sin `Origin` no se corta, porque `curl` y los tests no lo mandan.
- **CSP estricta** en el frontend (`script-src 'self'`, `style-src 'self'`), por eso no puede
  quedar ni un `style=` ni un `onclick=` en `index.html` (lo verifica
  `CabecerasTests::test_no_hay_scripts_ni_estilos_inline_en_el_frontend`).
  **Sin CSP** en `/docs`, `/redoc`, `/openapi.json` y `/mcp`: Swagger carga su JS desde un CDN y
  la CSP lo rompería.
- Cabeceras: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`.

### 7. Estado global acotado

- Cachés, colas y listas de sesión tienen tope o expiración; crecer sin límite es un DoS lento.
- Lo que vive en memoria (notificaciones) se documenta como efímero y no se comparte como
  estado autoritativo.
- Las sesiones por cuenta también: `_MEMORIA_USUARIOS` tope 64,
  `CuentasEnDisco` tope 1000 y `LimiteCuentasError` ⇒ 503.

### 8. Sesión, tokens y el servidor MCP

- **Alcance OAuth mínimo**: `drive.file` + `drive.appdata` (Google exige el segundo para tocar
  `appDataFolder`); nunca `auth/drive`.
- **Cookie de sesión firmada con HMAC-SHA256** de la stdlib, `HttpOnly`, `SameSite=Lax`, 30 días,
  `Secure` solo bajo HTTPS. Los tokens de Google **no** viajan en la cookie: viven en
  `{PURPLEMD_DIR}/auth/{sha256(sub)}.json` con permisos `0600`.
- **Authorization Code + PKCE (`S256`)** con `state` atado a la pestaña en una cookie temporal;
  `access_type=offline` y `prompt=consent` siempre, porque sin eso Google no entrega refresh token.
- **`destino` anti open-redirect**: el callback solo puede volver a una ruta interna; cualquier
  valor externo cae en `/`.
- **Todo `/api/` exige sesión**, con **dos excepciones** que no tocan
  storage: `POST /api/render` y `POST /api/pdf`, que reciben markdown y
  devuelven HTML/PDF sin leer ni escribir nada. Existen para el modo
  invitado (no hay cuenta y por tanto no hay storage). Nunca agregar una
  tercera: cualquier endpoint que lea o escriba storage va con sesión.
  `_RUTAS_STATELESS` en `api.py` es la lista cerrada, y
  `test_sin_sesion_los_endpoints_de_datos_no_pasan` prueba que todo lo
  demás sigue respondiendo 401.
- **MCP no tiene sesión**, así que exige `PURPLEMD_MCP_TOKEN` por `X-PurpleMD-Token`, y con
  `PURPLEMD_STORAGE=drive` queda 403 aunque el token sea válido (un cliente externo no puede
  leer el Drive de una cuenta concreta).
- Un `ConfigAuth` logueado o impreso no puede volcar secretos: `client_secret` y `secret_key`
  van con `field(repr=False)`.

### 9. Imagen y dependencias

- Usuario no-root en el contenedor, `uv.lock` committeado, `uv sync --frozen` en el build,
  sin secretos en el repo (`.gitignore` cubre `local/`, `.env`).
- `dependabot`/renovación manual de dependencias; revisar el changelog de `fastapi`,
  `starlette` y `weasyprint` por advisories.

---

## Cómo verificar (comandos)

```bash
uv run pytest -q                                  # suite completa (incluye tests de seguridad)
uv run pytest tests/test_api.py -q -k "pdf or import or interno"
uv run ruff check . && uv run ty check .           # lint + tipos

# ¿quedó algún innerHTML con datos del usuario?
grep -n "innerHTML" static/js/app.js
# ¿quedó un fetcher por defecto o un allow_origins con wildcard?
grep -rn "allow_origins=\[\"\\*\"\]\|default_url_fetcher" api.py
# ¿quedó trabajo bloqueante en async?
grep -n -A3 "^async def" api.py
```

## Cómo probar una amenaza a mano

```python
# SSRF: el PDF no debe tocar la red
#   1. HTTPServer en un hilo anotando peticiones
#   2. nota con ![img](http://127.0.0.1:PUERTO/a.png)
#   3. GET /api/projects/p/notes/n/pdf  -> 200 y hits == []
#
# Zip bomb: zip de 285 KiB con una entrada de 300 MB
#   -> se rechaza por file_size antes de descomprimir (sin pico de RSS)
```

---

## Checklist pre-push de seguridad

- [ ] Ningún endpoint de I/O/CPU declarado `async def` sin `await`.
- [ ] Ninguna llamada a una URL escrita por el usuario sin fetcher propio.
- [ ] Todo `read()` de subida con tope, mirado **antes** de descomprimir/escribir.
- [ ] Todo `except` registra en `logging` y responde sin exponer el stack.
- [ ] Sin wildcards en CORS; sin cabeceras nuevas rotas.
- [ ] Ningún secret visible en un `repr`, un log, un `detail` ni una URL.
- [ ] Cookie de sesión: `HttpOnly` + `SameSite=Lax` + firma HMAC; los tokens de Google, solo en disco `0600`.
- [ ] Todo endpoint de escritura pasa el chequeo de `Origin` cuando hay sesión.
- [ ] Cada regla nueva con su test en `tests/`.
- [ ] `uv run pytest -q`, `ruff`, `ty` en verde.

---

## Relación con otras skills

- `python`: reglas de código (excepciones específicas, `logging`), este archivo pone el **qué** se
  debe poder probar y con qué.
- `container`: usuario no-root, libs de runtime, HEALTHCHECK; acá va lo que no debe salir al
  contenedor (secretos, datos del usuario).
- `frontend`: validación de rutas en el cliente, `textContent` sobre `innerHTML`; la defensa del
  servidor no se delega al navegador.
