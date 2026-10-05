import logging
import unittest
from unittest.mock import patch

import renderer


class RenderBasicoTests(unittest.TestCase):
    def test_parrafos(self):
        self.assertEqual(renderer.renderizar("hola"), "<p>hola</p>\n")
        self.assertEqual(renderer.renderizar("hola\n\nchau"), "<p>hola</p>\n<p>chau</p>\n")

    def test_encabezados(self):
        self.assertEqual(renderer.renderizar("# Título"), "<h1>Título</h1>\n")
        self.assertEqual(renderer.renderizar("## Sección"), "<h2>Sección</h2>\n")

    def test_listas(self):
        html = renderer.renderizar("- uno\n- dos")
        self.assertIn("<ul>", html)
        self.assertIn("<li>uno</li>", html)
        html_ordenada = renderer.renderizar("1. uno")
        self.assertIn("<ol>", html_ordenada)

    def test_enlaces(self):
        html = renderer.renderizar("[título](https://example.com)")
        self.assertIn('<a href="https://example.com">título</a>', html)

    def test_codigo_cercado_con_lenguaje(self):
        html = renderer.renderizar("```python\nprint(1)\n```")
        # Con lenguaje conocido, Pygments resalta: hay clases de token.
        self.assertIn('class="nb"', html)  # name.builtin (print)
        self.assertIn('class="mi"', html)  # literal.number.integer (1)


class GfmTests(unittest.TestCase):
    def test_tablas(self):
        html = renderer.renderizar("| a | b |\n|---|---|\n| 1 | 2 |")
        self.assertIn("<table>", html)
        self.assertIn("<th>a</th>", html)
        self.assertIn("<td>2</td>", html)
        self.assertIn("</table>", html)

    def test_task_lists(self):
        html = renderer.renderizar("- [x] hecho\n- [ ] pendiente")
        self.assertIn('type="checkbox"', html)
        self.assertIn("task-list-item", html)
        self.assertIn('checked="checked"', html)
        # La casilla de "pendiente" no lleva checked.
        self.assertEqual(html.count('checked="checked"'), 1)
        self.assertIn("hecho", html)

    def test_strikethrough(self):
        self.assertEqual(renderer.renderizar("~~tachado~~"), "<p><s>tachado</s></p>\n")


class SanitizacionTests(unittest.TestCase):
    def test_el_html_crudo_se_escapa_en_vez_de_inyectarse(self):
        casos = (
            "<script>alert(1)</script>",
            '<img src=x onerror="alert(1)">',
            "<b>negrita</b>",
            '<a href="javascript:alert(1)">click</a>',
        )
        for markdown in casos:
            with self.subTest(markdown=markdown):
                html = renderer.renderizar(markdown)
                self.assertNotIn("<script>", html)
                self.assertNotIn("<img", html)
                self.assertNotIn("<b>", html)
                self.assertNotIn("<a href", html)
                self.assertIn("&lt;", html)

    def test_el_texto_de_un_html_escaped_sigue_visible(self):
        html = renderer.renderizar("<script>alert(1)</script>")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)


class ResaltadoTests(unittest.TestCase):
    def test_lenguaje_conocido_resalta(self):
        html = renderer.renderizar("```python\nprint('hola')\n```")
        self.assertIn('class="nb"', html)  # name.builtin (print)
        self.assertIn('class="s1"', html)  # literal.string.single

    def test_lenguaje_bash_resalta(self):
        html = renderer.renderizar("```bash\necho hola\n```")
        self.assertIn('class="nb"', html)  # echo es builtin en bash

    def test_lenguaje_html_resalta(self):
        html = renderer.renderizar("```html\n<p>hola</p>\n```")
        self.assertIn('class="nt"', html)  # name.tag

    def test_lenguaje_css_resalta(self):
        html = renderer.renderizar("```css\nbody { color: red; }\n```")
        self.assertIn('class="nt"', html)  # name.tag (selector)

    def test_lenguaje_js_resalta(self):
        html = renderer.renderizar("```js\nconsole.log('hola')\n```")
        self.assertIn('class="nx"', html)  # name.other (console)

    def test_sin_lenguaje_no_resalta(self):
        html = renderer.renderizar("```\ncodigo\n```")
        self.assertIn('<pre><code>', html)
        self.assertNotIn('class="nb"', html)

    def test_lenguaje_desconocido_no_resalta(self):
        html = renderer.renderizar("```lenguajefalso\ncodigo\n```")
        self.assertIn("codigo", html)
        self.assertNotIn('class="nb"', html)

    def test_sanitizacion_sigue_funcionando_con_resaltado(self):
        html = renderer.renderizar("```python\n<script>alert(1)</script>\n```")
        self.assertNotIn("<script>", html)
        # Pygments escapa el HTML crudo dentro del código: no se inyecta.
        self.assertIn("&lt;", html)
        self.assertIn("&gt;", html)


class RobustezTests(unittest.TestCase):
    def test_nunca_lanza_por_contenido_raro(self):
        casos = (
            "",
            "\x00",
            "```sin cerrar",
            "[" * 500,
            "|" * 100,
            "- [x] " * 200,
            "\n" * 500,
            "# " * 100,
        )
        for markdown in casos:
            with self.subTest(markdown=markdown[:20]):
                self.assertIsInstance(renderer.renderizar(markdown), str)

    def test_contenido_con_extension_md_invalida_no_importa(self):
        # El renderer no toca el sistema de archivos: cualquier texto pasa.
        self.assertIsInstance(renderer.renderizar("../../etc/passwd"), str)

    def test_el_fallback_se_registra_en_el_log(self):
        """Si el render explota, el `<pre>` salva la vista previa, pero el
        fallo no puede quedar en silencio: va al log con su traceback."""
        with patch("renderer._md.render", side_effect=RuntimeError("parser roto")):
            with self.assertLogs("purplemd", level="WARNING") as captura:
                html = renderer.renderizar("# hola")
        self.assertEqual(html, "<pre># hola</pre>")
        texto = logging.Formatter().format(captura.records[0])
        self.assertIn("RuntimeError: parser roto", texto)
        self.assertIn("Traceback (most recent call last)", texto)


if __name__ == "__main__":
    unittest.main()
