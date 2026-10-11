"""Tests de contraste WCAG sobre la paleta real de `static/css/style.css`.

La paleta es la única fuente de verdad del color en el proyecto: vive en
`:root` y el modo oscuro solo reescribe esos mismos tokens. Estos tests la
leen de disco y calculan el contraste con la fórmula de luminancia relativa
de WCAG 2.x, así que cualquier cambio de token se mide solo.

Dos niveles, como exige `AGENTS.md`:

- **AA (4.5:1)**: infracción si falla. Es el mínimo de WCAG 2.x para texto
  normal y aplica a todos los pares donde un token es texto sobre un fondo.
- **AAA (7:1)**: la aspiración del proyecto para el texto principal. Se
  valida por separado para poder distinguir «incumple AA» (bug) de «no
  llega a AAA» (paleta más suave de lo que pide la regla).
"""

import re
import unittest
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "style.css"

# Par mínimo absoluto de WCAG: texto normal.
MINIMO_AA = 4.5
# La regla de AGENTS.md para texto principal.
MINIMO_AAA = 7.0


def _cuerpo(css: str, inicio: int) -> str:
    """Devuelve el cuerpo de la regla que abre en `inicio` (llaves balanceadas)."""
    apertura = css.index("{", inicio)
    nivel = 0
    for i in range(apertura, len(css)):
        if css[i] == "{":
            nivel += 1
        elif css[i] == "}":
            nivel -= 1
            if nivel == 0:
                return css[apertura + 1 : i]
    raise AssertionError(f"la regla que empieza en {inicio} nunca cierra")


def _regla(css: str, selector: str) -> str:
    """Cuerpo de la PRIMERA regla cuyo selector es exactamente `selector`.

    Se busca `selector` seguido de espacios y `{` (no dentro de un comentario
    ni de otro selector que simplemente lo contenga), y se balancean llaves.
    """
    patron = re.compile(rf"(?<![\w-]){re.escape(selector)}\s*\{{")
    coincidencia = patron.search(css)
    if not coincidencia:
        raise AssertionError(f"no se encontró la regla `{selector}` en style.css")
    return _cuerpo(css, coincidencia.start())


def _tokens(bloque: str) -> dict:
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", bloque))


def _temas() -> dict:
    """Tokens de los tres bloques de la paleta, por nombre.

    - `claro`: `:root`, el valor por defecto.
    - `respaldo`: `:root:not([data-tema])` dentro del media query (sin JS).
    - `oscuro`: `:root[data-tema="oscuro"]`, el camino vivo.
    """
    css = CSS.read_text(encoding="utf-8")
    claro = _tokens(_regla(css, ":root"))
    media = _regla(css, "@media (prefers-color-scheme: dark)")
    respaldo = _tokens(_regla(media, ":root:not([data-tema])"))
    vivo = _tokens(_regla(css, ':root[data-tema="oscuro"]'))
    # El tema oscuro que se mide es el camino vivo, heredando del claro
    # los tokens que no reescribe (aunque en la práctica no debe faltar ninguno).
    oscuro = dict(claro)
    oscuro.update(vivo)
    return {"claro": claro, "oscuro": oscuro, "respaldo": respaldo, "vivo": vivo}


def _luminancia(hexcolor: str) -> float:
    """Luminancia relativa (WCAG 2.x) de un color `#rrggbb`."""
    bruto = hexcolor.lstrip("#")
    canales = [int(bruto[i : i + 2], 16) / 255 for i in (0, 2, 4)]

    def lineal(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lineal(c) for c in canales)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(a: str, b: str) -> float:
    """Ratio de contraste entre dos colores, 1.0 a 21.0."""
    la, lb = _luminancia(a), _luminancia(b)
    alto, bajo = max(la, lb), min(la, lb)
    return (alto + 0.05) / (bajo + 0.05)


# Pares donde el PRIMER token es texto y el SEGUNDO es su fondo real.
# Se recorrieron todas las declaraciones `color: var(--x)` de style.css y se
# les asignó el fondo del contenedor donde caen (--fondo = página,
# --panel = tarjetas, cabeceras, toasts y formularios).
PARES_TEXTO = [
    ("--texto", "--fondo", "cuerpo"),
    ("--texto", "--panel", "cuerpo sobre panel"),
    ("--texto-tenue", "--fondo", "secundario"),
    ("--texto-tenue", "--panel", "secundario sobre panel"),
    ("--acento", "--fondo", "acento"),
    ("--acento", "--panel", "acento sobre panel"),
    ("--error", "--fondo", "error"),
    ("--error", "--panel", "error sobre panel"),
    ("--ok", "--fondo", "ok"),
    ("--ok", "--panel", "ok sobre panel"),
    # Botón acento: fondo = acento / acento-fuerte, texto = sobre-acento.
    # El hover pasa el fondo a --acento-fuerte, por eso son dos pares.
    ("--sobre-acento", "--acento", "botón acento"),
    ("--sobre-acento", "--acento-fuerte", "botón acento (hover/active)"),
    # .btn-peligro:hover invierte: fondo --error, texto --panel.
    ("--panel", "--error", "botón peligro (hover)"),
    # Botón oficial de Google: texto de su guía sobre su propio fondo,
    # en reposo, hover y active (los tres fondos vienen de tokens).
    ("--google-texto", "--google-fondo", "botón Google"),
    ("--google-texto", "--google-hover", "botón Google (hover)"),
    ("--google-texto", "--google-activo", "botón Google (active)"),
    # Letra «MD» del logo en la pantalla de acceso: cae sobre `.sesion-caja`
    # (`--panel`).
    ("--logo-letra", "--panel", "letra del logo"),
]

# Texto principal: lo que AGENTS.md exige a AAA.
PARES_AAA = ("--texto", "--fondo"), ("--texto", "--panel")


class ContrasteTests(unittest.TestCase):
    """La paleta cumple AA en todos lados y AAA en el texto principal."""

    @classmethod
    def setUpClass(cls):
        cls.temas = _temas()

    def test_los_dos_temas_definen_los_mismos_tokens(self):
        """El tema oscuro no puede dejar tokens sin definir ni de más."""
        self.assertEqual(
            set(self.temas["claro"]),
            set(self.temas["vivo"]),
            "claro y oscuro deben declarar exactamente los mismos tokens",
        )

    def test_el_media_query_y_el_bloque_vivo_son_identicos(self):
        """El respaldo sin JS y el camino vivo no pueden divergir.

        `@media (prefers-color-scheme: dark) { :root:not([data-tema]) }`
        pinta la página que todavía no corrió `tema.js` (o la que corre
        sin JS); `:root[data-tema="oscuro"]` manda cuando el usuario
        elige tema, aunque el sistema diga lo contrario. Si los dos
        bloques dijeran cosas distintas, el mismo usuario vería dos
        oscuros según cuándo mirara.
        """
        self.assertEqual(
            self.temas["respaldo"],
            self.temas["vivo"],
            "el media query y :root[data-tema='oscuro'] deben declarar los mismos tokens",
        )

    def test_ningun_token_esta_vacio_o_mal_formado(self):
        """Todo token es un hex de 6 dígitos: si no, los cálculos mienten."""
        for nombre, tokens in self.temas.items():
            for token, valor in tokens.items():
                with self.subTest(tema=nombre, token=token):
                    self.assertRegex(valor, r"^#[0-9a-fA-F]{6}$")

    def test_texto_normal_cumple_wcag_aa(self):
        """Ningún par de texto baja de 4.5:1 (infracción de WCAG 2.x)."""
        for nombre, tokens in self.temas.items():
            for fg, bg, uso in PARES_TEXTO:
                with self.subTest(tema=nombre, uso=uso, par=f"{fg} sobre {bg}"):
                    ratio = _contraste(tokens[fg], tokens[bg])
                    self.assertGreaterEqual(
                        ratio,
                        MINIMO_AA,
                        f"{fg} ({tokens[fg]}) sobre {bg} ({tokens[bg]}) en tema "
                        f"{nombre} da {ratio:.2f}:1, mínimo AA {MINIMO_AA}:1 ({uso})",
                    )

    def test_texto_principal_cumple_wcag_aaa(self):
        """El cuerpo de texto llega a 7:1, la regla de AGENTS.md."""
        for nombre, tokens in self.temas.items():
            for fg, bg in PARES_AAA:
                with self.subTest(tema=nombre, par=f"{fg} sobre {bg}"):
                    ratio = _contraste(tokens[fg], tokens[bg])
                    self.assertGreaterEqual(
                        ratio,
                        MINIMO_AAA,
                        f"{fg} ({tokens[fg]}) sobre {bg} ({tokens[bg]}) en tema "
                        f"{nombre} da {ratio:.2f}:1, mínimo AAA {MINIMO_AAA}:1",
                    )

    def test_el_hover_del_boton_se_distingue_del_estado_normal(self):
        """El hover no puede quedar indistinguible del reposo del botón.

        Subir el contraste a costa de emparejar los dos fondos mataría la
        feedback visual: exige una diferencia mínima de luminancia entre
        `--acento` y `--acento-fuerte`.
        """
        for nombre, tokens in self.temas.items():
            with self.subTest(tema=nombre):
                reposo = _luminancia(tokens["--acento"])
                hover = _luminancia(tokens["--acento-fuerte"])
                self.assertGreaterEqual(
                    abs(reposo - hover),
                    0.01,
                    f"en {nombre} --acento ({tokens['--acento']}) y --acento-fuerte "
                    f"({tokens['--acento-fuerte']}) casi no se diferencian",
                )


class MedicionesTests(unittest.TestCase):
    """Congela las mediciones publicadas en docs/ACCESIBILIDAD.md.

    Si un token cambia, estos valores dejan de coincidir y el test obliga a
    volver a medir y actualizar la tabla, tal como pide ese documento.
    """

    # (tema, par, ratio publicado con dos decimales)
    PUBLICADOS = [
        ("claro", ("--texto", "--fondo"), 15.29),
        ("claro", ("--texto-tenue", "--fondo"), 6.58),
        ("claro", ("--sobre-acento", "--acento"), 7.10),
        ("claro", ("--error", "--panel"), 6.54),
        ("claro", ("--ok", "--fondo"), 5.43),
        ("claro", ("--google-texto", "--google-fondo"), 16.48),
        ("claro", ("--logo-letra", "--panel"), 16.67),
        ("oscuro", ("--texto", "--fondo"), 15.58),
        ("oscuro", ("--texto-tenue", "--fondo"), 7.69),
        ("oscuro", ("--sobre-acento", "--acento"), 6.70),
        ("oscuro", ("--sobre-acento", "--acento-fuerte"), 8.41),
        ("oscuro", ("--error", "--panel"), 9.14),
        ("oscuro", ("--ok", "--fondo"), 10.69),
        ("oscuro", ("--google-texto", "--google-fondo"), 12.84),
        ("oscuro", ("--logo-letra", "--panel"), 14.51),
    ]

    @classmethod
    def setUpClass(cls):
        cls.temas = _temas()

    def test_las_mediciones_de_la_doc_coinciden_con_el_css(self):
        for tema, par, publicado in self.PUBLICADOS:
            with self.subTest(tema=tema, par=f"{par[0]} sobre {par[1]}"):
                tokens = self.temas[tema]
                real = _contraste(tokens[par[0]], tokens[par[1]])
                self.assertEqual(
                    round(real, 2),
                    publicado,
                    f"{par[0]} sobre {par[1]} en {tema} mide {real:.2f}:1 pero "
                    f"docs/ACCESIBILIDAD.md publica {publicado}:1; hay que "
                    f"volver a medir y actualizar la tabla",
                )


if __name__ == "__main__":
    unittest.main()
