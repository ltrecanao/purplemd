"""Conversión de markdown a HTML para la vista previa de purplemd.

Cubre lo esencial de GFM: tablas, task lists, strikethrough y código
cercado con lenguaje (este último ya viene de CommonMark).

`html: False` en MarkdownIt es la sanitización del proyecto: el HTML crudo
que escriba el usuario se escapa como texto en vez de inyectarse en la
página. Así no hace falta una librería de saneamiento aparte ni confiar en
que una whitelist cubra todos los casos.

El resaltado de sintaxis lo hace Pygments con un estilo propio (Aura) que
se aplica DESPUÉS del render: Pygments genera HTML seguro (escapa el
contenido), así que no rompe la sanitización.
"""

import logging
import re
from html import escape, unescape

from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter  # type: ignore
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

# Logger compartido con `api`: un fallo de render no puede quedar en silencio,
# el fallback a `<pre>` se registra en WARNING con su traceback para que se
# vea en producción. Los tests lo capturan con `assertLogs("purplemd")`.
logger = logging.getLogger("purplemd")

# Patron para detectar emails en URLs de links markdown: [texto](email@dominio.com)
_EMAIL_RE = re.compile(r'^[\w.+-]+@[\w-]+\.[\w.-]+$')
# Patron para detectar URLs "bare" sin protocolo: [texto](dominio.com/ruta)
# Excluye emails, rutas relativas (./, ../), anchors (#), y URLs con protocolo
_BARE_URL_RE = re.compile(
    r'^(?!mailto:|https?://|ftp://|#|\.?/|/)'  # no protocolo, no anchor, no ruta relativa
    r'[\w-]+(\.[\w-]+)+'  # dominio con al menos un punto
    r'(?:/[\w./?#&=%+-]*)?$'  # path opcional
)

def _normalizar_urls_en_links(markdown: str) -> str:
    """Normaliza URLs en links markdown antes de renderizar.

    - Emails sin protocolo -> mailto:
    - URLs bare (dominio.com/ruta) -> https://
    - URLs con protocolo, anchors, rutas relativas -> sin cambios
    """
    def reemplazo(match: re.Match) -> str:
        texto, url = match.group(1), match.group(2)
        url_stripped = url.strip()
        if _EMAIL_RE.match(url_stripped):
            url = f"mailto:{url_stripped}"
        elif _BARE_URL_RE.match(url_stripped):
            url = f"https://{url_stripped}"
        return f"[{texto}]({url})"

    # Pattern: [texto](url) - captura el texto y la URL
    link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    return link_pattern.sub(reemplazo, markdown)

_md = (
    MarkdownIt("commonmark", {"html": False})
    .enable(["table", "strikethrough"])
    .use(tasklists_plugin)
)

_formatter = HtmlFormatter(style="dracula", nowrap=True)

# Bloque de código con lenguaje: <pre><code class="language-X">...</code></pre>
_BLOQUE = re.compile(
    r'<pre><code class="language-([^"]+)">(.*?)</code></pre>',
    re.DOTALL,
)


def _resaltar(html: str) -> str:
    """Resalta los bloques de código con Pygments.

    `markdown-it` emite el código escapado (`&lt;`, `&gt;`, `&amp;`), así
    que se desescapa antes de pasarlo a Pygments, que lo escapa de nuevo
    en su output. Si el lenguaje no existe o no tiene info string, el
    bloque se deja como está.
    """
    def reemplazo(matcho: re.Match) -> str:
        lenguaje, codigo = matcho.group(1), matcho.group(2)
        try:
            lexer = get_lexer_by_name(lenguaje)
        except ClassNotFound:
            return matcho.group(0)
        return f'<div class="highlight">{highlight(unescape(codigo), lexer, _formatter)}</div>'

    return _BLOQUE.sub(reemplazo, html)


# Paleta del resaltado en el export a PDF: la por defecto de Pygments.
# La vista previa del navegador sí usa la personalizada (dracula, con sus
# colores escritos a mano en `static/css/style.css`); el PDF en cambio no
# lleva una tabla de colores propia: la saca de acá.
_FORMATO_PDF = HtmlFormatter(style="default")


def css_resaltado(selector: str = ".highlight") -> str:
    """Reglas CSS del resaltado con la paleta por defecto de Pygments.

    `_html_para_pdf` las inserta en el `<style>` del documento, de modo que
    los colores salen del propio Pygments en vez de quedar duplicados como
    literales en `api.py`.
    """
    return _FORMATO_PDF.get_style_defs(selector)


def fondo_resaltado() -> str:
    """Color de fondo de los bloques de código, tomado del mismo estilo.

    El PDF lo usa en `pre` (el bloque sin lenguaje, que no pasa por
    Pygments) para que los dos tipos de bloque queden con el mismo fondo.
    """
    return _FORMATO_PDF.style.background_color or "#ffffff"


def renderizar(markdown: str) -> str:
    """Convierte markdown a HTML listo para insertar en la vista previa.

    Sin memoización a propósito: una caché retendría HTML de notas grandes
    (hasta MAX_BYTES) en memoria de forma indefinida en favor de un caso que
    markdown-it ya resuelve barato, y la API renderiza a lo sumo una nota
    por request.

    Normaliza URLs en links antes de renderizar:
    - Emails sin protocolo -> mailto:
    - URLs bare (dominio.com/ruta) -> https://

    Nunca lanza por contenido raro: si el render falla por un caso no
    previsto, devuelve el markdown escapado dentro de un `<pre>` para que
    la vista previa muestre el texto crudo en lugar de romper la página.
    """
    try:
        markdown_normalizado = _normalizar_urls_en_links(markdown)
        return _resaltar(_md.render(markdown_normalizado))
    except Exception as exc:
        logger.warning("render falló; se devuelve el markdown escapado", exc_info=exc)
        return f"<pre>{escape(markdown)}</pre>"
