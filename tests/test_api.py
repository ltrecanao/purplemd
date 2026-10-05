import http.server
import logging
import os
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

import purplemd
import renderer
from api import FETCHER_PDF, MAX_RENDER_BYTES, _html_para_pdf, app


class ApiTestCase(unittest.TestCase):
    """Base: directorio de datos aislado en un temporal y cliente HTTP."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)
        self._entorno = patch.dict(os.environ, {"PURPLEMD_DIR": str(self.directorio)})
        self._entorno.start()
        self.addCleanup(self._entorno.stop)
        self.client = TestClient(app)

    @staticmethod
    def crear_proyecto(name: str, epoch: float | None = None) -> Path:
        """Crea el directorio de un proyecto directamente en disco."""
        ruta = Path(os.environ["PURPLEMD_DIR"]) / "projects" / name
        ruta.mkdir(parents=True, exist_ok=True)
        if epoch is not None:
            os.utime(ruta, (epoch, epoch))
        return ruta

    @classmethod
    def crear_nota(
        cls, proyecto: str, ruta: str, contenido: str, epoch: float | None = None
    ) -> Path:
        """Crea una nota anidada directamente en disco, con modificación fijable."""
        destino = cls.crear_proyecto(proyecto) / f"{ruta}.md"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(contenido, encoding="utf-8")
        if epoch is not None:
            os.utime(destino, (epoch, epoch))
        return destino


class IndexYStaticTests(ApiTestCase):
    def test_root_serves_html(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        # static/ lo escribe la sesión de frontend en paralelo y la marca
        # cambió de "purplemd" a "PurpleMD": se compara sin distinguir case.
        self.assertIn("purplemd", response.text.lower())

    def test_root_no_aparece_en_openapi(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertNotIn("/", paths)

    def sirve_static(self, ruta: str, tipo: str) -> None:
        response = self.client.get(ruta)
        self.assertEqual(response.status_code, 200)
        self.assertIn(tipo, response.headers["content-type"])

    def test_static_css(self):
        self.sirve_static("/static/css/style.css", "text/css")

    def test_static_js(self):
        self.sirve_static("/static/js/app.js", "javascript")

    def test_static_inexistente_da_404(self):
        response = self.client.get("/static/css/no-existe.css")
        self.assertEqual(response.status_code, 404)


class PlantillasTests(ApiTestCase):
    """Las plantillas son recursos en `plantillas/`, listadas en su manifiesto."""

    raiz = Path(__file__).resolve().parent.parent / "plantillas"

    def manifiesto(self) -> dict:
        response = self.client.get("/plantillas/indice.json")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_manifiesto_lista_las_doce_plantillas(self):
        plantillas = self.manifiesto()["plantillas"]
        self.assertEqual(len(plantillas), 12)
        self.assertEqual(plantillas[0], "propuesta-comercial")
        self.assertEqual(plantillas[-1], "guia-paso-a-paso")

    def test_cada_plantilla_del_manifiesto_existe_y_se_sirve(self):
        for ruta in self.manifiesto()["plantillas"]:
            with self.subTest(ruta=ruta):
                self.assertTrue((self.raiz / f"{ruta}.md").is_file())
                response = self.client.get(f"/plantillas/{ruta}.md")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.text.lstrip().startswith("# "))

    def test_todo_archivo_del_directorio_esta_en_el_manifiesto(self):
        # Si alguien dropea un .md sin sumarlo al manifiesto, nunca se
        # cargaría en la app: el CI tiene que quejarse acá.
        archivos = list(self.raiz.rglob("*.md"))
        # Las plantillas son planas: ningún subdirectorio (clientes/ y
        # empresas/ se eliminaron).
        self.assertTrue(all(p.parent == self.raiz for p in archivos))
        self.assertEqual({p.stem for p in archivos}, set(self.manifiesto()["plantillas"]))

    def test_las_plantillas_no_tienen_emojis(self):
        # La marca de agua del PDF y los encabezados usan fuentes libres:
        # un emoji podría no tener glifo y salir como cajita.
        for ruta in self.manifiesto()["plantillas"]:
            with self.subTest(ruta=ruta):
                texto = (self.raiz / f"{ruta}.md").read_text(encoding="utf-8")
                self.assertFalse(any(ord(c) > 0x2100 for c in texto if c not in "—–…·«»"))

    def test_las_plantillas_tienen_un_solo_titulo(self):
        for ruta in self.manifiesto()["plantillas"]:
            with self.subTest(ruta=ruta):
                texto = (self.raiz / f"{ruta}.md").read_text(encoding="utf-8")
                titulos = sum(1 for linea in texto.splitlines() if linea.startswith("# "))
                self.assertEqual(titulos, 1)

    def test_los_campos_a_completar_estan_entre_corchetes(self):
        # Formato único de marcador: [NOMBRE DEL CAMPO]. Un placeholder
        # suelto sin corchetes se exportaría al PDF como texto normal.
        formal = (self.raiz / "presupuesto-formal.md").read_text(encoding="utf-8")
        simple = (self.raiz / "presupuesto-servicio.md").read_text(encoding="utf-8")
        self.assertIn("[FECHA]", formal)
        self.assertIn("[MONTO", simple)


class ProyectosEndpointTests(ApiTestCase):
    def test_listado_vacio(self):
        response = self.client.get("/api/projects")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"projects": []})

    def test_crear_responde_201_y_escribe_en_disco(self):
        response = self.client.post("/api/projects", json={"name": "mi proyecto"})
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), {"name", "modified"})
        self.assertEqual(body["name"], "mi proyecto")
        self.assertIsInstance(body["modified"], float)
        self.assertTrue((self.directorio / "projects" / "mi proyecto").is_dir())

    def test_crear_duplicado_responde_409_sin_borrar_el_directorio(self):
        self.client.post("/api/projects", json={"name": "saludo"})
        response = self.client.post("/api/projects", json={"name": "saludo"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("ya existe", str(response.json()["detail"]))
        self.assertTrue((self.directorio / "projects" / "saludo").is_dir())

    def test_crear_nombre_invalido_responde_422_en_espanol(self):
        invalidos = ("", "../etc/passwd", "a/b", ".oculta", "punto.txt", "con*estrella")
        for nombre in invalidos:
            with self.subTest(nombre=nombre):
                response = self.client.post("/api/projects", json={"name": nombre})
                self.assertEqual(response.status_code, 422)
                self.assertIn("nombre", response.text.lower())
        self.assertFalse((self.directorio / "projects").exists())

    def test_crear_sin_nombre_responde_422(self):
        response = self.client.post("/api/projects", json={})
        self.assertEqual(response.status_code, 422)

    def test_crear_nombre_con_extension_no_la_conserva(self):
        response = self.client.post("/api/projects", json={"name": "saludo.md"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["name"], "saludo")
        self.assertEqual(
            [p.name for p in (self.directorio / "projects").iterdir()], ["saludo"]
        )

    def test_listado_ordenado_por_modificacion_descendente(self):
        self.crear_proyecto("vieja", epoch=1000)
        self.crear_proyecto("nueva", epoch=3000)
        self.crear_proyecto("media", epoch=2000)
        response = self.client.get("/api/projects")
        self.assertEqual(response.status_code, 200)
        entradas = response.json()["projects"]
        self.assertEqual(
            [entrada["name"] for entrada in entradas], ["nueva", "media", "vieja"]
        )
        for entrada in entradas:
            self.assertEqual(set(entrada), {"name", "modified"})

    def test_el_listado_omite_lo_que_no_es_un_proyecto(self):
        base = self.directorio / "projects"
        base.mkdir(parents=True)
        (base / "avulso.md").write_text("no es un proyecto", encoding="utf-8")
        (base / ".oculta").mkdir()
        self.crear_proyecto("visible")
        response = self.client.get("/api/projects")
        self.assertEqual(
            [entrada["name"] for entrada in response.json()["projects"]], ["visible"]
        )


class ArbolEndpointTests(ApiTestCase):
    def test_arbol_de_un_proyecto_vacio(self):
        self.crear_proyecto("arbol")
        response = self.client.get("/api/projects/arbol/tree")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"project": "arbol", "entries": []})

    def test_arbol_recursivo_con_carpetas_primero_y_notas_despues(self):
        for nota in ("raiz", "zeta", "alpha/beta", "alpha/sub/gamma", "omega/delta"):
            self.crear_nota("arbol", nota, nota)
        response = self.client.get("/api/projects/arbol/tree")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["project"], "arbol")
        self.assertEqual(
            [(entrada["type"], entrada["path"]) for entrada in body["entries"]],
            [
                ("dir", "alpha"),
                ("dir", "alpha/sub"),
                ("dir", "omega"),
                ("note", "alpha/beta"),
                ("note", "alpha/sub/gamma"),
                ("note", "omega/delta"),
                ("note", "raiz"),
                ("note", "zeta"),
            ],
        )
        for entrada in body["entries"]:
            self.assertEqual(set(entrada), {"type", "path", "modified"})
            self.assertIsInstance(entrada["modified"], float)
            self.assertFalse(entrada["path"].endswith(".md"))

    def test_arbol_omite_archivos_que_no_son_notas(self):
        self.crear_nota("arbol", "saludo", "hola")
        avulso = Path(os.environ["PURPLEMD_DIR"]) / "projects" / "arbol" / "notas.txt"
        avulso.write_text("no es md", encoding="utf-8")
        response = self.client.get("/api/projects/arbol/tree")
        self.assertEqual(
            [(e["type"], e["path"]) for e in response.json()["entries"]],
            [("note", "saludo")],
        )

    def test_arbol_de_un_proyecto_inexistente_responde_404(self):
        response = self.client.get("/api/projects/fantasma/tree")
        self.assertEqual(response.status_code, 404)
        self.assertIn("no existe el proyecto", str(response.json()["detail"]))

    def test_arbol_de_un_nombre_invalido_responde_422(self):
        # Va codificado para que la normalización de dot segments del URL no
        # se coma el `..` antes de que llegue al handler.
        for nombre in ("punto.txt", "%2e%2e"):
            with self.subTest(nombre=nombre):
                response = self.client.get(f"/api/projects/{nombre}/tree")
                self.assertEqual(response.status_code, 422)
                self.assertIn("nombre", response.text.lower())


class NotasEndpointTests(ApiTestCase):
    def test_crear_responde_201_y_escribe_en_disco(self):
        self.crear_proyecto("proyecto")
        response = self.client.post(
            "/api/projects/proyecto/notes", json={"path": "saludo", "content": "hola"}
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), {"project", "path", "content", "modified"})
        self.assertEqual(body["project"], "proyecto")
        self.assertEqual(body["path"], "saludo")
        self.assertEqual(body["content"], "hola")
        ruta = self.directorio / "projects" / "proyecto" / "saludo.md"
        self.assertEqual(ruta.read_text(encoding="utf-8"), "hola")

    def test_crear_una_nota_anidada_crea_las_carpetas_que_falten(self):
        self.crear_proyecto("proyecto")
        response = self.client.post(
            "/api/projects/proyecto/notes",
            json={"path": "diseños/2026/logo", "content": "hola"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["path"], "diseños/2026/logo")
        ruta = (
            self.directorio / "projects" / "proyecto" / "diseños" / "2026" / "logo.md"
        )
        self.assertEqual(ruta.read_text(encoding="utf-8"), "hola")

    def test_crear_en_un_proyecto_inexistente_responde_404(self):
        response = self.client.post(
            "/api/projects/fantasma/notes", json={"path": "saludo", "content": "x"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("no existe el proyecto", str(response.json()["detail"]))
        self.assertFalse((self.directorio / "projects" / "fantasma").exists())

    def test_crear_duplicado_responde_409_sin_pisar_el_contenido(self):
        self.crear_proyecto("proyecto")
        self.client.post(
            "/api/projects/proyecto/notes", json={"path": "saludo", "content": "original"}
        )
        response = self.client.post(
            "/api/projects/proyecto/notes", json={"path": "saludo", "content": "nuevo"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("ya existe", str(response.json()["detail"]))
        contenido = (
            self.directorio / "projects" / "proyecto" / "saludo.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(contenido, "original")

    def test_crear_ruta_invalida_responde_422_en_espanol(self):
        self.crear_proyecto("proyecto")
        invalidas = (
            "",
            "   ",
            "../../etc/passwd",
            "..",
            "a/../../b",
            "a//b",
            "/absoluta",
            "relativa/",
            ".oculta",
            "punto.txt",
        )
        for ruta in invalidas:
            with self.subTest(ruta=ruta):
                response = self.client.post(
                    "/api/projects/proyecto/notes", json={"path": ruta, "content": "x"}
                )
                self.assertEqual(response.status_code, 422)
                self.assertIn("ruta", response.text.lower())

    def test_crear_ruta_profunda_responde_422(self):
        self.crear_proyecto("proyecto")
        profunda = "/".join(["n"] * (purplemd.MAX_PROFUNDIDAD + 1))
        response = self.client.post(
            "/api/projects/proyecto/notes", json={"path": profunda, "content": "x"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn(str(purplemd.MAX_PROFUNDIDAD), response.text)

    def test_crear_ruta_larga_responde_422(self):
        self.crear_proyecto("proyecto")
        larga = "a" * (purplemd.MAX_RUTA_BYTES + 1)
        response = self.client.post(
            "/api/projects/proyecto/notes", json={"path": larga, "content": "x"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn(str(purplemd.MAX_RUTA_BYTES), response.text)

    def test_crear_sin_path_o_content_responde_422(self):
        self.crear_proyecto("proyecto")
        for payload in ({}, {"path": "saludo"}, {"content": "x"}):
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/projects/proyecto/notes", json=payload
                )
                self.assertEqual(response.status_code, 422)

    def test_crear_contenido_sobre_el_limite_responde_422(self):
        self.crear_proyecto("proyecto")
        response = self.client.post(
            "/api/projects/proyecto/notes",
            json={"path": "grande", "content": "x" * (purplemd.MAX_BYTES + 1)},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn(str(purplemd.MAX_BYTES), response.text)
        self.assertFalse(
            (self.directorio / "projects" / "proyecto" / "grande.md").exists()
        )

    def test_crear_contenido_en_el_limite_exacto_responde_201(self):
        self.crear_proyecto("proyecto")
        response = self.client.post(
            "/api/projects/proyecto/notes",
            json={"path": "limite", "content": "x" * purplemd.MAX_BYTES},
        )
        self.assertEqual(response.status_code, 201)
        ruta = self.directorio / "projects" / "proyecto" / "limite.md"
        self.assertEqual(ruta.stat().st_size, purplemd.MAX_BYTES)

    def test_crear_contenido_con_byte_nul_responde_422(self):
        # Un binario renombrado a .md se delata por el byte NUL: la API se
        # puede pegar directo con curl, así que lo filtra el servidor.
        self.crear_proyecto("proyecto")
        response = self.client.post(
            "/api/projects/proyecto/notes",
            json={"path": "binario", "content": "PK\x00\x03y un texto"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("no es texto plano", response.text)
        self.assertIn("byte NUL", response.text)
        self.assertFalse(
            (self.directorio / "projects" / "proyecto" / "binario.md").exists()
        )

    def test_leer_devuelve_la_nota_completa(self):
        self.crear_nota("proyecto", "diseños/logo", "hola\nchau", epoch=1000)
        response = self.client.get("/api/projects/proyecto/notes/diseños/logo")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "project": "proyecto",
                "path": "diseños/logo",
                "content": "hola\nchau",
                "modified": 1000.0,
            },
        )

    def test_leer_inexistente_responde_404_en_espanol(self):
        self.crear_proyecto("proyecto")
        response = self.client.get("/api/projects/proyecto/notes/fantasma")
        self.assertEqual(response.status_code, 404)
        self.assertIn("no existe", str(response.json()["detail"]))

    def test_leer_en_un_proyecto_inexistente_responde_404(self):
        response = self.client.get("/api/projects/fantasma/notes/saludo")
        self.assertEqual(response.status_code, 404)

    def test_leer_ruta_invalida_responde_422(self):
        # El path viene del URL, no de Pydantic: el handler del núcleo es el
        # que garantiza el 422. Va codificado para que no lo normalice el URL.
        self.crear_proyecto("proyecto")
        response = self.client.get(
            "/api/projects/proyecto/notes/..%2F..%2Fetc%2Fpasswd"
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("ruta", response.text.lower())

    def test_guardar_reemplaza_el_contenido(self):
        self.crear_nota("proyecto", "saludo", "original", epoch=1000)
        response = self.client.put(
            "/api/projects/proyecto/notes/saludo", json={"content": "actualizado"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], "actualizado")
        contenido = (
            self.directorio / "projects" / "proyecto" / "saludo.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(contenido, "actualizado")

    def test_guardar_inexistente_responde_404(self):
        self.crear_proyecto("proyecto")
        response = self.client.put(
            "/api/projects/proyecto/notes/fantasma", json={"content": "x"}
        )
        self.assertEqual(response.status_code, 404)

    def test_guardar_en_un_proyecto_inexistente_responde_404(self):
        response = self.client.put(
            "/api/projects/fantasma/notes/saludo", json={"content": "x"}
        )
        self.assertEqual(response.status_code, 404)

    def test_guardar_sobre_el_limite_responde_422(self):
        self.crear_nota("proyecto", "saludo", "original")
        response = self.client.put(
            "/api/projects/proyecto/notes/saludo",
            json={"content": "x" * (purplemd.MAX_BYTES + 1)},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn(str(purplemd.MAX_BYTES), response.text)
        contenido = (
            self.directorio / "projects" / "proyecto" / "saludo.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(contenido, "original")

    def test_guardar_contenido_con_byte_nul_responde_422(self):
        self.crear_nota("proyecto", "saludo", "original")
        response = self.client.put(
            "/api/projects/proyecto/notes/saludo",
            json={"content": "# nota\x00con binario adentro"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("no es texto plano", response.text)
        self.assertIn("byte NUL", response.text)
        contenido = (
            self.directorio / "projects" / "proyecto" / "saludo.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(contenido, "original")

    def test_exportar_pdf_devuelve_pdf_valido(self):
        self.crear_nota("proyecto", "saludo", "# Hola\n")
        response = self.client.get("/api/projects/proyecto/notes/saludo/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_exportar_pdf_con_resaltado_de_sintaxis(self):
        self.crear_nota("proyecto", "codigo", "```python\nprint(1)\n```")
        response = self.client.get("/api/projects/proyecto/notes/codigo/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_exportar_pdf_de_nota_inexistente_responde_404(self):
        response = self.client.get("/api/projects/proyecto/notes/no-existe/pdf")
        self.assertEqual(response.status_code, 404)

    def test_pdf_marca_de_agua_lleva_el_corazon_escaped(self):
        """El pie imprime «♥», no «¶5»: `\2665` es escape CSS y la
        barra va doble dentro del literal de Python (con una sola,
        Python la lee como octal y arruina el carácter)."""
        nota = purplemd.Nota(project="p", path="x.md", content="# hola", modified=0.0)
        html = _html_para_pdf(nota)
        self.assertIn('content: "Generado con PurpleMD \\2665"', html)
        self.assertNotIn("¶", html)

    def test_pdf_las_tareas_quedan_en_su_renglon(self):
        """WeasyPrint, sin `display: inline-block`, baja el casillero a un
        renglón propio y el texto de la tarea queda colgado debajo."""
        nota = purplemd.Nota(project="p", path="x.md", content="# hola", modified=0.0)
        html = _html_para_pdf(nota)
        regla = html.split('input[type="checkbox"] {', 1)[1].split("}", 1)[0]
        self.assertIn("display: inline-block", regla)

    def test_pdf_el_bloque_de_codigo_usa_mono_y_la_paleta_por_defecto(self):
        """El bloque ``` del PDF va monoespaciado y con sus saltos de línea:
        el resaltado cambia el `<pre><code>` por un `<div class="highlight">`
        y ese div, sin reglas propias, caía en la fuente del documento y
        juntaba todo el código en un renglón. Los colores salen de la paleta
        por defecto de Pygments, no de literales en `api.py`."""
        nota = purplemd.Nota(
            project="p", path="x.md", content="```python\nprint(1)\n```", modified=0.0
        )
        html = _html_para_pdf(nota)
        regla = html.split("pre,\n    .highlight {", 1)[1].split("}", 1)[0]
        self.assertIn("white-space: pre-wrap", regla)
        self.assertIn('"DejaVu Sans Mono"', regla)
        self.assertIn(renderer.css_resaltado(), html)
        self.assertNotIn("#ff79c6", html)

    def test_pdf_las_cadenas_de_fuentes_no_incluyen_la_emoji(self):
        """Los dígitos del PDF no pueden salir en tipografía de emoji.

        En Debian, `45-generic.conf` y `60-generic.conf` promueven la familia
        `Noto Color Emoji` por encima de DejaVu Sans en fontconfig en cuanto
        aparece en la cadena de `font-family`; como esa fuente tiene glifos
        0-9, todos los números del documento y el contador de página salían
        con ella. Los emoji siguen resolviéndose igual, por fallback de
        fontconfig, cuando la fuente pedida no tiene el glifo."""
        nota = purplemd.Nota(
            project="p", path="x.md", content="# Números\n123456789", modified=0.0
        )
        html = _html_para_pdf(nota)
        # Solo las declaraciones: el comentario del CSS explica por qué la
        # familia no puede volver a entrar en la cadena.
        declaraciones = [
            linea for linea in html.splitlines() if "font-family:" in linea
        ]
        self.assertTrue(declaraciones)
        for declaracion in declaraciones:
            self.assertNotIn("Noto Color Emoji", declaracion)
        cadena = 'font-family: "DejaVu Sans", "Liberation Sans", sans-serif;'
        self.assertIn(cadena, html)

    def test_pdf_no_toca_la_red(self):
        """SSRF: el PDF nunca sale a buscar lo que dice la nota.

        Un servidor local en un hilo cuenta las peticiones que llegan; si el
        endpoint bajara la imagen remota, el conteo no estaría vacío. El
        recurso se omite y el PDF se genera igual (200)."""
        peticiones: list[str] = []

        class Contador(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (nombre que exige http.server)
                peticiones.append(self.path)
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:  # sin ruido en stderr
                pass

        servidor = http.server.HTTPServer(("127.0.0.1", 0), Contador)
        self.addCleanup(servidor.server_close)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        self.addCleanup(servidor.shutdown)

        puerto = servidor.server_address[1]
        self.crear_nota(
            "proyecto", "remota", f"# hola\n\n![img](http://127.0.0.1:{puerto}/a.png)\n"
        )
        response = self.client.get("/api/projects/proyecto/notes/remota/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(peticiones, [])

    def test_el_fetcher_del_pdf_solo_acepta_data(self):
        """El fetcher del PDF bloquea red (`http`, `https`), disco (`file`)
        y rutas relativas, y deja pasar solo imágenes inline `data:`."""
        recurso = FETCHER_PDF("data:image/png;base64,aGVsbG8=")
        self.assertEqual(recurso.read(), b"hello")
        for url in (
            "http://127.0.0.1:9/a.png",
            "https://ejemplo.com/a.png",
            "file:///etc/passwd",
            "adjunto.png",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                FETCHER_PDF(url)


    def test_los_endpoints_viejos_de_notas_desaparecieron(self):
        for metodo in ("get", "post"):
            with self.subTest(metodo=metodo):
                respuesta = getattr(self.client, metodo)("/api/notes")
                self.assertEqual(respuesta.status_code, 404)
        respuesta = self.client.put("/api/notes/saludo", json={"content": "x"})
        self.assertEqual(respuesta.status_code, 404)


class RenderEndpointTests(ApiTestCase):
    def test_renderiza_markdown(self):
        response = self.client.post("/api/render", json={"markdown": "# hola"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"html": "<h1>hola</h1>\n"})

    def test_markdown_vacio_da_html_vacio(self):
        response = self.client.post("/api/render", json={"markdown": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"html": ""})

    def test_escapa_el_html_crudo(self):
        response = self.client.post(
            "/api/render", json={"markdown": "<script>alert(1)</script>"}
        )
        self.assertEqual(response.status_code, 200)
        html = response.json()["html"]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_markdown_sobre_200_kb_responde_422(self):
        response = self.client.post(
            "/api/render", json={"markdown": "x" * (MAX_RENDER_BYTES + 1)}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn(str(MAX_RENDER_BYTES), response.text)


class HealthEndpointTests(ApiTestCase):
    def test_directorio_operativo_da_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"estado": "ok"})

    def test_directorio_increable_da_degradado(self):
        # El directorio de datos apunta adentro de un archivo: mkdir falla
        # y el healthcheck debe reportar "degradado" sin romperse.
        archivo = self.directorio / "archivo"
        archivo.write_text("x", encoding="utf-8")
        with patch.dict(os.environ, {"PURPLEMD_DIR": str(archivo / "hijos")}):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"estado": "degradado"})

    def test_directorio_no_escribible_da_degradado(self):
        with patch("api.os.access", return_value=False):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"estado": "degradado"})


class ErrorInternoTests(ApiTestCase):
    def test_responde_500_sin_filtrar_detalles(self):
        with patch("purplemd.listar_proyectos", side_effect=RuntimeError("secreto interno")):
            cliente = TestClient(app, raise_server_exceptions=False)
            response = cliente.get("/api/projects")
        self.assertEqual(response.status_code, 500)
        detalle = str(response.json()["detail"])
        self.assertNotIn("secreto interno", detalle)
        self.assertNotIn("Traceback", detalle)

    def test_el_500_se_registra_con_su_traceback(self):
        """La respuesta sigue siendo genérica, pero el fallo sí queda en el
        log: un 500 sin rastro es indiagnóstico en producción."""
        with (
            patch("purplemd.listar_proyectos", side_effect=RuntimeError("secreto interno")),
            self.assertLogs("purplemd", level="ERROR") as captura,
        ):
            cliente = TestClient(app, raise_server_exceptions=False)
            response = cliente.get("/api/projects")
        self.assertEqual(response.status_code, 500)
        texto = logging.Formatter().format(captura.records[0])
        self.assertIn("GET /api/projects", texto)
        self.assertIn("Traceback (most recent call last)", texto)
        self.assertIn("RuntimeError: secreto interno", texto)


class ProyectoEdicionEndpointTests(ApiTestCase):
    def test_patch_renombrar_responde_200_y_mueve_el_directorio(self):
        self.crear_nota("viejo", "diseños/logo", "hola")
        response = self.client.patch("/api/projects/viejo", json={"name": "nuevo"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"name", "modified"})
        self.assertEqual(body["name"], "nuevo")
        self.assertIsInstance(body["modified"], float)
        self.assertFalse((self.directorio / "projects" / "viejo").exists())
        ruta = self.directorio / "projects" / "nuevo" / "diseños" / "logo.md"
        self.assertEqual(ruta.read_text(encoding="utf-8"), "hola")

    def test_patch_al_mismo_nombre_responde_200_idempotente(self):
        # Reenviar el formulario no debe fallar ni tocar el disco.
        self.crear_proyecto("viejo")
        for nombre in ("viejo", "viejo.md"):
            with self.subTest(nombre=nombre):
                response = self.client.patch("/api/projects/viejo", json={"name": nombre})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["name"], "viejo")
        self.assertTrue((self.directorio / "projects" / "viejo").is_dir())

    def test_patch_a_un_nombre_duplicado_responde_409_sin_pisar_nada(self):
        self.crear_nota("viejo", "saludo", "hola")
        self.crear_nota("ocupado", "saludo", "del otro")
        response = self.client.patch("/api/projects/viejo", json={"name": "ocupado"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("ya existe", str(response.json()["detail"]))
        base = self.directorio / "projects"
        self.assertEqual((base / "viejo" / "saludo.md").read_text(encoding="utf-8"), "hola")
        self.assertEqual(
            (base / "ocupado" / "saludo.md").read_text(encoding="utf-8"), "del otro"
        )

    def test_patch_de_un_proyecto_inexistente_responde_404(self):
        response = self.client.patch("/api/projects/fantasma", json={"name": "nuevo"})
        self.assertEqual(response.status_code, 404)
        self.assertIn("no existe", str(response.json()["detail"]))

    def test_patch_con_un_nombre_invalido_responde_422_en_espanol(self):
        self.crear_proyecto("viejo")
        for nombre in ("", "punto.txt", "a/b", "..", ".oculta"):
            with self.subTest(nombre=nombre):
                response = self.client.patch("/api/projects/viejo", json={"name": nombre})
                self.assertEqual(response.status_code, 422)
                self.assertIn("nombre", response.text.lower())
        self.assertTrue((self.directorio / "projects" / "viejo").is_dir())

    def test_patch_sin_payload_responde_422(self):
        self.crear_proyecto("viejo")
        response = self.client.patch("/api/projects/viejo")
        self.assertEqual(response.status_code, 422)

    def test_patch_con_un_proyecto_invalido_en_la_url_responde_422(self):
        response = self.client.patch("/api/projects/punto.txt", json={"name": "nuevo"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("nombre", response.text.lower())

    def test_delete_responde_204_sin_cuerpo_y_borra_recursivamente(self):
        self.crear_nota("proyecto", "diseños/2026/logo", "hola")
        response = self.client.delete("/api/projects/proyecto")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.text, "")
        self.assertFalse((self.directorio / "projects" / "proyecto").exists())
        # Nada de lo que había adentro queda en disco.
        self.assertEqual(list((self.directorio / "projects").iterdir()), [])

    def test_delete_de_un_proyecto_inexistente_responde_404(self):
        response = self.client.delete("/api/projects/fantasma")
        self.assertEqual(response.status_code, 404)
        self.assertIn("no existe", str(response.json()["detail"]))

    def test_delete_con_un_nombre_invalido_responde_422(self):
        response = self.client.delete("/api/projects/punto.txt")
        self.assertEqual(response.status_code, 422)

    def test_delete_no_toca_a_los_demas_proyectos(self):
        self.crear_nota("proyecto", "saludo", "hola")
        self.crear_nota("otro", "saludo", "intacto")
        self.client.delete("/api/projects/proyecto")
        intacto = self.directorio / "projects" / "otro" / "saludo.md"
        self.assertEqual(intacto.read_text(encoding="utf-8"), "intacto")


class NotaEdicionEndpointTests(ApiTestCase):
    def raiz(self) -> Path:
        return self.directorio / "projects" / "proyecto"

    def test_patch_renombrar_responde_200_con_el_detalle(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        response = self.client.patch(
            "/api/projects/proyecto/notes/diseños/logo", json={"path": "diseños/marca"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"project", "path", "content", "modified"})
        self.assertEqual(body["project"], "proyecto")
        self.assertEqual(body["path"], "diseños/marca")
        self.assertEqual(body["content"], "hola")
        self.assertIsInstance(body["modified"], float)
        self.assertFalse((self.raiz() / "diseños" / "logo.md").exists())
        marca = self.raiz() / "diseños" / "marca.md"
        self.assertEqual(marca.read_text(encoding="utf-8"), "hola")

    def test_patch_mover_a_otra_carpeta_crea_la_destino(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        response = self.client.patch(
            "/api/projects/proyecto/notes/diseños/logo", json={"path": "imagenes/2026/logo"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "imagenes/2026/logo")
        destino = self.raiz() / "imagenes" / "2026" / "logo.md"
        self.assertEqual(destino.read_text(encoding="utf-8"), "hola")
        self.assertFalse((self.raiz() / "diseños" / "logo.md").exists())

    def test_patch_a_la_misma_ruta_responde_200_idempotente(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        response = self.client.patch(
            "/api/projects/proyecto/notes/diseños/logo", json={"path": "diseños/logo"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["path"], "diseños/logo")
        self.assertEqual(body["content"], "hola")
        self.assertTrue((self.raiz() / "diseños" / "logo.md").is_file())

    def test_patch_con_destino_ocupado_responde_409_sin_pisar(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        self.crear_nota("proyecto", "imagenes/logo", "otro")
        response = self.client.patch(
            "/api/projects/proyecto/notes/diseños/logo", json={"path": "imagenes/logo"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("destino", str(response.json()["detail"]))
        self.assertEqual(
            (self.raiz() / "diseños" / "logo.md").read_text(encoding="utf-8"), "hola"
        )
        self.assertEqual(
            (self.raiz() / "imagenes" / "logo.md").read_text(encoding="utf-8"), "otro"
        )

    def test_patch_de_una_nota_inexistente_responde_404(self):
        self.crear_proyecto("proyecto")
        response = self.client.patch(
            "/api/projects/proyecto/notes/fantasma", json={"path": "otra"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("no existe", str(response.json()["detail"]))

    def test_patch_en_un_proyecto_inexistente_responde_404(self):
        response = self.client.patch(
            "/api/projects/fantasma/notes/saludo", json={"path": "otra"}
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_a_una_ruta_que_escapa_del_proyecto_responde_422(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        for destino in ("../../etc/passwd", "/etc/passwd", "..", "a//b", ""):
            with self.subTest(destino=destino):
                response = self.client.patch(
                    "/api/projects/proyecto/notes/diseños/logo", json={"path": destino}
                )
                self.assertEqual(response.status_code, 422)
                self.assertIn("ruta", response.text.lower())
        self.assertEqual(
            (self.raiz() / "diseños" / "logo.md").read_text(encoding="utf-8"), "hola"
        )

    def test_patch_con_una_ruta_invalida_en_la_url_responde_422(self):
        # Va codificado para que la normalización de dot segments del URL no
        # se coma el `..` antes de que llegue al handler.
        response = self.client.patch(
            "/api/projects/proyecto/notes/..%2F..%2Fetc%2Fpasswd", json={"path": "otra"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("ruta", response.text.lower())

    def test_delete_responde_204_y_borra_el_archivo(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        response = self.client.delete("/api/projects/proyecto/notes/diseños/logo")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.text, "")
        self.assertFalse((self.raiz() / "diseños" / "logo.md").exists())
        # Decisión del núcleo: la carpeta vacía no se borra sola.
        self.assertTrue((self.raiz() / "diseños").is_dir())

    def test_delete_de_una_nota_inexistente_responde_404(self):
        self.crear_proyecto("proyecto")
        response = self.client.delete("/api/projects/proyecto/notes/fantasma")
        self.assertEqual(response.status_code, 404)

    def test_delete_en_un_proyecto_inexistente_responde_404(self):
        response = self.client.delete("/api/projects/fantasma/notes/saludo")
        self.assertEqual(response.status_code, 404)

    def test_delete_con_una_ruta_invalida_responde_422(self):
        response = self.client.delete(
            "/api/projects/proyecto/notes/..%2F..%2Fetc%2Fpasswd"
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("ruta", response.text.lower())


class DirectorioEdicionEndpointTests(ApiTestCase):
    def raiz(self) -> Path:
        return self.directorio / "projects" / "proyecto"

    def test_patch_renombrar_responde_200_con_el_detalle(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        response = self.client.patch(
            "/api/projects/proyecto/dirs/diseños", json={"path": "croquis"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"project", "path", "modified"})
        self.assertEqual(body["project"], "proyecto")
        self.assertEqual(body["path"], "croquis")
        self.assertIsInstance(body["modified"], float)
        self.assertFalse((self.raiz() / "diseños").exists())
        self.assertEqual(
            (self.raiz() / "croquis" / "logo.md").read_text(encoding="utf-8"), "hola"
        )

    def test_patch_mover_a_otra_carpeta_crea_la_destino(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        response = self.client.patch(
            "/api/projects/proyecto/dirs/diseños", json={"path": "archivo/2026/diseños"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "archivo/2026/diseños")
        destino = self.raiz() / "archivo" / "2026" / "diseños" / "logo.md"
        self.assertEqual(destino.read_text(encoding="utf-8"), "hola")
        self.assertFalse((self.raiz() / "diseños").exists())

    def test_patch_a_la_misma_ruta_responde_200_idempotente(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        response = self.client.patch(
            "/api/projects/proyecto/dirs/diseños", json={"path": "diseños"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "diseños")
        self.assertTrue((self.raiz() / "diseños" / "logo.md").is_file())

    def test_patch_dentro_de_si_mismo_responde_422(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        response = self.client.patch(
            "/api/projects/proyecto/dirs/diseños", json={"path": "diseños/interno"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("mover", str(response.json()["detail"]).lower())
        self.assertFalse((self.raiz() / "diseños" / "interno").exists())

    def test_patch_hacia_un_ancestro_responde_422(self):
        self.crear_nota("proyecto", "diseños/2026/logo", "hola")
        response = self.client.patch(
            "/api/projects/proyecto/dirs/diseños/2026", json={"path": "diseños"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertTrue((self.raiz() / "diseños" / "2026").is_dir())

    def test_patch_con_destino_ocupado_responde_409_sin_pisar(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        self.crear_nota("proyecto", "plantillas/base", "base")
        response = self.client.patch(
            "/api/projects/proyecto/dirs/diseños", json={"path": "plantillas"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("destino", str(response.json()["detail"]))
        self.assertEqual(
            (self.raiz() / "diseños" / "logo.md").read_text(encoding="utf-8"), "hola"
        )
        self.assertEqual(
            (self.raiz() / "plantillas" / "base.md").read_text(encoding="utf-8"), "base"
        )

    def test_patch_de_un_directorio_inexistente_responde_404(self):
        self.crear_proyecto("proyecto")
        response = self.client.patch(
            "/api/projects/proyecto/dirs/fantasma", json={"path": "otra"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("no existe", str(response.json()["detail"]))

    def test_patch_en_un_proyecto_inexistente_responde_404(self):
        response = self.client.patch(
            "/api/projects/fantasma/dirs/carpeta", json={"path": "otra"}
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_a_una_ruta_que_escapa_del_proyecto_responde_422(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        for destino in ("../../etc", "/etc", "..", "a//b", ""):
            with self.subTest(destino=destino):
                response = self.client.patch(
                    "/api/projects/proyecto/dirs/diseños", json={"path": destino}
                )
                self.assertEqual(response.status_code, 422)
                self.assertIn("ruta", response.text.lower())
        self.assertTrue((self.raiz() / "diseños" / "logo.md").is_file())

    def test_delete_de_un_directorio_vacio_responde_204(self):
        self.crear_proyecto("proyecto")
        (self.raiz() / "vacia").mkdir()
        response = self.client.delete("/api/projects/proyecto/dirs/vacia")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.text, "")
        self.assertFalse((self.raiz() / "vacia").exists())

    def test_delete_de_un_directorio_no_vacio_responde_409(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        response = self.client.delete("/api/projects/proyecto/dirs/diseños")
        self.assertEqual(response.status_code, 409)
        self.assertIn("vacío", str(response.json()["detail"]))
        # Sin recursive no se borra nada.
        self.assertEqual(
            (self.raiz() / "diseños" / "logo.md").read_text(encoding="utf-8"), "hola"
        )

    def test_delete_con_recursive_false_explicito_tambien_responde_409(self):
        self.crear_nota("proyecto", "diseños/logo", "hola")
        response = self.client.delete(
            "/api/projects/proyecto/dirs/diseños", params={"recursive": "false"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertTrue((self.raiz() / "diseños" / "logo.md").is_file())

    def test_delete_con_recursive_true_responde_204_y_borra_todo(self):
        self.crear_nota("proyecto", "diseños/2026/logo", "hola")
        response = self.client.delete(
            "/api/projects/proyecto/dirs/diseños", params={"recursive": "true"}
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.text, "")
        self.assertFalse((self.raiz() / "diseños").exists())

    def test_delete_de_un_directorio_inexistente_responde_404(self):
        self.crear_proyecto("proyecto")
        response = self.client.delete("/api/projects/proyecto/dirs/fantasma")
        self.assertEqual(response.status_code, 404)

    def test_delete_en_un_proyecto_inexistente_responde_404(self):
        response = self.client.delete("/api/projects/fantasma/dirs/carpeta")
        self.assertEqual(response.status_code, 404)

    def test_delete_con_una_ruta_invalida_responde_422(self):
        response = self.client.delete(
            "/api/projects/proyecto/dirs/..%2F..%2Fetc"
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("ruta", response.text.lower())


class EdicionEnTodosLosEndpointsTests(ApiTestCase):
    """Los seis endpoints de edición responden igual ante casos límite."""

    def _endpoints(self, proyecto: str) -> list[tuple[str, str, dict | None]]:
        return [
            ("patch", f"/api/projects/{proyecto}", {"name": "nuevo"}),
            ("delete", f"/api/projects/{proyecto}", None),
            ("patch", f"/api/projects/{proyecto}/notes/saludo", {"path": "otra"}),
            ("delete", f"/api/projects/{proyecto}/notes/saludo", None),
            ("patch", f"/api/projects/{proyecto}/dirs/carpeta", {"path": "otra"}),
            ("delete", f"/api/projects/{proyecto}/dirs/carpeta", None),
        ]

    def _responder(self, metodo: str, url: str, payload: dict | None):
        if payload is None:
            return getattr(self.client, metodo)(url)
        return getattr(self.client, metodo)(url, json=payload)

    def test_responden_404_cuando_no_existe_el_proyecto(self):
        for metodo, url, payload in self._endpoints("fantasma"):
            with self.subTest(endpoint=f"{metodo.upper()} {url}"):
                response = self._responder(metodo, url, payload)
                self.assertEqual(response.status_code, 404)
                self.assertIn("no existe", str(response.json()["detail"]))

    def test_responden_422_con_un_proyecto_invalido_en_la_url(self):
        for metodo, url, payload in self._endpoints("punto.txt"):
            with self.subTest(endpoint=f"{metodo.upper()} {url}"):
                response = self._responder(metodo, url, payload)
                self.assertEqual(response.status_code, 422)
                self.assertIn("nombre", response.text.lower())

    def test_el_openapi_sigue_generandose(self):
        # Cubre los response_class=Response de los DELETE nuevos.
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        rutas = response.json()["paths"]
        self.assertIn("/api/projects/{project}", rutas)
        self.assertIn("/api/projects/{project}/dirs/{path}", rutas)


if __name__ == "__main__":
    unittest.main()
