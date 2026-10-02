# Accesibilidad

Reglas de accesibilidad de PurpleMD: contraste, targets, foco, avisos y
teclado. El comportamiento detallado de cada superficie (menús, barra,
toasts) está en [ARQUITECTURA.md](ARQUITECTURA.md); la referencia HTTP,
en [API.md](API.md).

## Contraste

Medido con la fórmula de luminancia relativa de WCAG 2.x sobre los
tokens de `static/css/style.css` (tema claro y oscuro):

| Par de tokens | Claro | Oscuro |
|---|---|---|
| `--texto` sobre `--fondo` | **15.29:1** | **15.58:1** |
| `--texto-tenue` sobre `--fondo` | 6.58:1 | 7.69:1 |
| Texto de botón (`--sobre-acento` sobre `--acento`) | 7.10:1 | 6.70:1 |
| `--acento-fuerte` sobre `--fondo` | 8.25:1 | 4.40:1 |
| `--ok` sobre `--fondo` | 5.43:1 | 10.69:1 |
| `--error` sobre `--fondo` | 6.00:1 | 9.81:1 |

El texto normal supera **AAA (≥ 7:1)** en ambos temas. La paleta vive
en `:root` y en el bloque `prefers-color-scheme: dark` de `style.css`:
cualquier cambio de token debe volver a medirse.

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
| `Tab` (editor) | Escribe dos espacios |
| `Shift` + `Tab` (editor) | Sale del `textarea` |

Los atajos y el resto de la navegación se explican en la nota de
bienvenida, que la app crea al arrancar.
