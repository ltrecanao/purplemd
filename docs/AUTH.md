# Acceso con Google y almacenamiento en Drive

PurpleMD puede usar **Google como identidad** y **Google Drive como
almacenamiento**. Las dos cosas son independientes: se puede tener login
sin Drive, pero no Drive sin login.

| Situación | Comportamiento |
|---|---|
| Sin credenciales | Igual que siempre: sin pantalla de acceso, sin 401, proyectos con prefijo `u_xxxx_` |
| Credenciales completas | Login obligatorio; los datos viven aislados por cuenta |
| Credenciales completas + «Continuar sin cuenta» | **Modo invitado**: los datos viven solo en el navegador (ver [Modo invitado](#modo-invitado)) |
| `PURPLEMD_STORAGE=drive` | Los datos viven en el Drive de **cada** cuenta (exige login) |

> La regla de oro: **la integración nunca cambia el comportamiento de un
> despliegue que no la pidió.** `GOOGLE_CLIENT_ID` ausente o incompleto
> deja `habilitado=False` y lo registra en `WARNING`; no hay pantalla de
> acceso y ningún endpoint responde 401.

---

## Variables de entorno

### Obligatorias para encender el login

| Variable | Qué es |
|---|---|
| `GOOGLE_CLIENT_ID` | Cliente OAuth 2.0 de Google Cloud |
| `GOOGLE_CLIENT_SECRET` | Secreto del mismo cliente |
| `PURPLEMD_SECRET_KEY` | Clave con la que PurpleMD firma sus cookies (HMAC-SHA256). Generala una vez: `openssl rand -hex 32` |

Si falta cualquiera de las tres, el login queda apagado y aparece un
`WARNING` con los nombres de las que faltan. Un login silenciosamente
roto es un bug invisible.

### Opcionales

| Variable | Default | Qué hace |
|---|---|---|
| `PURPLEMD_AUTH` | automático | `off`/`0`/`no`/`false`/`apagado` **apaga** la integración aunque haya credenciales; `on`/`1`/`si`/`yes`/`true`/`encendido` la **pide**, y si faltan credenciales lo registra en `WARNING` y queda apagada |
| `PURPLEMD_REDIRECT_URI` | URL del request | URI de redirección usada en el flujo. Definila si Google solo permite una exacta |
| `PURPLEMD_GOOGLE_SCOPE` | ver abajo | Reemplaza el alcance completo |
| `PURPLEMD_COOKIE_SECURE` | según esquema | cualquier valor no vacío fuerza `Secure` en las cookies aunque el request venga por HTTP (útil detrás de un proxy que termina TLS) |
| `PURPLEMD_STORAGE` | `filesystem` | `filesystem`, `memory` o `drive` |
| `PURPLEMD_MCP_TOKEN` | — | Solo **sin** credenciales de Google: token del admin que abre `/mcp` (ver [MCP](#servidor-mcp)) |
| `PURPLEMD_DIR` | `./local/purplemd` | Raíz de datos |
| `PURPLEMD_AUTH_DIR` | `{PURPLEMD_DIR}/auth` | Dónde quedan los tokens de Google |

### Alcance OAuth

```
openid email profile
https://www.googleapis.com/auth/drive.file
https://www.googleapis.com/auth/drive.appdata
```

- `drive.file` y **no** `drive`: el consentimiento pide «los archivos que
  creó esta app», no todo el Drive.
- `drive.appdata` es el **requisito explícito de Google** para leer y
  escribir en `appDataFolder`, la carpeta oculta donde viven las notas.
  Sin él, `files.list` sobre esa carpeta devuelve vacía. Es un alcance
  *non-sensitive*: no exige verificación ni agrega pantalla de
  advertencia.
- `drive.appdata` queda fuera si se usa `PURPLEMD_STORAGE=filesystem` o
  `memory` (no se necesita Drive), pero no hace falta ajustarlo: el
  consentimiento es el mismo y no habilita nada que la app no use.

---

## Cómo conseguir las credenciales

> **Ojo con el nombre del menú**: Google renombró *OAuth consent screen*
> a **Google Auth Platform** (2024–2026). Si buscás «Pantalla de
> consentimiento» en la documentación vieja, no lo vas a encontrar. Las
> pantallas pasaron a tres pestañas: **Branding**, **Audience** y
> **Clients**.

1. [Google Cloud Console](https://console.cloud.google.com/) → crear
   (o elegir) un proyecto. No pide tarjeta.

2. **APIs y servicios → Biblioteca** → buscar *Google Drive API* →
   **Activar**. (La de *OpenID Connect* no hace falta: los endpoints de
   userinfo son parte del `openid`.)

3. **APIs y servicios → Google Auth Platform → Branding**:
   - Nombre de la app (lo ve quien hace login) y correo de soporte.
   - **Audience**: tipo de usuario **Externa** (no hay organización
     detrás), y en *Test users* → **+ Add users** el correo de quien lo
     va a usar.

4. **Google Auth Platform → Clients → Credenciales → Create
   credentials → OAuth client ID**:
   - Tipo: **Web application**.
   - **Authorized redirect URIs** → **Add URI**, exactas (no hay
     comodines; el esquema, la caja y la barra final cuentan):
     - local: `http://localhost:8000/api/auth/callback`
     - producción: `https://purplemd.onrender.com/api/auth/callback`

     Las dos pueden convivir en el mismo cliente, así que no hace falta
     crear uno por entorno.
   - *Authorized JavaScript origins* se puede dejar vacío: el flujo
     empieza en el backend, no desde el navegador.

5. Copiar el **Client ID** y el **Client secret** a las variables de
   entorno. Nunca al repo.

### Mientras la app está en *Testing*

- Solo pueden entrar las cuentas listadas en *Test users*, y ven una
  pantalla de «app sin verificar» que se saltea con *Advanced*.
- Los **refresh tokens vencen a los 7 días**: PurpleMD lo traduce en un
  401 con «volvé a conectar tu cuenta» y basta volver a entrar.
- Tope de 100 usuarios de prueba.

Nada de esto aplica si solo se pidieran `openid email profile` (Google
exime a esa combinación), pero PurpleMD pide además los alcances de
Drive, así que **el límite nos aplica**.

### Publicar para producción

*Google Auth Platform → Audience → Public app* saca el límite de 7 días,
habilita cualquier cuenta y quita el aviso. Antes de poder publicar,
Google exige en **Branding**: URL de la app, URL de política de
privacidad y al menos un *Authorized domain* — y ese dominio hay que
probar que es tuyo con [Search Console](https://search.google.com/search-console/about).

Consecuencia práctica: **la app recién se puede publicar cuando el
dominio de producción ya está fijo**. Hacerlo como paso aparte, después
de verificar el deploy, y no bloquearlo para probar en local.

---

## Flujo

Authorization Code con **PKCE (`S256`)** y `prompt=consent`.

```
navegador ──GET /api/auth/login?destino=/nota ──▶ api.py
   │   set-cookie purplemd_oauth (state + verifier + destino, 10 min)
   │◀──302────────────────────────────────────── accounts.google.com
   │
   └──▶ pantalla de consentimiento de Google
        │
        └──302 /api/auth/callback?code=...&state=...
                │  verifica state contra la cookie
                │  POST oauth2.googleapis.com/token  (code + code_verifier)
                │  GET  openidconnect.googleapis.com/v1/userinfo
                │  guarda los tokens en disco (0600)
                │  set-cookie purplemd_sesion (30 días) y borra purplemd_oauth
                ▼
             /nota
```

Detalles que importan:

- **`state` + cookie de corta vida**: el callback exige que el
  `state` venga de *esta misma pestaña*. Un `state` que no coincide
  responde 400.
- **PKCE `S256`**: el `verifier` nunca llega al JavaScript del frontend;
  viaja en la misma cookie firmada.
- **`access_type=offline` + `prompt=consent` siempre**: sin esto Google
  entrega el `refresh_token` solo la primera vez y la sesión moriría a
  la hora. El costo es una pantalla de consentimiento extra en cada
  login, y es deliberado.
- **Si la app está en modo testing**, los refresh tokens vencen a los 7
  días: el siguiente intento devuelve `invalid_grant` y el usuario
  tiene que volver a conectar. Se resuelve publicando la app.
- **`destino` anti open-redirect**: solo se acepta una ruta interna.
  `https://evil.example` o `//evil.example` caen en `/`.

### Endpoints

| Ruta | Qué responde |
|---|---|
| `GET /api/auth/login?destino=/` | 302 al consentimiento de Google; 503 si no hay credenciales |
| `GET /api/auth/callback` | 302 al destino tras guardar la sesión; **400** si expiró o no coincide con la pestaña, si falta el `code` o si Google devolvió `error`; **502** si falló el intercambio con Google o el perfil; **503** sin credenciales o si se llenó el tope de cuentas |
| `GET /api/auth/me` | 200 siempre: `{requiere_sesion, autenticado, email, name, picture, almacen, drive}` |
| `POST /api/auth/logout` | 204; borra la cookie y los tokens del servidor |

Los cuatro existen en la app pero van con `include_in_schema=False`, así
que Swagger (`/docs`) no los muestra: no son una API para terceros.

---

## Sesión y aislamiento

La cookie `purplemd_sesion` es una cadena firmada con HMAC-SHA256
(`PURPLEMD_SECRET_KEY`), con `HttpOnly`, `SameSite=Lax` y `Secure` bajo
HTTPS. Dura **30 días**. Un token alterado, vencido o sin la clave
devuelve simplemente «sin sesión»: nunca lanza.

Los tokens de Google **no** viven en la cookie. Viven en:

```
{PURPLEMD_DIR}/auth/{sha256(sub)}.json     permisos 0600
```

`sub` es el identificador estable de la cuenta en Google. El nombre del
archivo es su hash: ni el email ni el sub quedan expuestos en el disco
del servidor.

### Dónde viven los datos con sesión

| `PURPLEMD_STORAGE` | Ubicación |
|---|---|
| `filesystem` (default) | `{PURPLEMD_DIR}/users/{sha256(sub)}/projects/` |
| `memory` | una instancia por cuenta, tope 64 |
| `drive` | `appDataFolder` de **esa** cuenta de Google |

Dos cuentas no se pisan aunque compartan el volumen.

### El prefijo `u_xxxx_`

Sin login, el aislamiento en `filesystem` lo hace un prefijo en el
nombre del proyecto (una instancia compartida por todos los
navegadores). Con login el backend ya aísla, así que el frontend **deja
de ponerlo** (`prefijo()` en `static/js/app.js`) y los nombres llegan
planos.

Los proyectos con prefijo de la era sin autenticación quedan donde
estaban, fuera de toda carpeta de usuario: **no se migran
automáticamente**. La salida es exportar el `.zip` con la cuenta vieja e
importarlo con la nueva.

---

## Modo invitado

Con el login encendido, la pantalla de acceso ofrece **«Continuar sin
cuenta»** para quien prefiere no asociar su trabajo a una cuenta. Lo que
hace, y sobre todo lo que **no** hace:

- **El servidor no recibe ni conserva nada** de lo que se escribe. Los
  proyectos viven en `localStorage` (clave `purplemd_invitado_datos`) y
  la marca de modo en `purplemd_invitado`.
- **Sí viaja el markdown** en dos lugares, y no queda guardado: el
  preview (`POST /api/render`) y el PDF (`POST /api/pdf`) convierten y
  se olvidan. Son los dos únicos `/api/` que no exigen sesión,
  precisamente por eso (ver `docs/API.md`).
- **El export es el respaldo.** El `.zip` lo arma el navegador con el
  mismo formato que `FilesystemStorage.exportar_proyecto`, y el `.pdf`
  pasa por el endpoint stateless. El `.md` sale del editor, que nunca
  dependió del servidor.
- **Salir no borra.** Los datos quedan en el navegador: es lo que
  promete la pantalla de acceso y lo único que el usuario tiene para
  volver a su trabajo.
- **Con sesión, manda la sesión.** Si después se entra con Google, el
  modo invitado se apaga solo y sus datos siguen guardados por si
  vuelve.

Las reglas de nombres, rutas, tamaños y topes de ZIP se **replican** en
`static/js/app.js` con los mismos números que
`purplemd_storage/protocol.py`: sin servidor no hay quien defienda, así
que el cliente es el servidor. Si cambia un tope allá, hay que cambiarlo
acá.

Si `localStorage` está inaccesible, el botón lo explica y no deja entrar
en vez de dejar una app que no puede guardar nada.

---

## Backend de Drive

`PURPLEMD_STORAGE=drive` convierte a Drive en la tercera implementación
del protocolo `Storage`.

```
appDataFolder/projects/{proyecto}/{subcarpeta}/{nota}.md
```

`appDataFolder` es invisible en la interfaz de Drive y solo la puede ver
esta app, así que el usuario no puede romper la estructura desde el
explorador de archivos.

Tres decisiones que definen la implementación:

- **Los nombres no son únicos en Drive.** Toda operación busca por
  `padre + nombre` y crea solo si no hay coincidencia; si hay más de una
  se registra `WARNING` y se usa la primera.
- **Drive no mueve `modifiedTime` de las carpetas** cuando cambian sus
  hijos. Por eso el epoch del proyecto se guarda en su `description` y
  se actualiza en cada escritura: es lo que mantiene ordenada la lista
  de proyectos.
- **La cuota es finita** (`files.list` = 100 unidades,
  `files.update` = 50). Ante `403 rateLimitExceeded` o `429` se reintenta
  con backoff exponencial + jitter, hasta **4 veces**, antes de rendirse
  con `ErrorDrive`.

Además: el borrado es **permanente** (`DELETE`, no papelera — Google
prohíbe papelera en `appDataFolder`), y `/health` **no** llama a Drive
porque el HEALTHCHECK del contenedor lo consulta cada pocos segundos y
cada chequeo costaría cuota.

### Traducción de errores

| Drive responde | La API responde | Detalle |
|---|---|---|
| 401 | **401** | «la sesión con Google venció: volvé a conectar tu cuenta» |
| 404 | **404** | |
| 403/429 de cuota | reintento ×4 → **503** | |
| Otro ≥ 400 | **503** | |

### Fugas de memoria y límites

`_MEMORIA_USUARIOS` (backend `memory`) tiene tope de 64 cuentas y
`CuentasEnDisco` de 1000 (`LimiteCuentasError`). El listado de Drive se
cachea **15 segundos dentro de un solo request**: evita repetir
`files.list` al caminar el árbol, no acelera entre requests.

---

## Servidor MCP

El endpoint `/mcp` **siempre** pide autenticación por la cabecera
`X-PurpleMD-Token`, con o sin login de Google. Hay dos regímenes
excluyentes; el token de uno no sirve en el otro:

| Régimen | Cómo se obtiene el token | Qué storage sirve |
|---|---|---|
| Con credenciales de Google (`GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` + `PURPLEMD_SECRET_KEY`) | `POST /api/auth/mcp-token` con sesión de Google → `200 {token, header, expires_at}`. En la app: «menú → Servidor MCP» | Los datos de esa cuenta: `{PURPLEMD_DIR}/users/{sha256(sub)}/projects/`, o el Drive de esa cuenta con `PURPLEMD_STORAGE=drive` |
| Sin credenciales de Google | Variable de entorno `PURPLEMD_MCP_TOKEN`, leída **recortada** (un `\n` o espacio final al pegarla no rompe nada) y comparada en bytes | La raíz compartida `{PURPLEMD_DIR}/projects/` |

- **Sin token → 403**: «falta el token de MCP: generá el tuyo en la app
  (menú → Servidor MCP)» con login encendido, y «el servidor MCP está
  deshabilitado: falta `PURPLEMD_MCP_TOKEN`» sin credenciales. **Token
  inválido o vencido → 401** «token de MCP inválido o vencido».
- **TTL y revocación**: el token de la app es un payload firmado con
  `PURPLEMD_SECRET_KEY` que lleva el `sub` de la cuenta y el alcance
  `mcp`. No hay estado en el servidor: no se almacena y no se revoca uno
  por uno. Cada emisión dura **90 días**; para revocar todos, rotá
  `PURPLEMD_SECRET_KEY` (eso además cierra todas las sesiones).
- **El token de entorno no sirve con login encendido** (responde 401): no
  identifica a nadie y lo único que alcanzaría sería la raíz de la era
  sin login. Tampoco son intercambiables la cookie de sesión y el token
  MCP: cada uno tiene su alcance propio.
- **`PURPLEMD_STORAGE=drive` ya no apaga el MCP**: con el token de la
  cuenta se sirve el Drive de esa misma cuenta; sin token sigue apagado.
- **Errores de `POST /api/auth/mcp-token`**: **401** sin sesión, **503**
  si la integración de Google no está configurada y **403** si el
  `Origin` es ajeno (CSRF).
- **Modo invitado**: con login encendido, «Continuar sin cuenta» guarda
  los datos en el navegador (`localStorage`), no en el servidor, así que
  el MCP **no puede** servir a ese usuario.

---

## Troubleshooting

| Síntoma | Causa |
|---|---|
| `WARNING: la integración con Google queda apagada porque faltan …` | Faltan credenciales; el login no se enciende y no hay 401 |
| Pantalla de acceso que nunca avanza | Revisá la consola del navegador: casi siempre es un redirect URI distinto al autorizado en Google Cloud |
| `error=access_denied` en el callback | El usuario canceló el consentimiento, o la cuenta no está en *Usuarios de prueba* |
| `invalid_grant` en el callback | App en testing y refresh token de más de 7 días, o se regeneró el secreto del cliente |
| `el token de Google venció: volvé a conectar tu cuenta` (401) | Consentimiento revocado o refresh token perdido; basta volver a entrar |
| Drive responde 403 `rateLimitExceeded` seguidos | Cuota agotada: los reintentos ya se agotaron. Suele ser transitorio |
| `Google Drive API has not been used in project … before or it is disabled` (503) | La API de Drive no está activada en el proyecto de Google Cloud. **APIs y servicios → Biblioteca → Google Drive API → Activar** y esperar 2 a 5 minutos a que se propague. Aparece recién al *usar* el backend, no al configurarlo |
| `Solicitar detalles` pidiendo un rol al habilitar la API | La cuenta de la consola no es dueña del proyecto. El rol que hace falta es *Service Usage Admin* (`serviceusage.services.enable`), no ninguno de los que ofrece Resource Manager; la solución es entrar con la cuenta dueña |
| `WARNING: hay 2 carpetas «projects» en appDataFolder; elijo la más vieja` | Raíz duplicada de una carrera antigua entre dos siembras en paralelo. Se usa siempre la más vieja y ya no se vuelve a crear; la otra se puede borrar si está vacía |
| Los proyectos quedaron «viejos» en la lista | La `description` del proyecto no se pudo escribir (queda en `WARNING`); no rompe nada |
| `PURPLEMD_STORAGE=drive necesita una sesión de Google` (503) | Faltan credenciales: Drive solo funciona con login (el MCP responde 403 en esa misma combinación) |
| `/mcp` responde **401** «token de MCP inválido o vencido» | El token venció (TTL de 90 días), fue alterado o está firmado con otra `PURPLEMD_SECRET_KEY`; generá otro desde la app («menú → Servidor MCP») |
| `/mcp` responde **403** | Falta la cabecera `X-PurpleMD-Token`: con login encendido hay que generar el token en la app («menú → Servidor MCP»); sin credenciales, falta la variable `PURPLEMD_MCP_TOKEN` |

## Verificación

```bash
uv run pytest tests/test_auth.py -q   # 64 tests: config, sesiones, OAuth, CSRF, cabeceras, MCP
uv run pytest tests/test_drive.py -q  # 35 tests: contrato, appDataFolder, raíz, cuota, API
```

Ninguno toca la red: Google se intercepta con `httpx.MockTransport` y
Drive se simula con `DriveFalso`.
