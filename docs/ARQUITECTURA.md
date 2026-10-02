# Arquitectura

Cómo está armado PurpleMD: datos en disco, backends de persistencia y
comportamiento del frontend (superficies, menús, caché y semilla). La
referencia HTTP está en [API.md](API.md) y las reglas de accesibilidad
en [ACCESIBILIDAD.md](ACCESIBILIDAD.md).

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
  y «Solo editor»; «Archivo» agrupa «Descargar .md» y «Exportar .pdf»
  (con una nota abierta) y «Exportar .zip» (con proyecto activo), en
  ese orden, igual que en «Menú ▾» de la barra ancha, y «Difusión»
  lleva «Compartir PurpleMD», siempre disponible, y «Ver en GitHub»
  (con el logo de Octocat, `role="menuitem"` sobre un `<a>` con
  `target="_blank"`), que abre el repositorio en una pestaña nueva. Al
  elegir una
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
  `role="toolbar"`, que exigiría roving tabindex) y el
  menú «Menú ▾» («Menu Button» de la APG con el mismo ciclo de vida
  que el ☰ y el panel anclado bajo su trigger, no a ancho completo, con
  «Descargar .md», «Exportar .pdf», «Exportar .zip», «Compartir
  PurpleMD» y «Ver en GitHub» adentro —los tres primeros en el mismo
  orden que el grupo «Archivo» del ☰, y el último un `<a>` con
  `role="menuitem"` y `target="_blank"`, igual que en el ☰, así las
  dos superficies ofrecen la entrada al repositorio).
  «Descargar .md», «Exportar .pdf» y «Exportar .zip» están en las dos
  superficies con la misma etiqueta y habilitación (una sola regla por
  acción, `data-accion`: nota abierta para descargar y para el pdf,
  proyecto activo para el zip), y el trigger «Menú» se apaga cuando
  no hay ni nota ni proyecto. El PDF siempre sale con el pie
  «Generado con PurpleMD ♥» (el número de página se mantiene: es
  paginación, no branding). Si las etiquetas no
  entran, la barra envuelve en varias filas: nunca se truncan ni se
  achican y los targets siguen teniendo 44px (WCAG 2.5.5). Al cruzar el
  corte se cierra el menú del lado opuesto y, si el foco quedó en un
  control recién ocultado, pasa al primer control enfocable visible de
  la barra (WCAG 2.4.3).
- Regla de superficies: el explorador importa y crea; en angosto el menú
  ☰ descarga y exporta; en ancho la barra muestra el visualizador y el
  menú `Menú` reúne las acciones (descargar, exportar, compartir y
  repo). Importar avisa su **éxito**
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
  exportación (que viven en la barra ☰/Menú, que puede estar cerrada)
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
  cambios sin guardar no deja cambiar de nota. El ítem «Descargar .md»
  arma el archivo en el cliente, sin endpoint de descarga; aparece en las
  dos superficies (ítem del menú ☰ en angosto e ítem del menú «Menú ▾»
  en ancho) con el mismo manejador y la misma habilitación
  (`data-accion="descargar"`).
- No hay frameworks, bundlers ni librerías de JavaScript en el cliente:
  el render lo hace el backend.
