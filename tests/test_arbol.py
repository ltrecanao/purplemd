"""Reglas de estructura del árbol que un repintado puede romper sin ruido.

Dos defectos que solo aparecieron al medir el árbol en el navegador, y que
ningún test de la suite alcanza a cubrir (el frontend no tiene la suya
propia, `AGENTS.md`), así que van como reglas leídas del CSS real:

1. **Las acciones no participan del flujo de la fila.** `.fila > details`
   contiene a la vez la fila de la carpeta y TODA su lista anidada: si
   `.fila-acciones` vuelve al flujo le roba ~60px a ese `details` y, con
   él, a cada nivel del subárbol — la resta se repite por nivel (medido:
   ~10px de nombre en la tercera). Superpuestas, el ancho es entero.
2. **La fila de nota reserva el hueco del chevron** (padding izquierdo
   1.35rem = 0.6rem de la fila + 0.45em de punta + 0.3em de `gap`): sin
   eso el ícono de una nota queda casi encima del de su carpeta en vez de
   un nivel más adentro, que es como alinean todos los exploradores.
3. **El título colapsado de la franja 48–60rem va en una sola línea.**
   `.entrada-nota` es flex, así que su `::before` es un hijo flex y sin
   `nowrap` se contrae a min-content: cada carácter de la ruta bajaba de
   renglón.
"""

import re
import unittest
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "style.css"


def _regla(css: str, selector: str) -> str:
    """Cuerpo de la PRIMERA regla cuyo selector es exactamente `selector`."""
    coincidencia = re.search(rf"(?<![\w-]){re.escape(selector)}\s*\{{", css)
    if not coincidencia:
        raise AssertionError(f"no se encontró la regla `{selector}` en style.css")
    apertura = css.index("{", coincidencia.start())
    nivel = 0
    for i in range(apertura, len(css)):
        if css[i] == "{":
            nivel += 1
        elif css[i] == "}":
            nivel -= 1
            if nivel == 0:
                return css[apertura + 1 : i]
    raise AssertionError(f"la regla `{selector}` nunca cierra")


class ArbolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = CSS.read_text(encoding="utf-8")

    def test_las_acciones_se_superponen_y_no_comen_el_ancho_del_subarbol(self):
        """`.fila` ancla y `.fila-acciones` va absoluta: si vuelve al flujo,
        resta ~60px a `details` en cada nivel y el subárbol se achica."""
        fila = _regla(self.css, ".fila")
        self.assertRegex(fila, r"position:\s*relative")
        acciones = _regla(self.css, ".fila-acciones")
        self.assertRegex(acciones, r"position:\s*absolute")

    def test_la_fila_de_nota_reserva_el_hueco_del_chevron(self):
        """Padding izquierdo `1.35rem` en `.entrada-nota`: es lo que pone
        al ícono de la nota un nivel más adentro que el de su carpeta."""
        nota = _regla(self.css, ".entrada-nota")
        self.assertRegex(nota, r"padding:[^;]*1\.35rem")

    def test_el_titulo_colapsado_de_la_franja_es_de_una_sola_linea(self):
        """El `::before` que repone el `title` en 48–60rem es hijo flex de
        `.entrada-nota`: sin `nowrap` se rompe carácter por carácter."""
        franja = self.css[
            self.css.index("@media (min-width: 48rem) and (max-width: 60rem) {") :
        ]
        before = _regla(franja, ".panel-explorador .entrada-nota[title]::before")
        self.assertRegex(before, r"white-space:\s*nowrap")
        self.assertRegex(before, r"text-overflow:\s*ellipsis")


if __name__ == "__main__":
    unittest.main()
