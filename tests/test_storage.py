"""Tests para el backend MemoryStorage."""

import threading
import unittest

from purplemd_storage import MemoryStorage
from purplemd_storage.protocol import (
    DestinoOcupado,
    DirectorioNoEncontrado,
    DirectorioNoVacio,
    MovimientoInvalido,
    NombreInvalido,
    NotaDemasiadoGrande,
    NotaNoEncontrada,
    NotaYaExiste,
    ProyectoNoExiste,
    ProyectoYaExiste,
)


class MemoryStorageProyectoTests(unittest.TestCase):
    """Tests de proyectos con MemoryStorage."""

    def setUp(self):
        self.storage = MemoryStorage()

    def test_crear_proyecto(self):
        proyecto = self.storage.crear_proyecto("mi proyecto")
        self.assertEqual(proyecto.name, "mi proyecto")
        self.assertIsInstance(proyecto.modified, float)
        self.assertGreater(proyecto.modified, 0)

    def test_crear_proyecto_duplicado_lanza_proyecto_ya_existe(self):
        self.storage.crear_proyecto("saludo")
        with self.assertRaises(ProyectoYaExiste):
            self.storage.crear_proyecto("saludo")

    def test_crear_proyecto_nombre_invalido_lanza_nombre_invalido(self):
        invalidos = ("", "   ", "../etc/passwd", "a/b", ".oculta", "punto.txt", "con*estrella")
        for nombre in invalidos:
            with self.subTest(nombre=nombre), self.assertRaises(NombreInvalido):
                self.storage.crear_proyecto(nombre)

    def test_listar_proyectos_vacio(self):
        self.assertEqual(self.storage.listar_proyectos(), [])

    def test_listar_proyectos_ordenados_por_modificacion(self):
        self.storage.crear_proyecto("vieja")
        self.storage.crear_proyecto("media")
        self.storage.crear_proyecto("nueva")
        proyectos = self.storage.listar_proyectos()
        self.assertEqual([p.name for p in proyectos], ["nueva", "media", "vieja"])

    def test_renombrar_proyecto(self):
        self.storage.crear_proyecto("viejo")
        proyecto = self.storage.renombrar_proyecto("viejo", "nuevo")
        self.assertEqual(proyecto.name, "nuevo")
        self.assertEqual([p.name for p in self.storage.listar_proyectos()], ["nuevo"])

    def test_renombrar_proyecto_mismo_nombre_idempotente(self):
        self.storage.crear_proyecto("viejo")
        original = self.storage.renombrar_proyecto("viejo", "viejo")
        self.assertEqual(original.name, "viejo")
        self.assertEqual([p.name for p in self.storage.listar_proyectos()], ["viejo"])

    def test_renombrar_proyecto_a_existente_lanza_proyecto_ya_existe(self):
        self.storage.crear_proyecto("viejo")
        self.storage.crear_proyecto("ocupado")
        with self.assertRaises(ProyectoYaExiste):
            self.storage.renombrar_proyecto("viejo", "ocupado")

    def test_eliminar_proyecto(self):
        self.storage.crear_proyecto("proyecto")
        self.storage.crear_nota("proyecto", "nota", "contenido")
        self.storage.eliminar_proyecto("proyecto")
        self.assertEqual(self.storage.listar_proyectos(), [])

    def test_operar_proyecto_inexistente_lanza_proyecto_no_existe(self):
        with self.assertRaises(ProyectoNoExiste):
            self.storage.arbol_proyecto("fantasma")
        with self.assertRaises(ProyectoNoExiste):
            self.storage.leer_nota("fantasma", "nota")
        with self.assertRaises(ProyectoNoExiste):
            self.storage.crear_nota("fantasma", "nota", "x")


class MemoryStorageNotasTests(unittest.TestCase):
    """Tests de notas con MemoryStorage."""

    def setUp(self):
        self.storage = MemoryStorage()
        self.storage.crear_proyecto("proyecto")

    def test_crear_nota(self):
        nota = self.storage.crear_nota("proyecto", "saludo", "hola")
        self.assertEqual(nota.project, "proyecto")
        self.assertEqual(nota.path, "saludo")
        self.assertEqual(nota.content, "hola")
        self.assertIsInstance(nota.modified, float)
        self.assertGreater(nota.modified, 0)

    def test_crear_nota_anidada_crea_carpetas_intermedias(self):
        nota = self.storage.crear_nota("proyecto", "diseños/logo", "hola")
        self.assertEqual(nota.path, "diseños/logo")
        self.assertEqual(nota.content, "hola")

    def test_crear_nota_duplicada_lanza_nota_ya_existe(self):
        self.storage.crear_nota("proyecto", "saludo", "original")
        with self.assertRaises(NotaYaExiste):
            self.storage.crear_nota("proyecto", "saludo", "nuevo")

    def test_leer_nota(self):
        creada = self.storage.crear_nota("proyecto", "saludo", "hola\nchau")
        leida = self.storage.leer_nota("proyecto", "saludo")
        self.assertEqual(leida.content, "hola\nchau")
        self.assertEqual(leida.modified, creada.modified)

    def test_leer_nota_inexistente_lanza_nota_no_encontrada(self):
        with self.assertRaises(NotaNoEncontrada):
            self.storage.leer_nota("proyecto", "fantasma")

    def test_guardar_nota_reemplaza_contenido(self):
        self.storage.crear_nota("proyecto", "saludo", "original")
        guardada = self.storage.guardar_nota("proyecto", "saludo", "actualizado")
        self.assertEqual(guardada.content, "actualizado")
        self.assertGreater(guardada.modified, 0)

    def test_guardar_nota_inexistente_lanza_nota_no_encontrada(self):
        with self.assertRaises(NotaNoEncontrada):
            self.storage.guardar_nota("proyecto", "fantasma", "contenido")

    def test_renombrar_nota(self):
        self.storage.crear_nota("proyecto", "diseños/logo", "hola")
        nota = self.storage.renombrar_nota("proyecto", "diseños/logo", "marca")
        self.assertEqual(nota.path, "diseños/marca")
        self.assertEqual(nota.content, "hola")

    def test_mover_nota(self):
        self.storage.crear_nota("proyecto", "diseños/logo", "hola")
        nota = self.storage.mover_nota("proyecto", "diseños/logo", "imagenes/2026/logo")
        self.assertEqual(nota.path, "imagenes/2026/logo")
        self.assertEqual(nota.content, "hola")

    def test_mover_nota_a_misma_ruta_idempotente(self):
        self.storage.crear_nota("proyecto", "diseños/logo", "hola")
        nota = self.storage.mover_nota("proyecto", "diseños/logo", "diseños/logo")
        self.assertEqual(nota.path, "diseños/logo")
        self.assertEqual(nota.content, "hola")

    def test_mover_nota_a_destino_ocupado_lanza_destino_ocupado(self):
        self.storage.crear_nota("proyecto", "diseños/logo", "hola")
        self.storage.crear_nota("proyecto", "imagenes/logo", "otro")
        with self.assertRaises(DestinoOcupado):
            self.storage.mover_nota("proyecto", "diseños/logo", "imagenes/logo")

    def test_eliminar_nota(self):
        self.storage.crear_nota("proyecto", "diseños/logo", "hola")
        self.storage.eliminar_nota("proyecto", "diseños/logo")
        with self.assertRaises(NotaNoEncontrada):
            self.storage.leer_nota("proyecto", "diseños/logo")

    def test_tamano_maximo_nota(self):
        with self.assertRaises(NotaDemasiadoGrande):
            self.storage.crear_nota("proyecto", "grande", "x" * 2_000_000)

    def test_guardar_tambien_respeta_limite(self):
        self.storage.crear_nota("proyecto", "saludo", "original")
        with self.assertRaises(NotaDemasiadoGrande):
            self.storage.guardar_nota("proyecto", "saludo", "x" * 2_000_000)


class MemoryStorageDirectoriosTests(unittest.TestCase):
    """Tests de directorios con MemoryStorage."""

    def setUp(self):
        self.storage = MemoryStorage()
        self.storage.crear_proyecto("proyecto")
        self.storage.crear_nota("proyecto", "diseños/logo", "hola")
        self.storage.crear_nota("proyecto", "plantillas/base", "base")

    def test_renombrar_directorio(self):
        carpeta = self.storage.renombrar_directorio("proyecto", "diseños", "croquis")
        self.assertEqual(carpeta.path, "croquis")
        nota = self.storage.leer_nota("proyecto", "croquis/logo")
        self.assertEqual(nota.content, "hola")

    def test_mover_directorio(self):
        carpeta = self.storage.mover_directorio("proyecto", "diseños", "archivo/2026/diseños")
        self.assertEqual(carpeta.path, "archivo/2026/diseños")
        nota = self.storage.leer_nota("proyecto", "archivo/2026/diseños/logo")
        self.assertEqual(nota.content, "hola")

    def test_mover_directorio_dentro_de_si_mismo_lanza_movimiento_invalido(self):
        with self.assertRaises(MovimientoInvalido):
            self.storage.mover_directorio("proyecto", "diseños", "diseños/interno")

    def test_mover_directorio_hacia_ancestro_lanza_movimiento_invalido(self):
        self.storage.crear_nota("proyecto", "diseños/2026/logo", "x")
        with self.assertRaises(MovimientoInvalido):
            self.storage.mover_directorio("proyecto", "diseños/2026", "diseños")

    def test_mover_directorio_a_destino_ocupado_lanza_destino_ocupado(self):
        with self.assertRaises(DestinoOcupado):
            self.storage.mover_directorio("proyecto", "diseños", "plantillas")

    def test_mover_directorio_a_misma_ruta_idempotente(self):
        carpeta = self.storage.mover_directorio("proyecto", "diseños", "diseños")
        self.assertEqual(carpeta.path, "diseños")

    def test_eliminar_directorio_vacio(self):
        # Crear directorio vacío
        self.storage.crear_nota("proyecto", "vacia/nota", "x")
        self.storage.eliminar_nota("proyecto", "vacia/nota")
        # El directorio 'vacia' debería existir
        # MemoryStorage no elimina directorios vacíos automáticamente
        # así que podemos borrarlo
        self.storage.eliminar_directorio("proyecto", "vacia")

    def test_eliminar_directorio_no_vacio_lanza_directorio_no_vacio(self):
        with self.assertRaises(DirectorioNoVacio):
            self.storage.eliminar_directorio("proyecto", "diseños")

    def test_eliminar_directorio_con_recursive(self):
        self.storage.eliminar_directorio("proyecto", "diseños", recursive=True)
        with self.assertRaises(NotaNoEncontrada):
            self.storage.leer_nota("proyecto", "diseños/logo")

    def test_eliminar_directorio_inexistente_lanza_directorio_no_encontrado(self):
        with self.assertRaises(DirectorioNoEncontrado):
            self.storage.eliminar_directorio("proyecto", "fantasma")


class MemoryStorageArbolTests(unittest.TestCase):
    """Tests del árbol con MemoryStorage."""

    def setUp(self):
        self.storage = MemoryStorage()
        self.storage.crear_proyecto("arbol")
        for nota in ("raiz", "zeta", "alpha/beta", "alpha/sub/gamma", "omega/delta"):
            self.storage.crear_nota("arbol", nota, nota)

    def test_arbol_ordenado_carpetas_primero_notas_despues(self):
        resultado = self.storage.arbol_proyecto("arbol")
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

    def test_rutas_de_notas_sin_extension(self):
        resultado = self.storage.arbol_proyecto("arbol")
        for entrada in resultado.entries:
            self.assertFalse(entrada.path.endswith(".md"))


class MemoryStorageEstaOperativoTests(unittest.TestCase):
    """Tests de esta_operativo."""

    def test_memory_siempre_operativo(self):
        storage = MemoryStorage()
        self.assertTrue(storage.esta_operativo())


class MemoryStorageConcurrenciaTests(unittest.TestCase):
    """Tests básicos de concurrencia (thread-safety por GIL)."""

    def setUp(self):
        self.storage = MemoryStorage()
        self.storage.crear_proyecto("proyecto")

    def test_crear_notas_concurrentes(self):
        """Crear notas desde múltiples hilos no debe corromper el estado."""
        errores = []

        def crear_nota(i: int):
            try:
                self.storage.crear_nota("proyecto", f"nota{i}", f"contenido{i}")
            except Exception as e:
                errores.append(e)

        hilos = [threading.Thread(target=crear_nota, args=(i,)) for i in range(50)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        self.assertEqual(len(errores), 0, f"Errores: {errores}")
        # Verificar que todas las notas se crearon
        arbol = self.storage.arbol_proyecto("proyecto")
        self.assertEqual(len(arbol.entries), 50)

    def test_guardar_notas_concurrentes_misma_nota(self):
        """Guardar en la misma nota desde múltiples hilos."""
        self.storage.crear_nota("proyecto", "compartida", "inicial")
        errores = []

        def guardar(i: int):
            try:
                self.storage.guardar_nota("proyecto", "compartida", f"valor{i}")
            except Exception as e:
                errores.append(e)

        hilos = [threading.Thread(target=guardar, args=(i,)) for i in range(20)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        self.assertEqual(len(errores), 0, f"Errores: {errores}")
        # La nota debe tener uno de los valores escritos
        nota = self.storage.leer_nota("proyecto", "compartida")
        self.assertTrue(nota.content.startswith("valor"))


class MemoryStorageAislamientoTests(unittest.TestCase):
    """Tests de aislamiento entre instancias de MemoryStorage."""

    def test_instancias_independientes(self):
        storage1 = MemoryStorage()
        storage2 = MemoryStorage()

        storage1.crear_proyecto("proyecto1")
        storage1.crear_nota("proyecto1", "nota", "valor1")

        storage2.crear_proyecto("proyecto2")
        storage2.crear_nota("proyecto2", "nota", "valor2")

        # Cada storage tiene sus propios datos
        self.assertEqual(storage1.leer_nota("proyecto1", "nota").content, "valor1")
        self.assertEqual(storage2.leer_nota("proyecto2", "nota").content, "valor2")

        # storage2 no ve proyecto1
        with self.assertRaises(ProyectoNoExiste):
            storage2.arbol_proyecto("proyecto1")


class MemoryStorageEdgeCasesTests(unittest.TestCase):
    """Tests de casos edge."""

    def setUp(self):
        self.storage = MemoryStorage()
        self.storage.crear_proyecto("proyecto")

    def test_nota_con_ruta_con_extension(self):
        nota = self.storage.crear_nota("proyecto", "saludo.md", "hola")
        self.assertEqual(nota.path, "saludo")

    def test_crear_proyecto_con_extension(self):
        proyecto = self.storage.crear_proyecto("saludo.md")
        self.assertEqual(proyecto.name, "saludo")

    def test_renombrar_proyecto_con_extension(self):
        self.storage.crear_proyecto("viejo")
        proyecto = self.storage.renombrar_proyecto("viejo", "nuevo.md")
        self.assertEqual(proyecto.name, "nuevo")

    def test_ruta_con_segmentos_vacios_rechazada(self):
        with self.assertRaises(NombreInvalido):
            self.storage.crear_nota("proyecto", "a//b", "x")

    def test_ruta_sobre_limite_bytes_rechazada(self):
        with self.assertRaises(NombreInvalido):
            self.storage.crear_nota("proyecto", "a" * 300, "x")

    def test_profundidad_maxima_10(self):
        ruta = "/".join(["n"] * 10)
        nota = self.storage.crear_nota("proyecto", ruta, "x")
        self.assertEqual(nota.path, ruta)

    def test_profundidad_11_rechazada(self):
        ruta = "/".join(["n"] * 11)
        with self.assertRaises(NombreInvalido):
            self.storage.crear_nota("proyecto", ruta, "x")


if __name__ == "__main__":
    unittest.main()
