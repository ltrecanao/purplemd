"""Tests del backend FilesystemStorage.

Solo lo que no cubre el contrato de `tests/test_drive.py`: acá se fija el
reloj con `os.utime` para forzar escenarios que en disco ocurren solos
pero de forma aleatoria (medido: dos `mkdir` seguidos comparten `mtime`,
porque el reloj de archivos es grosero), y ahí el orden no puede depender
de `iterdir()`.
"""

import os
import tempfile
import unittest
from pathlib import Path

from purplemd_storage import FilesystemStorage
from purplemd_storage.protocol import DIR_PROYECTOS

# Instantes fijos para los `mtime`: el valor en sí no importa, solo si
# son iguales o cuál es el más grande.
T = 1_700_000_000


class FilesystemStorageListarTests(unittest.TestCase):
    """`listar_proyectos` ordena por `modified` y desempata por nombre."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.storage = FilesystemStorage(Path(tmp.name))
        self.base = Path(tmp.name) / DIR_PROYECTOS

    def _fijar_mtime(self, nombre: str, momento: float) -> None:
        """Pisa el mtime de un proyecto para poder provocar un empate."""
        ruta = self.base / nombre
        os.utime(ruta, (momento, momento))

    def test_mismo_mtime_desempata_por_nombre_descendente(self):
        """Con el mtime igualado no manda `iterdir()` (que varía entre
        sistemas de archivos) sino el nombre: orden determinista. Sin
        esto, el backend empataba con `memory` al azar en CI."""
        self.storage.crear_proyecto("aaa")
        self.storage.crear_proyecto("zzz")
        self._fijar_mtime("aaa", T)
        self._fijar_mtime("zzz", T)
        nombres = [p.name for p in self.storage.listar_proyectos()]
        self.assertEqual(nombres, ["zzz", "aaa"])

    def test_con_mtimes_distintos_manda_lo_mas_reciente(self):
        """El nombre es solo desempate: si los mtime difieren, gana el
        más nuevo aunque su nombre sea alfabéticamente menor."""
        self.storage.crear_proyecto("zzz")
        self.storage.crear_proyecto("aaa")
        self._fijar_mtime("zzz", T)
        self._fijar_mtime("aaa", T + 1000)
        nombres = [p.name for p in self.storage.listar_proyectos()]
        self.assertEqual(nombres, ["aaa", "zzz"])


if __name__ == "__main__":
    unittest.main()
