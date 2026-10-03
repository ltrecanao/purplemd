"""Tests de las tres rutas de `/api/notifications`.

Son la única superficie de API escrita en memoria (sin storage detrás), así
que el aislamiento es lo delicado: `_notificaciones` es una lista global de
módulo y arranca con la notificación de bienvenida que `api.py` crea al
importarse. Cada test la respalda y la repone, para que el orden en que
corran no cambie lo que miden.

Contrato en `docs/API.md`, fila «Notificaciones».
"""

import unittest

from fastapi.testclient import TestClient

import api


class NotificacionesTestCase(unittest.TestCase):
    """Base: cliente HTTP y lista global respaldada por test."""

    def setUp(self):
        # La bienvenida vive en la lista desde el import; se copia y se
        # repone en cleanup para que cada test parta del mismo estado.
        self._respaldo = list(api._notificaciones)
        self.addCleanup(self._restaurar)
        api._notificaciones.clear()
        self.client = TestClient(api.app)

    def _restaurar(self):
        api._notificaciones.clear()
        api._notificaciones.extend(self._respaldo)

    def crear(self, titulo="Aviso", mensaje="texto") -> dict:
        r = self.client.post("/api/notifications", json={"titulo": titulo, "mensaje": mensaje})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def listar(self) -> list:
        """Notificaciones no leídas, en el orden en que las entrega la API."""
        r = self.client.get("/api/notifications")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["notifications"]


class ListarTests(NotificacionesTestCase):
    """GET /api/notifications"""

    def test_lista_vacia_devuelve_lista_vacia(self):
        self.assertEqual(self.listar(), [])

    def test_devuelve_id_titulo_y_mensaje(self):
        creada = self.crear("Título", "Mensaje")
        self.assertEqual(
            self.listar(),
            [{"id": creada["id"], "titulo": "Título", "mensaje": "Mensaje"}],
        )

    def test_no_expone_el_campo_leida(self):
        """El contrato de API.md es {id, titulo, mensaje}; `leida` es interno."""
        self.crear()
        self.assertNotIn("leida", self.listar()[0])

    def test_las_leidas_dejan_de_aparecer(self):
        creada = self.crear("Se va", "chau")
        self.assertEqual(
            self.client.post(f"/api/notifications/{creada['id']}/read").status_code, 204
        )
        self.assertEqual(self.listar(), [])

    def test_el_orden_es_el_de_creacion(self):
        ids = [self.crear(f"n{i}")["id"] for i in range(3)]
        self.assertEqual([n["id"] for n in self.listar()], ids)

    def test_la_bienvenida_del_arranque_esta_listada(self):
        """Al importar `api` ya hay una notificación: la ve quien pregunte."""
        self.assertEqual(len(self._respaldo), 1)
        self.assertEqual(self._respaldo[0].titulo, "Notificaciones activas")
        self.assertFalse(self._respaldo[0].leida)
        api._notificaciones.extend(self._respaldo)
        self.assertIn("Notificaciones activas", [n["titulo"] for n in self.listar()])


class CrearTests(NotificacionesTestCase):
    """POST /api/notifications"""

    def test_crea_y_devuelve_201_con_el_id(self):
        r = self.client.post("/api/notifications", json={"titulo": "T", "mensaje": "M"})
        self.assertEqual(r.status_code, 201)
        cuerpo = r.json()
        self.assertEqual(cuerpo["titulo"], "T")
        self.assertEqual(cuerpo["mensaje"], "M")
        self.assertTrue(cuerpo["id"])

    def test_los_ids_son_autoincrementales_y_unicos(self):
        ids = {self.crear()["id"] for _ in range(5)}
        self.assertEqual(len(ids), 5)

    def test_aparece_en_el_listado_tras_crearla(self):
        self.crear("Recién")
        self.assertEqual([n["titulo"] for n in self.listar()], ["Recién"])

    def test_falta_el_titulo_responde_422(self):
        self.assertEqual(
            self.client.post("/api/notifications", json={"mensaje": "solo"}).status_code, 422
        )

    def test_falta_el_mensaje_responde_422(self):
        self.assertEqual(
            self.client.post("/api/notifications", json={"titulo": "solo"}).status_code, 422
        )

    def test_cuerpo_vacio_responde_422(self):
        self.assertEqual(self.client.post("/api/notifications", json={}).status_code, 422)

    def test_los_strings_vacios_estan_permitidos(self):
        """Solo se exige la presencia del campo, no su contenido.

        Documentado así en API.md («recibe {titulo, mensaje}»); si algún día
        se quiere rechazar vacíos, cambia el contrato y este test.
        """
        creada = self.crear("", "")
        self.assertEqual(creada["titulo"], "")
        self.assertEqual(creada["mensaje"], "")
        self.assertEqual(
            [n for n in self.listar() if not n["titulo"]],
            [{"id": creada["id"], "titulo": "", "mensaje": ""}],
        )


class MarcarLeidaTests(NotificacionesTestCase):
    """POST /api/notifications/{notif_id}/read"""

    def test_marca_como_leida_y_devuelve_204_sin_cuerpo(self):
        creada = self.crear()
        r = self.client.post(f"/api/notifications/{creada['id']}/read")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.content, b"")
        self.assertTrue(api._notificaciones[0].leida)

    def test_id_desconocido_tambien_devuelve_204(self):
        """Idempotencia documentada: «con un id desconocido también 204»."""
        self.assertEqual(self.client.post("/api/notifications/999999/read").status_code, 204)

    def test_repetir_no_reeleva_ni_errorea(self):
        creada = self.crear()
        url = f"/api/notifications/{creada['id']}/read"
        for _ in range(3):
            with self.subTest(intento=_):
                self.assertEqual(self.client.post(url).status_code, 204)
        self.assertTrue(api._notificaciones[0].leida)

    def test_marcar_no_borra_la_notificacion(self):
        """Marcarla la oculta del listado, pero sigue existiendo en memoria."""
        creada = self.crear("Conserva")
        self.client.post(f"/api/notifications/{creada['id']}/read")
        self.assertEqual(len(api._notificaciones), 1)

    def test_no_marca_a_otra_con_el_mismo_prefijo(self):
        primero = self.crear("a")
        self.crear("b")
        # Si la ruta hiciera match parcial, `a` podría alcanzar al segundo.
        self.client.post(f"/api/notifications/{primero['id']}/read")
        self.assertTrue(api._notificaciones[0].leida)
        self.assertFalse(api._notificaciones[1].leida)

    def test_ruta_sin_el_sufijo_read_no_existe(self):
        """No hay ruta `/api/notifications/{id}`: solo existe con `/read`.

        Es 404 y no 405 porque la URL en sí no corresponde a ninguna ruta,
        no porque el método esté mal.
        """
        creada = self.crear()
        self.assertEqual(self.client.post(f"/api/notifications/{creada['id']}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
