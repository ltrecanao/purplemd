# Accesibilidad

Reglas de accesibilidad de PurpleMD: contraste, targets, foco, avisos y
teclado. El comportamiento detallado de cada superficie (menús, barra,
toasts) está en [ARQUITECTURA.md](ARQUITECTURA.md); la referencia HTTP,
en [API.md](API.md).

## Contraste

Medido con la fórmula de luminancia relativa de WCAG 2.x sobre los
tokens de `static/css/style.css` (tema claro y oscuro):

| Par de tokens | Claro | Oscuro | Nivel |
|---|---|---|---|
| `--texto` sobre `--fondo` | **15.29:1** | **15.58:1** | AAA |
| `--texto` sobre `--panel` | **16.66:1** | **14.51:1** | AAA |
| `--texto-tenue` sobre `--fondo` | 6.58:1 | 7.69:1 | AA |
| `--texto-tenue` sobre `--panel` | 7.17:1 | 7.16:1 | AAA |
| `--acento` sobre `--fondo` | 6.52:1 | 6.84:1 | AA |
| `--acento` sobre `--panel` | 7.10:1 | 6.37:1 | AA |
| Texto de botón (`--sobre-acento` sobre `--acento`) | 7.10:1 | 6.70:1 | AA |
| Texto de botón en hover (`--sobre-acento` sobre `--acento-fuerte`) | 8.98:1 | 8.41:1 | AAA |
| `--error` sobre `--panel` | 6.54:1 | 9.14:1 | AA |
| `--ok` sobre `--fondo` | 5.43:1 | 10.69:1 | AA |

**Todos los pares superan AA (≥ 4.5:1) en ambos temas.** El texto
principal (`--texto`) llega a **AAA (≥ 7:1)** en ambos, que es donde
AGENTS.md fija la regla; el resto del texto —secundario, acentos y
estados— queda en AA, y varios pares también alcanzan AAA.

> **Antes se afirmaba que «el texto normal supera AAA en ambos temas».
> No era cierto**: 11 de los 26 pares medían entre 4.31:1 y 6.84:1, y el
> hover del botón de acento en tema oscuro estaba por debajo de AA. Ese
> último caso se corrigió (`--acento-fuerte` en oscuro, `#8b5cf6` →
> `#b9a3fa`); los otros diez se mantienen en AA por decisión de diseño.

La paleta vive en `:root` y en el bloque `prefers-color-scheme: dark` de
`style.css`. `tests/test_contraste.py` **lee ese archivo**, recalcula los
26 pares y falla si alguno baja de AA, si el texto principal baja de AAA
o si los números dejan de coincidir con la tabla de arriba: cualquier
cambio de token obliga a volver a medir.

## Objetivos táctiles (WCAG 2.5.5)

Todo control tiene como mínimo **44×44 px**: los ítems de los menús
(`min-height: 44px`), los botones de la barra y los targets del
segmentado. Si las etiquetas no entran, la barra envuelve en varias
filas: nunca se truncan ni se achican (`style.css`).

## Foco visible (WCAG 2.4.3)

- `:focus-visible` con indicador propio en botones, ítems de menú,
  disparadores ☰ y «Menú ▾», filas del explorador, entradas del árbol,
  `summary` de carpetas, botones de la barra de herramientas y el
  editor.
- Al cruzar el corte de 48rem se cierra el menú del lado opuesto y, si
  el foco quedó en un control recién ocultado, pasa al primer control
  enfocable visible de la barra. Ocultar es `display:none`: el elemento
  no es enfocable ni visible.
- Tras eliminar una entrada, el foco va al siguiente control viable.

## Avisos que no tapan el foco (WCAG 2.2 SC 2.4.11 y 4.1.3)

- El **éxito** va a un toast efímero (6 s, `role="status"`,
  `aria-live="polite"`, sin robar el foco); el **error** queda
  persistente junto a su control (`role="alert"`, sin auto-cierre).
- El panel de acción (renombrar/eliminar) abre con el foco en su
  control principal y queda por encima de los toasts: un aviso nunca lo
  oculta por completo ni le intercepta el clic.
- Detalle completo del feedback en
  [ARQUITECTURA.md](ARQUITECTURA.md#frontend).

## Semántica ARIA (WAI-ARIA APG)

- Menús ☰ y «Menú ▾»: patrón **«Menu Button»** con `aria-expanded`,
  `aria-haspopup` y `role="menuitem"`; el foco vuelve al trigger al
  cerrar (`Escape`, clic fuera o elección).
- Vistas: en angosto, `menuitemradio` con `aria-checked`; en ancho,
  **«Radio Group»** nativo (`fieldset` + `legend` + `radio`), sin
  `role="toolbar"` (que exigiría roving tabindex).
- Barra de formato del editor: sí lleva `role="toolbar"`, **con** el
  roving tabindex que el rol exige (un tab stop, flechas para moverse).
  En los dos casos el rol se usa cuando viene con su patrón completo.
- El caret «▼» va `aria-hidden` para que el nombre accesible del
  disparador sea solo «Menú».
- Vínculo externo («Ver en GitHub»): `<a role="menuitem">` con
  `target="_blank" rel="noopener noreferrer"`.

## Selección no solo por color (WCAG 1.4.1)

La selección y los estados del segmentado se distinguen también por
posición/marca, no únicamente por el color de la etiqueta.

## Sin `alert()` ni `confirm()`

Las confirmaciones destructivas son inline, en español, con el aviso de
lo que se pierde; el backend borra sin preguntar y la confirmación vive
en el frontend.

## Teclado

| Tecla | Acción |
|---|---|
| `Escape` | Cierra el panel de acción, el explorador desplegable o el menú abierto (devolviendo el foco a su trigger) |
| `Ctrl`/`Cmd` + `S` | Guarda la nota |
| `Ctrl`/`Cmd` + `B` | Negrita en la selección del editor |
| `Ctrl`/`Cmd` + `I` | Cursiva en la selección del editor |
| `Ctrl`/`Cmd` + `K` | Convierte la selección del editor en enlace |
| `Ctrl`/`Cmd` + `Z` | Deshacer en el editor (undo nativo del navegador) |
| `Ctrl`/`Cmd` + `Y`, `Ctrl`/`Cmd` + `Shift` + `Z` | Rehacer en el editor |
| `Ctrl`/`Cmd` + `F` | Abre la barra de buscar con el foco en el editor |
| `Ctrl`/`Cmd` + `H` | Abre la barra con la fila de reemplazar |
| `Enter` / `Shift` + `Enter` (barra de búsqueda) | Coincidencia siguiente / anterior |
| `Escape` (barra de búsqueda) | Cierra la barra y devuelve el foco al editor |
| `Tab` (editor) | Escribe dos espacios |
| `Shift` + `Tab` (editor) | Sale del `textarea` |
| `←`/`→`, `Inicio`/`Fin` (toolbar) | Mueve el foco entre los botones habilitados |

Los tres atajos de formato comparten mapa con los botones de la barra
(`FORMATOS` en `static/js/app.js`), así que no pueden divergir: lo que
promete el `title` de un botón es lo que ejecuta su tecla. Lo mismo hace
`data-herr` para los cuatro botones nuevos (deshacer, rehacer, buscar,
reemplazar): sus atajos entran por la misma función que su clic. Solo
actúan con el foco dentro del `textarea`, así que `Ctrl+K` no secuestra
el buscador del navegador salvo que se esté escribiendo en la nota. El
`Ctrl+Z` de deshacer no se intercepta: manda el undo nativo y su evento
`input` refresca los botones.

La barra lleva `role="toolbar"`, y ese rol exige **un solo tab stop**
(WAI-ARIA APG, patrón «Toolbar»): `Tab` entra y sale de la barra de una
vez, y dentro se navega con las flechas. Con 20 botones tabulables, el
`Tab` habría costado 20 paradas entre el editor y la vista previa. Los
botones `disabled` (deshacer y rehacer sin historial) quedan fuera del
tab stop: un control apagado no recibe foco, y si el que era tabbable
quedara apagado, `Tab` ya no entraría a la barra.

La barra de búsqueda, en cambio, no lleva `role="toolbar"`: es una
región `role="search"` con su contador en `aria-live="polite"` («3 de
12»), y sus botones se tabulan solos.

Los atajos y el resto de la navegación se explican también en la nota de
bienvenida, que la app crea al arrancar.
