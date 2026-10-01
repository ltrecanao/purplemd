import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import purplemd


class ValidarNombreTests(unittest.TestCase):
    """El nombre de proyecto (y cada segmento de ruta) sigue las reglas de siempre."""

    def test_devuelve_el_nombre_sin_extension(self):
        self.assertEqual(purplemd.validar_nombre("proyecto"), "proyecto")
        self.assertEqual(purplemd.validar_nombre("proyecto.md"), "proyecto")
        self.assertEqual(purplemd.validar_nombre("PROYECTO.MD"), "PROYECTO")
        self.assertEqual(purplemd.validar_nombre("Lista de compras 2026"), "Lista de compras 2026")
        self.assertEqual(purplemd.validar_nombre("índice_nota-01"), "índice_nota-01")

    def test_rechaza_path_traversal(self):
        invalidos = (
            "..",
            "../etc/passwd",
            "sub/../../etc/passwd",
            "a/b",
            "a\\b",
            "..\\windows",
            ".",
            ".oculta",
        )
        for nombre in invalidos:
            with self.subTest(nombre=nombre), self.assertRaises(purplemd.NombreInvalido):
                purplemd.validar_nombre(nombre)

    def test_rechaza_vacio_y_extension_sola(self):
        for nombre in ("", ".md", "   "):
            with self.subTest(nombre=nombre), self.assertRaises(purplemd.NombreInvalido):
                purplemd.validar_nombre(nombre)

    def test_rechaza_caracteres_invalidos(self):
        invalidos = ("punto.txt", "nota*md", "coma,cosa", "dos..puntos", "emoji🎨", "raro?")
        for nombre in invalidos:
            with self.subTest(nombre=nombre), self.assertRaises(purplemd.NombreInvalido):
                purplemd.validar_nombre(nombre)

    def test_el_mensaje_de_error_esta_en_espanol(self):
        with self.assertRaises(purplemd.NombreInvalido) as contexto:
            purplemd.validar_nombre("../etc/passwd")
        self.assertIn("nombre", str(contexto.exception))


class ValidarRutaTests(unittest.TestCase):
    def test_devuelve_la_ruta_sin_extension(self):
        self.assertEqual(purplemd.validar_ruta("saludo"), "saludo")
        self.assertEqual(purplemd.validar_ruta("diseños/logo.md"), "diseños/logo")
        self.assertEqual(purplemd.validar_ruta("a/b/c"), "a/b/c")

    def test_acepta_hasta_la_profundidad_maxima(self):
        ruta = "/".join("abcdefghij")  # 10 segmentos
        self.assertEqual(purplemd.validar_ruta(ruta), ruta)
        self.assertEqual(purplemd.MAX_PROFUNDIDAD, 10)

    def test_rechaza_rutas_vacias_o_con_barras_de_extremos(self):
        for ruta in ("", "   ", ".md", "/saludo", "saludo/", "/"):
            with self.subTest(ruta=ruta), self.assertRaises(purplemd.NombreInvalido):
                purplemd.validar_ruta(ruta)

    def test_rechaza_segmentos_vacios(self):
        for ruta in ("a//b", "a///b", " /b"):
            with self.subTest(ruta=ruta), self.assertRaises(purplemd.NombreInvalido):
                purplemd.validar_ruta(ruta)

    def test_rechaza_path_traversal(self):
        rutas = (
            "..",
            ".",
            "../../etc/passwd",
            "a/../../b",
            "a/../b",
            "diseños/../../../etc/passwd",
            "a\\b",
            "..\\windows",
        )
        for ruta in rutas:
            with self.subTest(ruta=ruta), self.assertRaises(purplemd.NombreInvalido):
                purplemd.validar_ruta(ruta)

    def test_rechaza_mas_de_diez_niveles(self):
        profunda = "/".join(["n"] * (purplemd.MAX_PROFUNDIDAD + 1))
        with self.assertRaises(purplemd.NombreInvalido):
            purplemd.validar_ruta(profunda)

    def test_rechaza_rutas_sobre_el_limite_de_bytes(self):
        with self.assertRaises(purplemd.NombreInvalido):
            purplemd.validar_ruta("a" * (purplemd.MAX_RUTA_BYTES + 1))
        # El límite cuenta bytes UTF-8 y no caracteres: 101 "á" ya pasan de 200.
        with self.assertRaises(purplemd.NombreInvalido):
            purplemd.validar_ruta("á" * 101)

    def test_una_ruta_corta_no_llega_al_limite(self):
        ruta = "diseños/" * (purplemd.MAX_PROFUNDIDAD - 1) + "logo"
        self.assertLessEqual(len(ruta.encode("utf-8")), purplemd.MAX_RUTA_BYTES)
        self.assertEqual(purplemd.validar_ruta(ruta), ruta)

    def test_el_mensaje_de_error_esta_en_espanol(self):
        with self.assertRaises(purplemd.NombreInvalido) as contexto:
            purplemd.validar_ruta("a//b")
        self.assertIn("ruta", str(contexto.exception))


class ProyectoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)

    def test_crear_hace_el_directorio_en_disco(self):
        proyecto = purplemd.crear_proyecto("mi proyecto", self.directorio)
        ruta = self.directorio / "projects" / "mi proyecto"
        self.assertTrue(ruta.is_dir())
        self.assertEqual(proyecto.name, "mi proyecto")
        self.assertIsInstance(proyecto.modified, float)
        self.assertGreater(proyecto.modified, 0)

    def test_crear_acepta_el_nombre_con_extension(self):
        proyecto = purplemd.crear_proyecto("saludo.md", self.directorio)
        self.assertEqual(proyecto.name, "saludo")
        self.assertEqual([p.name for p in (self.directorio / "projects").iterdir()], ["saludo"])

    def test_crear_duplicado_falla_sin_borrar_el_directorio(self):
        purplemd.crear_proyecto("saludo", self.directorio)
        with self.assertRaises(purplemd.ProyectoYaExiste):
            purplemd.crear_proyecto("saludo", self.directorio)
        self.assertTrue((self.directorio / "projects" / "saludo").is_dir())

    def test_crear_nombre_invalido_lanza_nombre_invalido(self):
        invalidos = ("", "   ", "../etc/passwd", "a/b", ".oculta", "punto.txt", "con*estrella")
        for nombre in invalidos:
            with self.subTest(nombre=nombre), self.assertRaises(purplemd.NombreInvalido):
                purplemd.crear_proyecto(nombre, self.directorio)
        self.assertFalse((self.directorio / "projects").exists())

    def test_operar_un_proyecto_inexistente_lanza_proyecto_no_existe(self):
        casos = (
            lambda: purplemd.arbol_proyecto("fantasma", self.directorio),
            lambda: purplemd.leer_nota("fantasma", "nota", self.directorio),
            lambda: purplemd.crear_nota("fantasma", "nota", "x", self.directorio),
            lambda: purplemd.guardar_nota("fantasma", "nota", "x", self.directorio),
        )
        for operacion in casos:
            with self.subTest(operacion=operacion), self.assertRaises(
                purplemd.ProyectoNoExiste
            ):
                operacion()

    def test_crear_una_nota_no_inventa_el_proyecto(self):
        with self.assertRaises(purplemd.ProyectoNoExiste):
            purplemd.crear_nota("fantasma", "anidada/nota", "x", self.directorio)
        self.assertFalse((self.directorio / "projects" / "fantasma").exists())

    def test_el_directorio_de_datos_inexistente_se_crea(self):
        destino = self.directorio / "anidado" / "datos"
        purplemd.crear_proyecto("saludo", destino)
        self.assertTrue((destino / "projects" / "saludo").is_dir())


class ListadoProyectosTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)

    def test_directorio_vacio_da_lista_vacia(self):
        # Ni siquiera existe projects/ todavía.
        self.assertEqual(purplemd.listar_proyectos(self.directorio), [])

    def _fijar_modificacion(self, nombre: str, epoch: float) -> None:
        ruta = self.directorio / "projects" / nombre
        os.utime(ruta, (epoch, epoch))

    def test_lista_de_mas_reciente_a_mas_antiguo(self):
        for nombre in ("vieja", "media", "nueva"):
            purplemd.crear_proyecto(nombre, self.directorio)
        self._fijar_modificacion("vieja", 1000)
        self._fijar_modificacion("media", 2000)
        self._fijar_modificacion("nueva", 3000)
        proyectos = purplemd.listar_proyectos(self.directorio)
        self.assertEqual([proyecto.name for proyecto in proyectos], ["nueva", "media", "vieja"])
        for proyecto in proyectos:
            self.assertIsInstance(proyecto.modified, float)

    def test_omite_directorios_con_nombre_invalido(self):
        # Un directorio que el editor no creó no debe romper el listado entero.
        (self.directorio / "projects" / ".oculta").mkdir(parents=True)
        purplemd.crear_proyecto("visible", self.directorio)
        self.assertEqual([p.name for p in purplemd.listar_proyectos(self.directorio)], ["visible"])

    def test_omite_archivos_sueltos_en_projects(self):
        base = self.directorio / "projects"
        base.mkdir(parents=True)
        (base / "avulso.md").write_text("no es un proyecto", encoding="utf-8")
        self.assertEqual(purplemd.listar_proyectos(self.directorio), [])


class ArbolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)
        purplemd.crear_proyecto("arbol", self.directorio)
        self.raiz = self.directorio / "projects" / "arbol"

    def test_proyecto_vacio_da_un_arbol_vacio(self):
        resultado = purplemd.arbol_proyecto("arbol", self.directorio)
        self.assertEqual(resultado.project, "arbol")
        self.assertEqual(resultado.entries, [])

    def test_es_recursivo_y_ordena_carpetas_despues_notas(self):
        self._crear_estructura()
        resultado = purplemd.arbol_proyecto("arbol", self.directorio)
        self.assertEqual(
            [(entrada.type, entrada.path) for entrada in resultado.entries],
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
        for entrada in resultado.entries:
            self.assertIsInstance(entrada.modified, float)

    def test_las_rutas_de_las_notas_no_llevan_extension(self):
        self._crear_estructura()
        resultado = purplemd.arbol_proyecto("arbol", self.directorio)
        rutas = [entrada.path for entrada in resultado.entries]
        for ruta in rutas:
            self.assertFalse(ruta.endswith(".md"), ruta)

    def test_omite_archivos_no_md_y_nombres_invalidos(self):
        (self.raiz / "notas.txt").write_text("no es md", encoding="utf-8")
        (self.raiz / "borrador.md.tmp").write_text("temporal", encoding="utf-8")
        (self.raiz / ".oculta.md").write_text("oculta", encoding="utf-8")
        (self.raiz / "carpeta rara 🎨").mkdir()
        purplemd.crear_nota("arbol", "saludo", "hola", self.directorio)
        resultado = purplemd.arbol_proyecto("arbol", self.directorio)
        self.assertEqual([(e.type, e.path) for e in resultado.entries], [("note", "saludo")])

    def test_un_proyecto_inexistente_lanza_proyecto_no_existe(self):
        with self.assertRaises(purplemd.ProyectoNoExiste):
            purplemd.arbol_proyecto("fantasma", self.directorio)

    def test_un_nombre_invalido_lanza_nombre_invalido(self):
        with self.assertRaises(purplemd.NombreInvalido):
            purplemd.arbol_proyecto("../etc", self.directorio)

    def _crear_estructura(self) -> None:
        for nota in ("raiz", "zeta", "alpha/beta", "alpha/sub/gamma", "omega/delta"):
            ruta = self.raiz / f"{nota}.md"
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(nota, encoding="utf-8")


class PersistenciaNotasTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)
        purplemd.crear_proyecto("proyecto", self.directorio)
        self.raiz = self.directorio / "projects" / "proyecto"

    def test_crear_escribe_el_archivo_en_disco(self):
        nota = purplemd.crear_nota("proyecto", "saludo", "hola", self.directorio)
        ruta = self.raiz / "saludo.md"
        self.assertTrue(ruta.is_file())
        self.assertEqual(ruta.read_text(encoding="utf-8"), "hola")
        self.assertEqual(nota.project, "proyecto")
        self.assertEqual(nota.path, "saludo")
        self.assertEqual(nota.content, "hola")
        self.assertIsInstance(nota.modified, float)
        self.assertGreater(nota.modified, 0)

    def test_crear_acepta_la_ruta_con_extension(self):
        nota = purplemd.crear_nota("proyecto", "saludo.md", "hola", self.directorio)
        self.assertEqual(nota.path, "saludo")
        self.assertEqual([p.name for p in self.raiz.iterdir()], ["saludo.md"])

    def test_crear_anidada_crea_las_carpetas_que_falten(self):
        nota = purplemd.crear_nota("proyecto", "diseños/logo", "hola", self.directorio)
        ruta = self.raiz / "diseños" / "logo.md"
        self.assertTrue(ruta.is_file())
        self.assertEqual(ruta.read_text(encoding="utf-8"), "hola")
        self.assertEqual(nota.path, "diseños/logo")
        # También con carpetas intermedias múltiples.
        purplemd.crear_nota("proyecto", "a/b/c/nota", "x", self.directorio)
        self.assertTrue((self.raiz / "a" / "b" / "c" / "nota.md").is_file())

    def test_crear_nombre_duplicado_falla_sin_pisar_el_contenido(self):
        purplemd.crear_nota("proyecto", "diseños/logo", "original", self.directorio)
        with self.assertRaises(purplemd.NotaYaExiste):
            purplemd.crear_nota("proyecto", "diseños/logo.md", "nuevo", self.directorio)
        ruta = self.raiz / "diseños" / "logo.md"
        self.assertEqual(ruta.read_text(encoding="utf-8"), "original")

    def test_leer_devuelve_la_nota_completa(self):
        creada = purplemd.crear_nota("proyecto", "saludo", "hola\nchau", self.directorio)
        leida = purplemd.leer_nota("proyecto", "saludo", self.directorio)
        self.assertEqual(leida.project, "proyecto")
        self.assertEqual(leida.path, "saludo")
        self.assertEqual(leida.content, "hola\nchau")
        self.assertEqual(leida.modified, creada.modified)

    def test_leer_una_nota_anidada(self):
        purplemd.crear_nota("proyecto", "diseños/2026/logo", "hola", self.directorio)
        leida = purplemd.leer_nota("proyecto", "diseños/2026/logo", self.directorio)
        self.assertEqual(leida.content, "hola")
        self.assertEqual(leida.path, "diseños/2026/logo")

    def test_leer_inexistente_lanza_nota_no_encontrada(self):
        with self.assertRaises(purplemd.NotaNoEncontrada):
            purplemd.leer_nota("proyecto", "fantasma", self.directorio)
        with self.assertRaises(purplemd.NotaNoEncontrada):
            purplemd.leer_nota("proyecto", "diseños/fantasma", self.directorio)

    def test_leer_en_un_proyecto_inexistente_lanza_proyecto_no_existe(self):
        with self.assertRaises(purplemd.ProyectoNoExiste):
            purplemd.leer_nota("fantasma", "saludo", self.directorio)

    def test_leer_una_ruta_invalida_lanza_nombre_invalido(self):
        for ruta in ("../etc/passwd", "..", "a//b", "a/../../b"):
            with self.subTest(ruta=ruta), self.assertRaises(purplemd.NombreInvalido):
                purplemd.leer_nota("proyecto", ruta, self.directorio)

    def test_guardar_reemplaza_el_contenido(self):
        purplemd.crear_nota("proyecto", "saludo", "original", self.directorio)
        ruta = self.raiz / "saludo.md"
        os.utime(ruta, (1000, 1000))
        guardada = purplemd.guardar_nota("proyecto", "saludo", "actualizado", self.directorio)
        self.assertEqual(ruta.read_text(encoding="utf-8"), "actualizado")
        self.assertEqual(guardada.content, "actualizado")
        self.assertGreater(guardada.modified, 1000)

    def test_guardar_inexistente_lanza_nota_no_encontrada(self):
        with self.assertRaises(purplemd.NotaNoEncontrada):
            purplemd.guardar_nota("proyecto", "fantasma", "contenido", self.directorio)

    def test_guardar_en_un_proyecto_inexistente_lanza_proyecto_no_existe(self):
        with self.assertRaises(purplemd.ProyectoNoExiste):
            purplemd.guardar_nota("fantasma", "saludo", "contenido", self.directorio)


class TamanoMaximoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)
        purplemd.crear_proyecto("proyecto", self.directorio)
        self.raiz = self.directorio / "projects" / "proyecto"

    def test_crear_con_un_byte_de_mas_falla(self):
        with self.assertRaises(purplemd.NotaDemasiadoGrande):
            purplemd.crear_nota(
                "proyecto", "grande", "x" * (purplemd.MAX_BYTES + 1), self.directorio
            )
        self.assertFalse((self.raiz / "grande.md").exists())

    def test_crear_en_el_limite_pasa(self):
        nota = purplemd.crear_nota(
            "proyecto", "limite", "x" * purplemd.MAX_BYTES, self.directorio
        )
        self.assertEqual(nota.content, purplemd.MAX_BYTES * "x")

    def test_el_limite_cuenta_bytes_utf8_y_no_caracteres(self):
        # 300.000 emojis son 300.000 caracteres pero 1.200.000 bytes.
        with self.assertRaises(purplemd.NotaDemasiadoGrande):
            purplemd.crear_nota("proyecto", "emojis", "🎨" * 300_000, self.directorio)

    def test_guardar_tambien_respeta_el_limite(self):
        purplemd.crear_nota("proyecto", "saludo", "original", self.directorio)
        with self.assertRaises(purplemd.NotaDemasiadoGrande):
            purplemd.guardar_nota(
                "proyecto", "saludo", "x" * (purplemd.MAX_BYTES + 1), self.directorio
            )
        contenido = (self.raiz / "saludo.md").read_text(encoding="utf-8")
        self.assertEqual(contenido, "original")


class EscrituraAtomicaTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)
        purplemd.crear_proyecto("proyecto", self.directorio)
        self.raiz = self.directorio / "projects" / "proyecto"

    def test_no_deja_archivos_temporales(self):
        purplemd.crear_nota("proyecto", "saludo", "original", self.directorio)
        purplemd.guardar_nota("proyecto", "saludo", "actualizado", self.directorio)
        self.assertEqual([p.name for p in self.raiz.iterdir()], ["saludo.md"])

    def test_un_fallo_de_escritura_deja_la_nota_intacta(self):
        purplemd.crear_nota("proyecto", "saludo", "original", self.directorio)
        with patch("purplemd.os.fsync", side_effect=OSError("disco lleno")):
            with self.assertRaises(OSError):
                purplemd.guardar_nota("proyecto", "saludo", "actualizado", self.directorio)
        contenido = (self.raiz / "saludo.md").read_text(encoding="utf-8")
        self.assertEqual(contenido, "original")
        self.assertEqual([p.name for p in self.raiz.iterdir()], ["saludo.md"])


class DirectorioPorDefectoTests(unittest.TestCase):
    def test_el_defecto_es_local_purplemd(self):
        with patch.dict(os.environ):
            os.environ.pop("PURPLEMD_DIR", None)
            self.assertEqual(purplemd.DIR_DEFECTO, "./local/purplemd")
            self.assertEqual(purplemd._directorio_entorno(), Path(purplemd.DIR_DEFECTO))

    def test_se_lee_purplemd_dir_en_cada_llamada(self):
        # El entorno se consulta en cada llamada y no al importar el módulo.
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"PURPLEMD_DIR": tmp}
        ):
            purplemd.crear_proyecto("saludo")
            self.assertTrue((Path(tmp) / "projects" / "saludo").is_dir())
            purplemd.crear_nota("saludo", "anidada/nota", "hola")
            self.assertTrue((Path(tmp) / "projects" / "saludo" / "anidada" / "nota.md").is_file())


class RenombrarProyectoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)
        purplemd.crear_proyecto("viejo", self.directorio)
        purplemd.crear_nota("viejo", "diseños/logo", "hola", self.directorio)
        self.raiz = self.directorio / "projects" / "viejo"

    def test_renombrar_cambia_el_directorio_en_disco(self):
        proyecto = purplemd.renombrar_proyecto("viejo", "nuevo", self.directorio)
        self.assertEqual(proyecto.name, "nuevo")
        self.assertIsInstance(proyecto.modified, float)
        self.assertGreater(proyecto.modified, 0)
        self.assertFalse(self.raiz.exists())
        self.assertTrue((self.directorio / "projects" / "nuevo").is_dir())

    def test_renombrar_conserva_el_contenido(self):
        purplemd.renombrar_proyecto("viejo", "nuevo", self.directorio)
        destino = self.directorio / "projects" / "nuevo" / "diseños" / "logo.md"
        self.assertEqual(destino.read_text(encoding="utf-8"), "hola")
        nota = purplemd.leer_nota("nuevo", "diseños/logo", self.directorio)
        self.assertEqual(nota.content, "hola")

    def test_renombrar_al_mismo_nombre_es_idempotente(self):
        # Reenviar el formulario no debe fallar ni tocar el disco.
        proyecto = purplemd.renombrar_proyecto("viejo", "viejo", self.directorio)
        self.assertEqual(proyecto.name, "viejo")
        self.assertEqual(proyecto.modified, self.raiz.stat().st_mtime)
        # La extensión no cambia el nombre normalizado: sigue siendo el mismo.
        proyecto = purplemd.renombrar_proyecto("viejo", "viejo.md", self.directorio)
        self.assertEqual(proyecto.name, "viejo")
        self.assertTrue(self.raiz.is_dir())

    def test_renombrar_a_un_nombre_existente_lanza_proyecto_ya_existe(self):
        purplemd.crear_proyecto("ocupado", self.directorio)
        purplemd.crear_nota("ocupado", "saludo", "del otro", self.directorio)
        with self.assertRaises(purplemd.ProyectoYaExiste):
            purplemd.renombrar_proyecto("viejo", "ocupado", self.directorio)
        # Ni el origen ni el destino se tocan.
        self.assertEqual(
            (self.raiz / "diseños" / "logo.md").read_text(encoding="utf-8"), "hola"
        )
        otro = self.directorio / "projects" / "ocupado" / "saludo.md"
        self.assertEqual(otro.read_text(encoding="utf-8"), "del otro")

    def test_renombrar_un_proyecto_inexistente_lanza_proyecto_no_existe(self):
        with self.assertRaises(purplemd.ProyectoNoExiste):
            purplemd.renombrar_proyecto("fantasma", "nuevo", self.directorio)

    def test_renombrar_a_un_nombre_invalido_lanza_nombre_invalido(self):
        for nombre in ("", "   ", "../etc/passwd", "a/b", ".oculta", "punto.txt"):
            with self.subTest(nombre=nombre), self.assertRaises(purplemd.NombreInvalido):
                purplemd.renombrar_proyecto("viejo", nombre, self.directorio)
        self.assertTrue(self.raiz.is_dir())
        self.assertEqual(
            (self.raiz / "diseños" / "logo.md").read_text(encoding="utf-8"), "hola"
        )


class EliminarProyectoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)
        purplemd.crear_proyecto("proyecto", self.directorio)
        purplemd.crear_nota("proyecto", "diseños/2026/logo", "hola", self.directorio)
        purplemd.crear_nota("proyecto", "raiz", "x", self.directorio)

    def test_eliminar_borra_todo_recursivamente(self):
        purplemd.eliminar_proyecto("proyecto", self.directorio)
        self.assertFalse((self.directorio / "projects" / "proyecto").exists())
        # No queda nada de lo que había adentro en el disco.
        self.assertEqual(list((self.directorio / "projects").iterdir()), [])

    def test_eliminar_no_toca_a_los_demas_proyectos(self):
        purplemd.crear_proyecto("otro", self.directorio)
        purplemd.crear_nota("otro", "saludo", "intacto", self.directorio)
        purplemd.eliminar_proyecto("proyecto", self.directorio)
        intacto = self.directorio / "projects" / "otro" / "saludo.md"
        self.assertEqual(intacto.read_text(encoding="utf-8"), "intacto")

    def test_eliminar_un_proyecto_inexistente_lanza_proyecto_no_existe(self):
        with self.assertRaises(purplemd.ProyectoNoExiste):
            purplemd.eliminar_proyecto("fantasma", self.directorio)

    def test_eliminar_un_nombre_invalido_lanza_nombre_invalido(self):
        for nombre in ("", "../etc/passwd", "a/b", ".oculta"):
            with self.subTest(nombre=nombre), self.assertRaises(purplemd.NombreInvalido):
                purplemd.eliminar_proyecto(nombre, self.directorio)
        self.assertTrue((self.directorio / "projects" / "proyecto").is_dir())


class NotaEdicionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)
        purplemd.crear_proyecto("proyecto", self.directorio)
        self.raiz = self.directorio / "projects" / "proyecto"
        purplemd.crear_nota("proyecto", "diseños/logo", "hola", self.directorio)

    def _contenido(self, ruta: str) -> str:
        return (self.raiz / ruta).read_text(encoding="utf-8")

    def test_renombrar_cambia_el_nombre_en_su_misma_carpeta(self):
        nota = purplemd.renombrar_nota("proyecto", "diseños/logo", "marca", self.directorio)
        self.assertEqual(nota.path, "diseños/marca")
        self.assertEqual(nota.content, "hola")
        self.assertIsInstance(nota.modified, float)
        self.assertFalse((self.raiz / "diseños" / "logo.md").exists())
        self.assertEqual(self._contenido("diseños/marca.md"), "hola")

    def test_renombrar_con_extension_no_la_conserva(self):
        nota = purplemd.renombrar_nota("proyecto", "diseños/logo", "marca.md", self.directorio)
        self.assertEqual(nota.path, "diseños/marca")

    def test_renombrar_a_un_nombre_ocupado_lanza_destino_ocupado(self):
        purplemd.crear_nota("proyecto", "diseños/marca", "otro", self.directorio)
        with self.assertRaises(purplemd.DestinoOcupado):
            purplemd.renombrar_nota("proyecto", "diseños/logo", "marca", self.directorio)
        # Ninguno de los dos contenidos se pisa.
        self.assertEqual(self._contenido("diseños/logo.md"), "hola")
        self.assertEqual(self._contenido("diseños/marca.md"), "otro")

    def test_renombrar_una_nota_inexistente_lanza_nota_no_encontrada(self):
        with self.assertRaises(purplemd.NotaNoEncontrada):
            purplemd.renombrar_nota("proyecto", "diseños/fantasma", "marca", self.directorio)

    def test_renombrar_con_un_nombre_invalido_lanza_nombre_invalido(self):
        for nuevo in ("", "a/b", "..", "punto.txt"):
            with self.subTest(nuevo=nuevo), self.assertRaises(purplemd.NombreInvalido):
                purplemd.renombrar_nota("proyecto", "diseños/logo", nuevo, self.directorio)
        self.assertEqual(self._contenido("diseños/logo.md"), "hola")

    def test_mover_a_otra_carpeta_crea_la_destino_y_conserva_el_contenido(self):
        nota = purplemd.mover_nota(
            "proyecto", "diseños/logo", "imagenes/2026/logo", self.directorio
        )
        self.assertEqual(nota.path, "imagenes/2026/logo")
        self.assertEqual(nota.content, "hola")
        self.assertFalse((self.raiz / "diseños" / "logo.md").exists())
        self.assertEqual(self._contenido("imagenes/2026/logo.md"), "hola")
        # La carpeta origen queda pero vacía: no se borra sola.
        self.assertTrue((self.raiz / "diseños").is_dir())

    def test_mover_a_una_ruta_que_escapa_del_proyecto_lanza_nombre_invalido(self):
        for destino in ("../../etc/passwd", "/etc/passwd", "..", "a/../../b", "", "a//b"):
            with self.subTest(destino=destino), self.assertRaises(purplemd.NombreInvalido):
                purplemd.mover_nota("proyecto", "diseños/logo", destino, self.directorio)
        self.assertEqual(self._contenido("diseños/logo.md"), "hola")

    def test_mover_a_la_misma_ruta_es_idempotente(self):
        nota = purplemd.mover_nota("proyecto", "diseños/logo", "diseños/logo", self.directorio)
        self.assertEqual(nota.project, "proyecto")
        self.assertEqual(nota.path, "diseños/logo")
        self.assertEqual(nota.content, "hola")
        self.assertTrue((self.raiz / "diseños" / "logo.md").is_file())

    def test_mover_a_una_ruta_ocupada_lanza_destino_ocupado_sin_pisar(self):
        purplemd.crear_nota("proyecto", "imagenes/logo", "otro", self.directorio)
        with self.assertRaises(purplemd.DestinoOcupado):
            purplemd.mover_nota("proyecto", "diseños/logo", "imagenes/logo", self.directorio)
        self.assertEqual(self._contenido("diseños/logo.md"), "hola")
        self.assertEqual(self._contenido("imagenes/logo.md"), "otro")

    def test_mover_una_nota_inexistente_lanza_nota_no_encontrada(self):
        with self.assertRaises(purplemd.NotaNoEncontrada):
            purplemd.mover_nota("proyecto", "fantasma", "imagenes/fantasma", self.directorio)

    def test_mover_en_un_proyecto_inexistente_lanza_proyecto_no_existe(self):
        with self.assertRaises(purplemd.ProyectoNoExiste):
            purplemd.mover_nota("fantasma", "saludo", "otra/saludo", self.directorio)

    def test_eliminar_borra_el_archivo(self):
        purplemd.eliminar_nota("proyecto", "diseños/logo", self.directorio)
        self.assertFalse((self.raiz / "diseños" / "logo.md").exists())
        with self.assertRaises(purplemd.NotaNoEncontrada):
            purplemd.leer_nota("proyecto", "diseños/logo", self.directorio)

    def test_eliminar_conserva_las_carpetas_vacias(self):
        # Decisión: borrar una nota no cambia el árbol de formas sorpresivas.
        purplemd.eliminar_nota("proyecto", "diseños/logo", self.directorio)
        self.assertTrue((self.raiz / "diseños").is_dir())

    def test_eliminar_una_nota_inexistente_lanza_nota_no_encontrada(self):
        with self.assertRaises(purplemd.NotaNoEncontrada):
            purplemd.eliminar_nota("proyecto", "fantasma", self.directorio)

    def test_eliminar_en_un_proyecto_inexistente_lanza_proyecto_no_existe(self):
        with self.assertRaises(purplemd.ProyectoNoExiste):
            purplemd.eliminar_nota("fantasma", "saludo", self.directorio)

    def test_eliminar_una_ruta_invalida_lanza_nombre_invalido(self):
        for ruta in ("../etc/passwd", "..", "a//b"):
            with self.subTest(ruta=ruta), self.assertRaises(purplemd.NombreInvalido):
                purplemd.eliminar_nota("proyecto", ruta, self.directorio)
        self.assertTrue((self.raiz / "diseños" / "logo.md").is_file())


class DirectorioEdicionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)
        purplemd.crear_proyecto("proyecto", self.directorio)
        self.raiz = self.directorio / "projects" / "proyecto"
        purplemd.crear_nota("proyecto", "diseños/logo", "hola", self.directorio)
        purplemd.crear_nota("proyecto", "plantillas/base", "base", self.directorio)

    def _contenido(self, ruta: str) -> str:
        return (self.raiz / ruta).read_text(encoding="utf-8")

    def test_renombrar_cambia_el_nombre_con_su_contenido(self):
        carpeta = purplemd.renombrar_directorio(
            "proyecto", "diseños", "croquis", self.directorio
        )
        self.assertEqual(carpeta.project, "proyecto")
        self.assertEqual(carpeta.path, "croquis")
        self.assertIsInstance(carpeta.modified, float)
        self.assertFalse((self.raiz / "diseños").exists())
        self.assertEqual(self._contenido("croquis/logo.md"), "hola")

    def test_renombrar_a_un_nombre_ocupado_lanza_destino_ocupado(self):
        with self.assertRaises(purplemd.DestinoOcupado):
            purplemd.renombrar_directorio("proyecto", "diseños", "plantillas", self.directorio)
        self.assertEqual(self._contenido("diseños/logo.md"), "hola")
        self.assertEqual(self._contenido("plantillas/base.md"), "base")

    def test_renombrar_un_directorio_inexistente_lanza_directorio_no_encontrado(self):
        with self.assertRaises(purplemd.DirectorioNoEncontrado):
            purplemd.renombrar_directorio("proyecto", "fantasma", "marca", self.directorio)

    def test_renombrar_con_un_nombre_invalido_lanza_nombre_invalido(self):
        for nuevo in ("", "a/b", "..", "punto.txt"):
            with self.subTest(nuevo=nuevo), self.assertRaises(purplemd.NombreInvalido):
                purplemd.renombrar_directorio("proyecto", "diseños", nuevo, self.directorio)
        self.assertTrue((self.raiz / "diseños" / "logo.md").is_file())

    def test_mover_a_otra_carpeta_crea_la_destino(self):
        carpeta = purplemd.mover_directorio(
            "proyecto", "diseños", "archivo/2026/diseños", self.directorio
        )
        self.assertEqual(carpeta.path, "archivo/2026/diseños")
        self.assertFalse((self.raiz / "diseños").exists())
        self.assertEqual(self._contenido("archivo/2026/diseños/logo.md"), "hola")

    def test_mover_dentro_de_si_mismo_lanza_movimiento_invalido(self):
        with self.assertRaises(purplemd.MovimientoInvalido):
            purplemd.mover_directorio("proyecto", "diseños", "diseños/interno", self.directorio)
        # No se crea nada por el intento.
        self.assertFalse((self.raiz / "diseños" / "interno").exists())
        self.assertEqual(self._contenido("diseños/logo.md"), "hola")

    def test_mover_hacia_un_ancestro_lanza_movimiento_invalido(self):
        purplemd.crear_nota("proyecto", "diseños/2026/logo", "x", self.directorio)
        with self.assertRaises(purplemd.MovimientoInvalido):
            purplemd.mover_directorio("proyecto", "diseños/2026", "diseños", self.directorio)
        self.assertTrue((self.raiz / "diseños" / "2026").is_dir())

    def test_mover_a_una_ruta_ocupada_lanza_destino_ocupado_sin_pisar(self):
        with self.assertRaises(purplemd.DestinoOcupado):
            purplemd.mover_directorio("proyecto", "diseños", "plantillas", self.directorio)
        self.assertEqual(self._contenido("diseños/logo.md"), "hola")
        self.assertEqual(self._contenido("plantillas/base.md"), "base")

    def test_mover_a_una_ruta_que_escapa_del_proyecto_lanza_nombre_invalido(self):
        for destino in ("../../etc", "/etc", "..", "a/../../b", ""):
            with self.subTest(destino=destino), self.assertRaises(purplemd.NombreInvalido):
                purplemd.mover_directorio("proyecto", "diseños", destino, self.directorio)
        self.assertTrue((self.raiz / "diseños" / "logo.md").is_file())

    def test_mover_a_la_misma_ruta_es_idempotente(self):
        carpeta = purplemd.mover_directorio("proyecto", "diseños", "diseños", self.directorio)
        self.assertEqual(carpeta.path, "diseños")
        self.assertEqual(self._contenido("diseños/logo.md"), "hola")

    def test_mover_en_un_proyecto_inexistente_lanza_proyecto_no_existe(self):
        with self.assertRaises(purplemd.ProyectoNoExiste):
            purplemd.mover_directorio("fantasma", "carpeta", "otra", self.directorio)

    def test_eliminar_un_directorio_vacio(self):
        (self.raiz / "vacia").mkdir()
        purplemd.eliminar_directorio("proyecto", "vacia", directorio=self.directorio)
        self.assertFalse((self.raiz / "vacia").exists())

    def test_eliminar_un_directorio_no_vacio_lanza_directorio_no_vacio(self):
        with self.assertRaises(purplemd.DirectorioNoVacio):
            purplemd.eliminar_directorio("proyecto", "diseños", directorio=self.directorio)
        # Nada se borra sin que se pida el borrado recursivo.
        self.assertEqual(self._contenido("diseños/logo.md"), "hola")

    def test_eliminar_con_recursive_borra_todo_el_contenido(self):
        purplemd.eliminar_directorio(
            "proyecto", "diseños", recursive=True, directorio=self.directorio
        )
        self.assertFalse((self.raiz / "diseños").exists())

    def test_eliminar_un_directorio_inexistente_lanza_directorio_no_encontrado(self):
        with self.assertRaises(purplemd.DirectorioNoEncontrado):
            purplemd.eliminar_directorio("proyecto", "fantasma", directorio=self.directorio)

    def test_eliminar_un_directorio_inexistente_con_recursive_tambien_falla(self):
        with self.assertRaises(purplemd.DirectorioNoEncontrado):
            purplemd.eliminar_directorio(
                "proyecto", "fantasma", recursive=True, directorio=self.directorio
            )

    def test_eliminar_en_un_proyecto_inexistente_lanza_proyecto_no_existe(self):
        with self.assertRaises(purplemd.ProyectoNoExiste):
            purplemd.eliminar_directorio("fantasma", "carpeta", directorio=self.directorio)

    def test_eliminar_una_ruta_invalida_lanza_nombre_invalido(self):
        # "diseños/.." y las rutas absolutas no pueden salirse del proyecto.
        for ruta in ("../proyecto", "/etc", "diseños/../.."):
            with self.subTest(ruta=ruta), self.assertRaises(purplemd.NombreInvalido):
                purplemd.eliminar_directorio("proyecto", ruta, directorio=self.directorio)
        self.assertTrue((self.raiz / "diseños" / "logo.md").is_file())


if __name__ == "__main__":
    unittest.main()
