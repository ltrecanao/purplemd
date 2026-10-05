"""Principio perceptible: el texto del explorador nunca puede quedar ilegible.

En el breakpoint intermedio (`48rem`–`60rem`) el explorador colapsa el texto
con `font-size: 0` y lo recupera en el `::before` con `content: attr(title)`.
Ese es el único mecanismo válido: un `font-size: 0` sobre algo sin `title`
deja el contenido en la página pero sin forma de leerlo (botones «Crear» e
«Importar .md» eran cajas vacías, y lo que se escribe en un input no tiene
reemplazo posible, por eso el input nunca colapsa).

El test lee `static/css/style.css` y falla si aparece una regla de colapso
cuyo selector no termine en `[title]`.
"""

import re
import unittest
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "style.css"
BLOQUE = "@media (min-width: 48rem) and (max-width: 60rem) {"
COLAPSO = re.compile(r"font-size:\s*0\s*;")


class TextoVisibleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        css = CSS.read_text(encoding="utf-8")
        inicio = css.index(BLOQUE)
        # El bloque cierra con una llave en la primera columna; las reglas
        # de adentro cierran indentadas.
        cls.bloque = css[inicio : css.index("\n}", inicio) + 2]
        cls.reglas = [
            (selector.strip(), cuerpo)
            for selector, cuerpo in re.findall(r"([^{}]+)\{([^{}]*)\}", cls.bloque)
        ]

    def test_hay_reglas_de_colapso_en_el_breakpoint(self):
        """Si alguien borra el colapso entero, este test lo dice primero:
        la rama no debe perderse en silencio, se cambia con intención."""
        colapsos = [c for _, c in self.reglas if COLAPSO.search(c)]
        self.assertTrue(colapsos)

    def test_todo_colapso_tiene_title_como_reemplazo(self):
        """`font-size: 0` solo con `attr(title)`: si no hay `title` que
        mostrar en el `::before`, el texto queda invisible."""
        for selector, cuerpo in self.reglas:
            if not COLAPSO.search(cuerpo):
                continue
            with self.subTest(selector=selector):
                self.assertRegex(selector, r"\[title\]$")

    def test_el_input_que_el_usuario_escribe_nunca_colapsa(self):
        """`attr(value)` no es dinámico: el valor escrito no puede salir
        por un `::before`, así que ese input conserva su tamaño."""
        for selector, cuerpo in self.reglas:
            if "input" in selector:
                with self.subTest(selector=selector):
                    self.assertIsNone(COLAPSO.search(cuerpo))


if __name__ == "__main__":
    unittest.main()
