# Arquitectura

Cómo está armado PurpleMD: datos en disco, backends de persistencia,
acceso con Google y comportamiento del frontend (superficies, menús,
caché y plantillas). La referencia HTTP está en [API.md](API.md), el
acceso en [AUTH.md](AUTH.md) y las reglas de accesibilidad en
[ACCESIBILIDAD.md](ACCESIBILIDAD.md).

## Estructura de datos

Sin sesión, todo el contenido vive bajo `{PURPLEMD_DIR}/projects/`, con
proyectos y subcarpetas. No hay notas sueltas:

```text
local/purplemd/
├── projects/                  ← sin login (era sin autenticación)
│   └── u_AbCdEf12_cuaderno/
│       └── portada.md
├── users/
│   └── 3f2a…e91/             ← sha256(sub) de la cuenta
│       └── projects/
│           └── cuaderno/
│               ├── portada.md
│               └── diseños/
│                   └── logo.md
└── auth/
    └── 7c1b…44d.json          ← tokens de Google, 0600
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

Con `PURPLEMD_STORAGE=drive` no hay disco local: la misma estructura
vive en `appDataFolder` del Drive de cada cuenta.

## Backends de almacenamiento

PurpleMD soporta tres backends, seleccionables con la variable de
entorno `PURPLEMD_STORAGE`:

| Backend | Variable | Descripción |
|---|---|---|
| **filesystem** | `PURPLEMD_STORAGE=filesystem` (default) | Persistencia en disco local (`{PURPLEMD_DIR}/projects/`, o `users/{sha256(sub)}/projects/` con sesión). Escrituras atómicas, sobrevive a restarts del proceso. |
| **memory** | `PURPLEMD_STORAGE=memory` | Solo RAM. Se pierde en cualquier restart (deploy, crash, scale to 0). Ideal para entornos efímeros como Render free tier. Con sesión hay una instancia por cuenta (tope 64). |
| **drive** | `PURPLEMD_STORAGE=drive` | El Google Drive de cada cuenta, en `appDataFolder`. Exige login: `get_storage()` no puede construirlo sin sesión y devuelve un `ValueError` claro. |

Los tres implementan el protocolo `Storage` de
`purplemd_storage/protocol.py` y responden igual ante el mismo guion de
operaciones: `tests/test_drive.py::ContratoTresBackendsTests` lo exige.

### El namespace `u_xxxx_` (solo sin login)

Sin sesión, el frontend usa **localStorage** para generar un namespace
único por navegador (`u_AbCdEf12`). Cada visitante ve solo sus proyectos
(`u_AbCdEf12_proyecto`), aislando datos casuales sin autenticación real.
El prefijo es un detalle de transporte: junto a un nombre nunca se
muestra (la lista, el título de la nota, los formularios de renombrar y
los avisos de eliminar lo quitan) y se agrega solo al armar cada pedido
a la API. La única pista del namespace en pantalla es el badge
`👤 u_AbCdEf12` de la barra superior.

Con login, el prefijo **desaparece**: el backend ya aísla por cuenta, y
ponerlo duplicaría cada proyecto (`prefijo()` en `static/js/app.js`).
Lo mismo en **modo invitado**: ahí los datos ya viven en este navegador,
así que el aislamiento lo da el origen y no el nombre.

### Modo invitado (storage en el navegador)

Elegido desde la pantalla de acceso, guarda proyectos y notas en
`localStorage` (`purplemd_invitado_datos`) y **el servidor no recibe ni
conserva nada** de lo que se escribe. `static/js/app.js` engancha en un
punto único —`pedir()`— y ahí replica las reglas de
`purplemd_storage/protocol.py` con los mismos números: sin servidor no
hay quien defienda, así que el cliente es el servidor.

Lo único que sí viaja son `POST /api/render` y `POST /api/pdf`
(markdown ⇒ HTML/PDF, sin persistir), que por eso son los dos únicos
`/api/` sin sesión. El `.zip` lo arma y lo lee el navegador con el
mismo formato que `FilesystemStorage.exportar_proyecto`.

## Sesión y seguridad

Un solo middleware (`_seguridad_y_sesion`) cubre **todas** las rutas,
incluidas las de los mounts (`/static`, `/mcp`), y corre por fuera del
router:

1. Si la ruta es `/mcp` ⇒ **token propio** en la cabecera
   `X-PurpleMD-Token`, con o sin login de Google (**403** si falta,
   **401** si no sirve). El token es el que define la identidad: el de la
   cuenta (firmado con su `sub`) cuando hay login, o el del entorno
   `PURPLEMD_MCP_TOKEN` cuando no lo hay.
2. Si hay credenciales de Google y no hay sesión válida ⇒ **401** en
   todo `/api/*` que no sea `/api/auth/*`, salvo `_RUTAS_STATELESS`
   (`/api/render` y `/api/pdf`, que no tocan storage). Las rutas de
   login siguen accesibles para poder entrar.
3. En verbos no seguros (`POST`, `PUT`, `PATCH`, `DELETE`), si viene un
   `Origin` cuyo host no coincide con `Host` ⇒ **403**. Sin `Origin` no
   se corta (`curl` no lo manda). La primera barrera de CSRF es la
   cookie `SameSite=Lax`.
4. Cabeceras de seguridad en el frontend: CSP estricta,
   `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`.
   **Sin CSP** en `/docs`, `/redoc`, `/openapi.json` y `/mcp`: Swagger
   carga su JS desde un CDN.

Detalles del flujo OAuth, de las cookies y de Drive: [AUTH.md](AUTH.md).

## Frontend

Compuesto por `static/index.html`, `static/css/style.css`,
`static/js/app.js` (módulo ES, sin dependencias externas) y
`static/js/tema.js` (script clásico en el `<head>`, sin dependencias).
Las páginas aparte —`static/privacy.html`, `static/terms.html` y
`static/wiki/index.html`— reutilizan el mismo CSS y `tema.js`, y se
sirven en `/privacy`, `/terms` y `/wiki`.

- **Pantalla de acceso**: al arrancar el JS pregunta
  `GET /api/auth/me`. Si el servidor exige sesión y no hay sesión, se
  muestra `#sesion-pantalla` (`role="dialog"`, `aria-modal`) cubriendo
  toda la app y **no se pide ningún dato más** (evita llenar la app de
  401). Cualquier respuesta 401 posterior la vuelve a mostrar. El badge
  de cuenta y el botón «Salir» solo existen con sesión; el badge
  `👤 u_…` del namespace, solo sin ella.
- **Dos puertas de entrada al arranque**: sesión con Google o
  «Continuar sin cuenta». Ambas terminan en `arrancar()` (separado de
  `iniciar()` para que no se duplique ni el intervalo de avisos). El
  botón de invitado es el oficial de Google —las medidas de su guía de
  branding, sin reestilizar— más una acción secundaria y el pie que
  aclara dónde viven los datos.
- Tres paneles: explorador (proyectos y árbol), editor y vista previa.
- En pantallas angostas (menos de 48rem) el explorador no es una
  columna: arranca oculto y es un desplegable superpuesto que se abre
  con el botón «Explorador» de la barra superior, cae ancho completo
  justo debajo de ella (con scroll interno si el contenido es largo) y
  se cierra con `Escape`, al pulsar el botón de nuevo o al abrir una
  nota. Cambiar de proyecto no cierra el desplegable. Desde 48rem el
  explorador ya es columna (estrecha hasta 60rem —el texto de cada ítem
  que lleva `title` se muestra por su tooltip—, ancha desde ahí) y el
  botón «Explorador» no se ve.
- Menú «Vista ▾»: la única superficie de las vistas, en cualquier
  ancho. Ofrece tres opciones exclusivas como `menuitemradio` con
  `aria-checked`: «Editor y previsualización» (estado inicial), «Solo
  previsualización» y «Solo editor». Al elegir una opción, `aria-checked`
  se sincroniza con `zona[data-vista]`, el menú se cierra y el foco
  vuelve al trigger (igual que con `Escape`, que solo cierra). Ocultar es
  solo `display:none` en CSS: el DOM no se toca, así que el texto del
  editor, el HTML renderizado, el scroll y el cursor se conservan.
  `Guardar` y `Ctrl`/`Cmd`+`S` funcionan en las tres vistas. La vista no
  se persiste: al recargar vuelve al estado inicial, «Editor y
  previsualización».
- Menú «Menú ▾»: superficie única de las acciones secundarias en
  cualquier ancho, agrupadas por tipo de operación: «Sincronizar»
  (siempre disponible, se apaga mientras hay un guardado o una
  sincronización en vuelo), «Archivo» («Descargar .md», «Exportar .pdf»
  con una nota abierta, «Exportar .zip» con proyecto activo), «Difusión»
  («Compartir PurpleMD», siempre disponible, y «Ver en GitHub», con el
  logo de Octocat: un `<a role="menuitem">` con `target="_blank"`) y
  «Servidor». Nunca se apaga entero: siempre hay algo que ofrecer. El
  PDF no lleva firma de agua (solo el número de página, que es
  paginación, no branding).
- Menú «Más ▾» de la barra de formato: el formato secundario del editor
  (tachado, código en línea, imagen, tabla, línea horizontal y bloque de
  código), con ítems etiquetados y el mismo `data-md` que los botones
  visibles (una acción, un manejador). Su panel vive dentro de
  `role="toolbar"` para ocultarse con la barra, y su trigger es un
  `.tool-btn` más, así que entra en el mismo roving tabindex.
- Sistema de menús único: los tres menús comparten el ciclo de vida de
  «Menu Button» (WAI-ARIA APG) —alternar con el trigger, clic fuera
  cierra, `Escape` cierra y devuelve el foco al trigger, activar un ítem
  cierra y devuelve el foco, flechas/`Inicio`/`Fin` navegan, `Tab` sale
  del menú y su `focusout` lo cierra— y solo hay uno abierto a la vez.
  El panel se posiciona `fixed` desde el rectángulo del trigger, por
  eso nunca se recorta contra los bordes de la ventana (se abre hacia
  arriba si no entra debajo y se alinea al borde derecho cuando
  sobra), y se vuelve a colocar en cada `resize`.
- Barra superior: `marca | badge | cuenta | Explorador (angosto) | Vista
  ▾ | ☀/🌙 | Menú ▾ | Guardar`. Si las etiquetas no entran, envuelve en
  varias filas: nunca se truncan ni se achican y los targets siguen
  teniendo 44px (WCAG 2.5.5). Al cruzar el corte de 48rem (768px), si el
  foco quedó en un control recién ocultado, pasa al primer control
  enfocable visible de la barra (WCAG 2.4.3).
- Tema claro/oscuro: `tema.js` es un script clásico en el `<head>`, antes
  del CSS, que resuelve y aplica `data-tema` en `<html>` antes del primer
  pintado (sin destello del color opuesto). Una sola clave en
  `localStorage` (`purplemd_tema`, `claro` u `oscuro`); sin clave manda
  `prefers-color-scheme` (con listener de cambio). El botón ☀/🌙 de la
  barra alterna y persiste la elección; el swap de iconos lo hace el CSS
  desde `data-tema` (el icono muestra la ACCIÓN, no el estado) y el JS
  solo pinta `title`/`aria-label`. La paleta se apoya en tres bloques de
  `style.css` —`:root` (claro), el media query sobre
  `:root:not([data-tema])` (respaldo sin JS) y
  `:root[data-tema="oscuro"]` (camino vivo)— con paridad exacta entre
  los dos últimos, garantizada por `tests/test_contraste.py`.
- Regla de superficies: el explorador importa y crea; el menú «Menú ▾»
  sincroniza, descarga, exporta, comparte y ofrece el servidor MCP; la
  barra de formato formatea. Importar avisa su **éxito**
  con un toast y su **error** en `#importar-estado`, junto a los botones
  de la fila.
- El arranque **no crea proyectos ni notas**: el explorador arranca con
  el estado vacío («Tu espacio de trabajo»), que ofrece crear el primer
  proyecto o elegir una plantilla. Si hay proyectos, se restaura la
  última ubicación guardada o, sin ella, queda seleccionado el más
  reciente.
- Las **plantillas** de `/plantillas` no se instalan: el frontend lee su
  manifiesto (`indice.json`) y llena el selector «Empezar con una
  plantilla» del formulario de proyecto. Solo si el usuario elige una,
  al crear el proyecto se crea además su primera nota con ese contenido
  y se abre. Sin manifiesto, el selector no aparece y el formulario
  queda como siempre.
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
  exportación (que viven en el menú «Menú ▾», que puede estar cerrado)
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
- Los enlaces relativos de la vista previa abren la nota del proyecto
  activo (p. ej. `[Ver recetas](recetas)`); los que tienen esquema o son
  anclas quedan para el navegador.
- Guardado manual (botón «Guardar» o `Ctrl`/`Cmd`+`S`): mientras hay
  cambios sin guardar no deja cambiar de nota. El ítem «Descargar .md»
  arma el archivo en el cliente, sin endpoint de descarga; vive en el
  menú «Menú ▾» con la misma habilitación que el resto de las acciones
  (`data-accion="descargar"`).
- No hay frameworks, bundlers ni librerías de JavaScript en el cliente:
  el render lo hace el backend.
