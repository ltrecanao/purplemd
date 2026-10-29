"""La opción de ocultar el explorador existe solo donde él es columna.

En ancho (≥ 48rem) el explorador es una columna lateral sin desplegable,
y `#explorador-ocultar` es la única superficie para sacarlo de la vista.
Por debajo de 48rem ya está `#explorador-toggle`, y aparecer con las dos
superficies para lo mismo sería repetir el problema que el proyecto
resolvió unificando los menús: el botón arranca oculto y su CSS ancho lo
muestra.

El test lee `static/index.html` y `static/css/style.css` y falla si la
restricción se pierde: botón visible en angosto junto al desplegable, o
reglas de la clase `.explorador-oculto` fuera del `min-width: 48rem`
(desde donde la preferencia guardada podría romper el layout angosto).
"""

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
HTML = STATIC / "index.html"
CSS = STATIC / "css" / "style.css"


def sin_comentarios(css: str) -> str:
    """Quita los comentarios: pueden mencionar `@media` y confundir el
    barrido de bloques de abajo (la hoja ya lo hace en su intro)."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def reglas(texto: str) -> list[tuple[str, str]]:
    """(selector, cuerpo) de cada regla simple de un fragmento de CSS."""
    return [(sel.strip(), cuerpo) for sel, cuerpo in re.findall(r"([^{}]+)\{([^{}]*)\}", texto)]


def bloques_media(css: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """[(condición, reglas)] de cada bloque `@media` del CSS.

    Los bloques cierran con `}` en la primera columna (la convención de
    la hoja, la misma que aprovecha `test_texto_visible.py`), y las
    reglas de adentro son de un solo nivel.
    """
    bloques = []
    pos = 0
    while True:
        inicio = css.find("@media", pos)
        if inicio == -1:
            return bloques
        apertura = css.index("{", inicio)
        condicion = css[inicio:apertura].removeprefix("@media").strip()
        fin = css.index("\n}", inicio) + 2
        bloques.append((condicion, reglas(css[apertura + 1 : fin - 2])))
        pos = fin


def sin_media(css: str) -> str:
    """Deja solo las reglas base, fuera de todo bloque `@media`."""
    resto = []
    pos = 0
    while True:
        inicio = css.find("@media", pos)
        if inicio == -1:
            return "".join(resto) + css[pos:]
        resto.append(css[pos:inicio])
        pos = css.index("\n}", inicio) + 2


def es_corte_ancho(condicion: str) -> bool:
    """¿La condición cubre todo `min-width: 48rem`, sin techo?

    `48rem … 60rem` no alcanza: el botón y la preferencia tienen que
    valer también por arriba de 60rem, donde el explorador sigue siendo
    columna.
    """
    return "min-width: 48rem" in condicion and "max-width" not in condicion


class ExploradorOcultoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")
        cls.css = sin_comentarios(CSS.read_text(encoding="utf-8"))
        cls.base = reglas(sin_media(cls.css))
        cls.media = bloques_media(cls.css)
        cls.anchos = [r for cond, r in cls.media if es_corte_ancho(cond)]

    def test_el_boton_existe_y_controla_al_explorador(self):
        """El botón vive en la topbar, nombra la acción inicial y su
        ARIA apunta al panel que controla con la verdad del arranque
        (explorador visible hasta que la preferencia diga lo contrario)."""
        self.assertRegex(
            self.html,
            r'<button[^>]*id="explorador-ocultar"[^>]*aria-expanded="true"'
            r'[^>]*aria-controls="explorador"[^>]*>Ocultar explorador</button>',
        )

    def test_el_boton_solo_se_muestra_desde_48rem(self):
        """La regla base lo esconde y solo un `min-width: 48rem` sin
        techo lo muestra: si se pierde cualquiera de las dos caras, el
        botón aparece en angosto junto al desplegable o desaparece en
        ancho (y con él, la única superficie para recuperar el panel)."""
        ocultos = [
            cuerpo
            for selector, cuerpo in self.base
            if selector.endswith("#explorador-ocultar") and "display: none" in cuerpo
        ]
        self.assertTrue(ocultos, "falta `#explorador-ocultar { display: none }` en la base")
        mostrados = [
            cuerpo
            for reglas_anchas in self.anchos
            for selector, cuerpo in reglas_anchas
            if selector.endswith("#explorador-ocultar") and "display: inline-flex" in cuerpo
        ]
        self.assertTrue(
            mostrados,
            "falta `#explorador-ocultar { display: inline-flex }` en el corte ancho",
        )

    def test_la_preferencia_no_toca_el_layout_angosto(self):
        """La clase `.explorador-oculto` existe solo en el corte ancho sin
        techo: por debajo de 48rem la preferencia guardada no puede
        colapsar la grilla ni tapar al desplegable, aunque la clave
        `purplemd_explorador_oculto` siga guardada en el navegador."""
        en_ancho = [
            (selector, cuerpo)
            for reglas_anchas in self.anchos
            for selector, cuerpo in reglas_anchas
            if "explorador-oculto" in selector
        ]
        self.assertTrue(
            any("grid-template-columns: minmax(0, 1fr)" in c for _, c in en_ancho),
            "falta la regla que colapsa `.app.explorador-oculto` a una columna",
        )
        self.assertTrue(
            any("display: none" in c for _, c in en_ancho),
            "falta la regla que oculta `.panel-explorador` con la clase",
        )
        fuera = [selector for selector, _ in self.base if "explorador-oculto" in selector]
        fuera += [
            selector
            for cond, r in self.media
            if not es_corte_ancho(cond)
            for selector, _ in r
            if "explorador-oculto" in selector
        ]
        self.assertEqual(
            fuera,
            [],
            "las reglas .explorador-oculto deben vivir solo en `min-width: 48rem`",
        )


if __name__ == "__main__":
    unittest.main()
