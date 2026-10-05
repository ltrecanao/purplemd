"""Tests del export/import de proyectos como ZIP.

Cubren los dos endpoints (`GET /export` y `POST /import`) y el contrato de
cada backend, que es donde vive la lógica: filesystem y memoria deben
reportar exactamente los mismos contadores para que el mismo ZIP se
importe igual en la demo (memory) que en una instalación local (filesystem).

Referencia del contrato en `docs/API.md`, sección «Exportar / Importar
proyecto (.zip)».
"""

import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import purplemd
from api import app
from purplemd_storage import FilesystemStorage, MemoryStorage


def _zip_con(*notas, metadata=True, version=1) -> bytes:
    """Arma un ZIP en memoria con las notas indicadas como `("ruta", "texto")`."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if metadata:
            zf.writestr(
                ".purplemd.json",
                json.dumps(
                    {"project": "x", "exported_at": "2026-01-01T00:00:00", "version": version}
                ),
            )
        for ruta, contenido in notas:
            zf.writestr(f"{ruta}.md", contenido)
    return buffer.getvalue()


def _zip_bomba(megabytes: int = 64) -> bytes:
    """ZIP con una entrada `bomba.md` declarada de `megabytes` MB.

    Comprime a casi nada porque son ceros: el central directory promete
    megabytes que `zf.read()` tendría que materializar en memoria. Ese es el
    ataque; la defensa es mirar `file_size` antes de leer.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            ".purplemd.json",
            json.dumps({"project": "p", "exported_at": "x", "version": 1}),
        )
        with zf.open("bomba.md", "w") as destino:
            trozo = b"\0" * (1024 * 1024)
            for _ in range(megabytes):
                destino.write(trozo)
    return buffer.getvalue()


class ApiZipTestCase(unittest.TestCase):
    """Base: directorio de datos aislado y cliente HTTP."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)
        self._entorno = patch.dict(os.environ, {"PURPLEMD_DIR": str(self.directorio)})
        self._entorno.start()
        self.addCleanup(self._entorno.stop)
        self.client = TestClient(app)

    def crear(self, nombre: str, notas: dict) -> None:
        """Crea un proyecto con las notas indicadas, vía API."""
        self.assertEqual(self.client.post("/api/projects", json={"name": nombre}).status_code, 201)
        for ruta, contenido in notas.items():
            r = self.client.post(
                f"/api/projects/{nombre}/notes", json={"path": ruta, "content": contenido}
            )
            self.assertEqual(r.status_code, 201, r.text)


class ExportTests(ApiZipTestCase):
    """GET /api/projects/{project}/export"""

    def test_export_responde_un_zip_descargable(self):
        self.crear("cuaderno", {"portada": "# hola"})
        r = self.client.get("/api/projects/cuaderno/export")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/zip")
        self.assertIn('filename="cuaderno.zip"', r.headers["content-disposition"])

    def test_el_zip_trae_metadata_y_todas_las_notas(self):
        self.crear("cuaderno", {"portada": "# hola", "diseños/logo": "![x](y)"})
        r = self.client.get("/api/projects/cuaderno/export")
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            nombres = sorted(zf.namelist())
            self.assertEqual(nombres, [".purplemd.json", "diseños/logo.md", "portada.md"])
            meta = json.loads(zf.read(".purplemd.json"))
            self.assertEqual(meta["version"], 1)
            self.assertEqual(meta["project"], "cuaderno")
            self.assertEqual(zf.read("portada.md").decode("utf-8"), "# hola")

    def test_las_rutas_viajan_relativas_sin_prefijo_de_usuario(self):
        """El ZIP es portable: el namespace no puede colarse en las rutas."""
        self.crear("u_abc_proyecto", {"carpeta/nota": "x"})
        r = self.client.get("/api/projects/u_abc_proyecto/export")
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            for nombre in zf.namelist():
                self.assertNotIn("u_abc", nombre)

    def test_exportar_proyecto_inexistente_responde_404(self):
        self.assertEqual(self.client.get("/api/projects/no-existe/export").status_code, 404)

    def test_exportar_nombre_invalido_responde_422(self):
        """`..` llega al validador de `purplemd_storage` y lo rechaza.

        Va codificado como `%2E%2E`: un `%2F` en medio haría que la ruta no
        coincidiera con el patrón del router y Starlette respondería 404
        antes de llegar a la validación, que es un camino distinto.
        """
        self.assertEqual(self.client.get("/api/projects/%2E%2E/export").status_code, 422)


class ImportTests(ApiZipTestCase):
    """POST /api/projects/{project}/import"""

    def _importar(self, proyecto: str, data: bytes, nombre="p.zip"):
        return self.client.post(
            f"/api/projects/{proyecto}/import",
            files={"file": (nombre, data, "application/zip")},
        )

    def test_import_crea_el_proyecto_y_las_notas(self):
        r = self._importar("nuevo", _zip_con(("portada", "# hola"), ("a/b/nota", "x")))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"creadas": 2, "actualizadas": 0, "omitidas": 0, "errores": []})
        nota = self.client.get("/api/projects/nuevo/notes/a/b/nota")
        self.assertEqual(nota.status_code, 200)
        self.assertEqual(nota.json()["content"], "x")

    def test_import_en_proyecto_existente_actualiza_sin_pisar_lo_demás(self):
        self.crear("viejo", {"uno": "original", "dos": "se conserva"})
        r = self._importar("viejo", _zip_con(("uno", "reescrita"), ("tres", "nueva")))
        self.assertEqual(r.json(), {"creadas": 1, "actualizadas": 1, "omitidas": 0, "errores": []})
        self.assertEqual(
            self.client.get("/api/projects/viejo/notes/uno").json()["content"], "reescrita"
        )
        self.assertEqual(
            self.client.get("/api/projects/viejo/notes/dos").json()["content"], "se conserva"
        )

    def test_segunda_import_es_idempotente(self):
        self._importar("rep", _zip_con(("nota", "x")))
        r = self._importar("rep", _zip_con(("nota", "x")))
        self.assertEqual(r.json(), {"creadas": 0, "actualizadas": 1, "omitidas": 0, "errores": []})

    def test_rechaza_archivos_que_no_son_zip(self):
        r = self.client.post(
            "/api/projects/x/import", files={"file": ("notas.txt", b"hola", "text/plain")}
        )
        self.assertEqual(r.status_code, 422)

    def test_zip_sobre_el_tope_de_subida_responde_413(self):
        """El tope se aplica sobre el archivo subido y antes de importar:
        no se crea nada y el ZIP ni se abre."""
        with patch("api.MAX_IMPORT_ZIP_BYTES", 10):
            r = self._importar("gigante", _zip_con(("nota", "x")))
        self.assertEqual(r.status_code, 413)
        self.assertIn("10 bytes", r.json()["detail"])
        self.assertEqual(self.client.get("/api/projects/gigante/tree").status_code, 404)

    def test_zip_bomba_no_llega_a_descomprimirse(self):
        """La entrada gigante se descarta por el `file_size` del central
        directory y **antes** de `zf.read()`: medir después de leer ya habría
        costado la memoria, que es justo lo que busca la zip bomb. Si el
        `zf.read()` llega a materializar `bomba.md`, el test falla."""
        original = zipfile.ZipFile.read

        def leer_sin_bomba(self, nombre, *args, **kwargs):
            entrada = getattr(nombre, "filename", nombre)
            if str(entrada).startswith("bomba"):
                raise AssertionError(f"zf.read() materializó {entrada}")
            return original(self, nombre, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "read", leer_sin_bomba):
            r = self._importar("p", _zip_bomba())

        self.assertEqual(r.status_code, 200, r.text)
        cuerpo = r.json()
        self.assertEqual(cuerpo["creadas"], 0)
        motivo = f"supera {purplemd.MAX_BYTES} bytes ({64 * 1024 * 1024})"
        self.assertTrue(
            any(e["path"] == "bomba" and e["motivo"] == motivo for e in cuerpo["errores"]),
            cuerpo["errores"],
        )
        self.assertFalse((self.directorio / "projects" / "p" / "bomba.md").exists())

    def test_zip_corrupto_responde_con_error_reportado(self):
        r = self._importar("rotto", b"esto no es un zip")
        self.assertEqual(r.status_code, 200)
        cuerpo = r.json()
        self.assertEqual(cuerpo["creadas"], 0)
        self.assertTrue(any("ZIP" in e["motivo"] for e in cuerpo["errores"]))

    def test_zip_sin_metadata_se_reporta_y_no_escribe_nada(self):
        r = self._importar("sinmeta", _zip_con(("nota", "x"), metadata=False))
        cuerpo = r.json()
        self.assertEqual(cuerpo["creadas"], 0)
        self.assertTrue(any(e["path"] == ".purplemd.json" for e in cuerpo["errores"]))
        self.assertEqual(self.client.get("/api/projects/sinmeta/tree").status_code, 200)

    def test_version_de_metadata_incompatible_se_reporta(self):
        r = self._importar("v9", _zip_con(("nota", "x"), version=9))
        cuerpo = r.json()
        self.assertEqual(cuerpo["creadas"], 0)
        self.assertTrue(any("versión" in e["motivo"] for e in cuerpo["errores"]))

    def test_archivos_no_markdown_se_omiten_y_se_reportan(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                ".purplemd.json",
                json.dumps({"project": "mix", "exported_at": "x", "version": 1}),
            )
            zf.writestr("buena.md", "x")
            zf.writestr("foto.png", "\x89PNG")
        r = self._importar("mix", buffer.getvalue())
        cuerpo = r.json()
        self.assertEqual(cuerpo["creadas"], 1)
        self.assertEqual(cuerpo["omitidas"], 1)
        self.assertTrue(any(e["motivo"] == "no es un archivo .md" for e in cuerpo["errores"]))

    def test_ruta_con_path_traversal_se_omite_y_se_reporta(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                ".purplemd.json",
                json.dumps({"project": "p", "exported_at": "x", "version": 1}),
            )
            zf.writestr("../fuera.md", "x")
        r = self._importar("p", buffer.getvalue())
        cuerpo = r.json()
        self.assertEqual(cuerpo["creadas"], 0)
        self.assertTrue(cuerpo["errores"])
        # No creó nada fuera del directorio de datos.
        self.assertFalse((self.directorio / "fuera.md").exists())

    def test_round_trip_export_import_conserva_el_contenido(self):
        self.crear("origen", {"portada": "# título", "carpeta/anidada": "**negrita**"})
        zip_bytes = self.client.get("/api/projects/origen/export").content
        r = self._importar("destino", zip_bytes)
        self.assertEqual(r.json()["creadas"], 2)
        for ruta in ("portada", "carpeta/anidada"):
            with self.subTest(ruta=ruta):
                origen = self.client.get(f"/api/projects/origen/notes/{ruta}").json()["content"]
                destino = self.client.get(f"/api/projects/destino/notes/{ruta}").json()["content"]
                self.assertEqual(origen, destino)


class ContratoBackendsTests(unittest.TestCase):
    """Los dos backends deben reportar lo mismo para el mismo ZIP."""

    def test_filesystem_y_memoria_reportan_los_mismos_contadores(self):
        zip_bytes = _zip_con(("a", "x"), ("b/c", "y"))
        resultados = [
            MemoryStorage().importar_proyecto("destino", zip_bytes),
            self._filesystem().importar_proyecto("destino", zip_bytes),
        ]
        self.assertEqual(resultados[0], resultados[1])

    def _filesystem(self) -> FilesystemStorage:
        """Backend en un temporal que se limpia al terminar el test."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return FilesystemStorage(Path(tmp.name))

    def test_export_import_round_trip_en_memoria(self):
        storage = MemoryStorage()
        storage.crear_proyecto("origen")
        storage.crear_nota("origen", "portada", "# hola")
        storage.crear_nota("origen", "sub/nota", "x")
        zip_bytes = storage.exportar_proyecto("origen")
        r = storage.importar_proyecto("copia", zip_bytes)
        self.assertEqual(r["creadas"], 2)
        self.assertEqual(storage.leer_nota("copia", "portada").content, "# hola")

    def test_export_import_round_trip_en_filesystem(self):
        storage = self._filesystem()
        storage.crear_proyecto("origen")
        storage.crear_nota("origen", "portada", "# hola")
        storage.crear_nota("origen", "sub/nota", "x")
        zip_bytes = storage.exportar_proyecto("origen")
        r = storage.importar_proyecto("copia", zip_bytes)
        self.assertEqual(r["creadas"], 2)
        self.assertEqual(storage.leer_nota("copia", "portada").content, "# hola")
        self.assertEqual(storage.leer_nota("copia", "sub/nota").content, "x")

    def test_exportar_proyecto_inexistente_lanza(self):
        for storage in (MemoryStorage(), self._filesystem()):
            with self.subTest(backend=type(storage).__name__):
                with self.assertRaises(purplemd.ProyectoNoExiste):
                    storage.exportar_proyecto("no-existe")

    def test_import_omite_notas_sobre_el_limite(self):
        grande = "x" * (purplemd.MAX_BYTES + 1)
        zip_bytes = _zip_con(("grande", grande), ("chica", "ok"))
        r = MemoryStorage().importar_proyecto("p", zip_bytes)
        self.assertEqual(r["creadas"], 1)
        self.assertEqual(r["omitidas"], 1)
        self.assertTrue(any("bytes" in e["motivo"] for e in r["errores"]))

    def test_el_total_descomprimido_tambien_esta_acotado(self):
        """Cada nota puede estar en el límite, pero la suma de todas no:
        un ZIP de notas chicas no puede descomprimir media memoria."""
        notas = [(f"nota{i}", "x" * purplemd.MAX_BYTES) for i in range(5)]
        zip_bytes = _zip_con(*notas)
        tope = 3 * purplemd.MAX_BYTES
        with patch("purplemd_storage.protocol.MAX_IMPORT_TOTAL_BYTES", tope):
            resultados = [
                MemoryStorage().importar_proyecto("destino", zip_bytes),
                self._filesystem().importar_proyecto("destino", zip_bytes),
            ]
        self.assertEqual(resultados[0], resultados[1])
        self.assertEqual(resultados[0]["creadas"], 3)
        self.assertTrue(
            any("descomprimidos" in e["motivo"] for e in resultados[0]["errores"]),
            resultados[0]["errores"],
        )


if __name__ == "__main__":
    unittest.main()
