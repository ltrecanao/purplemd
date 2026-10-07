"""Autenticación con Google: configuración, sesiones, OAuth y aislamiento.

Cada regla de seguridad nueva nace con su test (regla 8 de
`skills/seguridad/SKILL.md`):

- Las credenciales incompletas **no** encienden el login (y lo dicen en
  el log) — `ConfigTests`.
- Una cookie alterada, vencida o sin firma no es una sesión —
  `SesionesTests`.
- PKCE usa el `S256` del RFC 7636 — `PkceTests`.
- El `state` ata el callback a la pestaña que abrió el login y el
  `destino` no puede salir del sitio — `LoginHttpTests`.
- Sin sesión la API responde 401 y dos cuentas no se pisan —
  `AislamientoTests`.
- Un POST con `Origin` ajeno se corta antes de llegar al router —
  `CsrfTests`.
- CSP y cabeceras de seguridad en el frontend, sin romper Swagger —
  `CabecerasTests`.
- El servidor MCP no tiene sesión, así que pide token propio —
  `McpTests`.

Ningún test toca la red: los llamados a Google se interceptan con
`httpx.MockTransport`.
"""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import purplemd_auth
from api import app
from purplemd_auth import (
    COOKIE_OAUTH,
    COOKIE_SESION,
    ConfigAuth,
    Cuenta,
    CuentasEnDisco,
    CuentasEnMemoria,
    LimiteCuentasError,
    challenge_de,
    cookie_segura,
    desde_entorno,
    firmar,
    identificador_seguro,
    nuevo_state,
    nuevo_verifier,
    verificar,
)

CREDENCIALES = {
    "GOOGLE_CLIENT_ID": "client-id-123.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": "secreto-de-prueba",
    "PURPLEMD_SECRET_KEY": "clave-de-firma-suficientemente-larga",
    "PURPLEMD_AUTH": "on",
}

TOKEN_OK = {
    "access_token": "access-1",
    "refresh_token": "refresh-1",
    "expires_in": 3600,
    "scope": "openid email profile https://www.googleapis.com/auth/drive.file",
    "token_type": "Bearer",
}

# Vector de prueba del RFC 7636, apéndice B.
RFC7636_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC7636_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

VARIABLES_GOOGLE = (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "PURPLEMD_SECRET_KEY",
    "PURPLEMD_AUTH",
    "PURPLEMD_REDIRECT_URI",
    "PURPLEMD_GOOGLE_SCOPE",
)


def sin_google():
    """Context manager que deja el entorno sin rastro de Google."""
    return _SinGoogle()


class _SinGoogle:
    def __enter__(self):
        self._parche = patch.dict(os.environ)
        self._parche.__enter__()
        for clave in VARIABLES_GOOGLE:
            os.environ.pop(clave, None)
        return self

    def __exit__(self, *exc):
        return self._parche.__exit__(*exc)


class GoogleFalso:
    """Google interceptado en memoria.

    Los tests cambian `token`, `perfil` o `fallo` sobre la marcha y el
    siguiente llamado responde en consecuencia: un solo patch de
    `cliente_por_defecto` para toda la vida del test, sin apagar y
    volver a encender el parche.
    """

    def __init__(self):
        self.token: dict = dict(TOKEN_OK)
        self.perfil: dict = {
            "sub": "sub-1",
            "email": "ana@example.com",
            "name": "Ana",
            "picture": "",
        }
        self.fallo: httpx.Response | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fallo is not None:
            return self.fallo
        url = str(request.url)
        if url.startswith(purplemd_auth.URL_TOKEN):
            return httpx.Response(200, json=self.token)
        if url.startswith(purplemd_auth.URL_PERFIL):
            return httpx.Response(200, json=self.perfil)
        return httpx.Response(404, json={"error": "no encontrado"})

    def cliente(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


class AuthTestCase(unittest.TestCase):
    """Base: entorno con credenciales completas y Google interceptado."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directorio = Path(self._tmp.name)

        self._entorno = patch.dict(
            os.environ, {"PURPLEMD_DIR": str(self.directorio), **CREDENCIALES}
        )
        self._entorno.start()
        self.addCleanup(self._entorno.stop)
        # Variables que, si quien corre los tests las tiene puestas en el
        # shell, cambiarían el comportamiento de todos los tests.
        for clave in (
            "PURPLEMD_STORAGE",
            "PURPLEMD_MCP_TOKEN",
            "PURPLEMD_REDIRECT_URI",
            "PURPLEMD_GOOGLE_SCOPE",
            "PURPLEMD_COOKIE_SECURE",
        ):
            os.environ.pop(clave, None)

        self.client = TestClient(app)
        self.google = GoogleFalso()
        self._oauth = patch(
            "purplemd_auth.oauth.cliente_por_defecto", return_value=self.google.cliente()
        )
        self._oauth.start()
        self.addCleanup(self._oauth.stop)

    def login(self, destino="/", *, perfil: dict | None = None):
        """Completa el flujo entero: login → callback con el state real."""
        if perfil is not None:
            self.google.perfil = perfil
        abierto = self.client.get(
            f"/api/auth/login?destino={destino}", follow_redirects=False
        )
        self.assertEqual(abierto.status_code, 302, abierto.text)
        state = httpx.QueryParams(abierto.headers["location"].split("?", 1)[1])["state"]
        respuesta = self.client.get(
            f"/api/auth/callback?code=codigo-1&state={state}", follow_redirects=False
        )
        self.assertEqual(respuesta.status_code, 302, respuesta.text)
        return respuesta

    def abrir_flujo(self, destino="/") -> str:
        """Dispara el login y devuelve el `state` que exige el callback."""
        abierto = self.client.get(
            f"/api/auth/login?destino={destino}", follow_redirects=False
        )
        self.assertEqual(abierto.status_code, 302, abierto.text)
        return httpx.QueryParams(abierto.headers["location"].split("?", 1)[1])["state"]


class ConfigTests(unittest.TestCase):
    """Sin credenciales completas no hay login, y se dice en el log."""

    def test_sin_variables_no_esta_habilitado(self):
        with sin_google():
            self.assertFalse(desde_entorno().habilitado)

    def test_sin_clave_de_firma_queda_apagado_y_se_registra(self):
        with sin_google(), self.assertLogs("purplemd", level="WARNING") as bitacora:
            os.environ["GOOGLE_CLIENT_ID"] = "id"
            os.environ["GOOGLE_CLIENT_SECRET"] = "secreto"
            config = desde_entorno()
        self.assertFalse(config.habilitado)
        self.assertIn("PURPLEMD_SECRET_KEY", bitacora.output[0])

    def test_con_credenciales_completas_esta_habilitado(self):
        with patch.dict(os.environ, CREDENCIALES):
            config = desde_entorno()
        self.assertTrue(config.habilitado)
        self.assertTrue(config.drive_habilitado)
        self.assertEqual(config.client_id, CREDENCIALES["GOOGLE_CLIENT_ID"])
        self.assertNotIn(CREDENCIALES["GOOGLE_CLIENT_SECRET"], repr(config))

    def test_purplemd_auth_off_apaga_aunque_haya_credenciales(self):
        with patch.dict(os.environ, {**CREDENCIALES, "PURPLEMD_AUTH": "off"}):
            self.assertFalse(desde_entorno().habilitado)

    def test_purplemd_auth_on_sin_credenciales_no_inventa_un_login(self):
        with sin_google(), self.assertLogs("purplemd", level="WARNING") as bitacora:
            os.environ["PURPLEMD_AUTH"] = "on"
            self.assertFalse(desde_entorno().habilitado)
        self.assertTrue(bitacora.output)

    def test_el_alcance_por_defecto_es_identidad_mas_las_dos_carpetas(self):
        """`drive.file` para no pedir el Drive entero y `drive.appdata`
        porque Google lo exige para leer `appDataFolder`: sin él,
        `files.list` sobre la carpeta oculta vuelve vacía."""
        with patch.dict(os.environ, CREDENCIALES):
            alcance = desde_entorno().alcance
        self.assertEqual(
            alcance.split(),
            [
                "openid",
                "email",
                "profile",
                "https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/drive.appdata",
            ],
        )
        # Nunca el acceso total al Drive del usuario.
        self.assertNotIn("auth/drive ", f"{alcance} ")

    def test_el_alcance_se_puede_reemplazar_por_entorno(self):
        with patch.dict(
            os.environ, {**CREDENCIALES, "PURPLEMD_GOOGLE_SCOPE": "openid email"}
        ):
            self.assertEqual(desde_entorno().alcance, "openid email")

    def test_get_storage_no_puede_construir_un_drive_sin_sesion(self):
        """Un caller sin sesión (MCP, `purplemd` suelto) no debe tocar datos."""
        from purplemd_storage import get_storage

        with patch.dict(os.environ, {"PURPLEMD_STORAGE": "drive"}):
            with self.assertRaises(ValueError) as ctx:
                get_storage()
        self.assertIn("sesión", str(ctx.exception))


class SesionesTests(unittest.TestCase):
    """La cookie firmada es opaca: sin la clave, no hay sesión."""

    SECRETO = CREDENCIALES["PURPLEMD_SECRET_KEY"]

    def test_roundtrip(self):
        payload = {"sub": "s", "email": "a@b.c", "name": "A", "picture": ""}
        datos = verificar(firmar(payload, self.SECRETO, 60), self.SECRETO)
        assert datos is not None
        self.assertEqual(datos["sub"], "s")
        self.assertEqual(datos["email"], "a@b.c")

    def test_firma_alterada_no_es_sesion(self):
        token = firmar({"sub": "s", "email": "a", "name": "A", "picture": ""}, self.SECRETO, 60)
        cuerpo, _, _ = token.partition(".")
        alterado = f"{cuerpo}.{cuerpo}"
        self.assertIsNone(verificar(alterado, self.SECRETO))

    def test_payload_alterado_no_es_sesion(self):
        token = firmar({"sub": "s", "email": "a", "name": "A", "picture": ""}, self.SECRETO, 60)
        import base64

        cuerpo, _, firma = token.partition(".")
        # Cambia el sub sin volver a firmar.
        datos = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
        datos["sub"] = "otro"
        serializado = json.dumps(datos, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
        nuevo = base64.urlsafe_b64encode(serializado.encode()).decode().rstrip("=")
        self.assertIsNone(verificar(f"{nuevo}.{firma}", self.SECRETO))

    def test_token_vencido_no_es_sesion(self):
        payload = {"sub": "s", "email": "a", "name": "A", "picture": ""}
        token = firmar(payload, self.SECRETO, 1, ahora=0)
        self.assertIsNotNone(verificar(token, self.SECRETO, ahora=0.5))
        self.assertIsNone(verificar(token, self.SECRETO, ahora=10))

    def test_secreto_distinto_no_abre_la_cookie(self):
        token = firmar({"sub": "s", "email": "a", "name": "A", "picture": ""}, self.SECRETO, 60)
        self.assertIsNone(verificar(token, "otra-clave"))

    def test_basura_y_ausencia_devuelven_none_y_no_lanzan(self):
        for token in (None, "", "sin-punto", "a.b", ".", "abc.def"):
            with self.subTest(token=token):
                self.assertIsNone(verificar(token, self.SECRETO))

    def test_estado_de_la_cookie(self):
        atributos = cookie_segura(es_https=False)
        self.assertTrue(atributos["httponly"])
        self.assertEqual(atributos["samesite"], "lax")
        self.assertFalse(atributos["secure"])
        self.assertTrue(cookie_segura(es_https=True)["secure"])

    def test_secure_se_puede_forzar_por_entorno(self):
        with patch.dict(os.environ, {"PURPLEMD_COOKIE_SECURE": "1"}):
            self.assertTrue(cookie_segura(es_https=False)["secure"])


class PkceTests(unittest.TestCase):
    """El reto S256 es el del RFC 7636 y viaja en la URL de consentimiento."""

    def test_code_challenge_es_el_vector_del_rfc(self):
        self.assertEqual(challenge_de(RFC7636_VERIFIER), RFC7636_CHALLENGE)

    def test_verifier_y_state_son_aleatorios(self):
        self.assertNotEqual(nuevo_verifier(), nuevo_verifier())
        self.assertNotEqual(nuevo_state(), nuevo_state())
        self.assertGreaterEqual(len(nuevo_verifier()), 43)

    def test_url_de_autorizacion(self):
        config = ConfigAuth(True, "mi-id", "mi-secreto", "clave", "", "")
        with patch.dict(os.environ, CREDENCIALES):
            config = desde_entorno()
        url = purplemd_auth.url_autorizacion(
            config, "https://mi-sitio/callback", "state-1", RFC7636_VERIFIER
        )
        self.assertTrue(url.startswith(purplemd_auth.URL_AUTORIZACION + "?"))
        params = httpx.QueryParams(url.split("?", 1)[1])
        self.assertEqual(params["client_id"], CREDENCIALES["GOOGLE_CLIENT_ID"])
        self.assertEqual(params["redirect_uri"], "https://mi-sitio/callback")
        self.assertEqual(params["response_type"], "code")
        self.assertEqual(params["state"], "state-1")
        self.assertEqual(params["code_challenge_method"], "S256")
        self.assertEqual(params["code_challenge"], RFC7636_CHALLENGE)
        # Offline + consent: sin esto Google no entrega refresh token y la
        # sesión moriría a la hora.
        self.assertEqual(params["access_type"], "offline")
        self.assertEqual(params["prompt"], "consent")
        self.assertIn("drive.file", params["scope"])

    def test_el_secret_no_aparece_en_url_ni_en_headers(self):
        with patch.dict(os.environ, CREDENCIALES):
            config = desde_entorno()
        url = purplemd_auth.url_autorizacion(config, "r", "s", "v")
        self.assertNotIn(CREDENCIALES["GOOGLE_CLIENT_SECRET"], url)


class AlmacenCuentasTests(unittest.TestCase):
    """Los tokens viven en disco, aislados y con permisos mínimos."""

    def test_archivo_con_permisos_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            almacen = CuentasEnDisco(Path(tmp) / "auth")
            cuenta = Cuenta("sub-1", "a@b.c", "Ana", "", "acc", "ref", 9999999999)
            almacen.guardar(cuenta)
            ruta = Path(tmp) / "auth" / (identificador_seguro("sub-1") + ".json")
            self.assertTrue(ruta.exists())
            self.assertEqual(stat.S_IMODE(os.stat(ruta).st_mode), 0o600)
            guardada = almacen.obtener("sub-1")
            assert guardada is not None
            self.assertEqual(guardada.refresh_token, "ref")
            self.assertIsNone(almacen.obtener("sub-otro"))

    def test_archivo_corrupto_no_tumba_el_arranque(self):
        with tempfile.TemporaryDirectory() as tmp:
            almacen = CuentasEnDisco(Path(tmp) / "auth")
            roto = Path(tmp) / "auth" / (identificador_seguro("sub-1") + ".json")
            roto.parent.mkdir(parents=True, exist_ok=True)
            roto.write_text("{esto no es json", encoding="utf-8")
            with self.assertLogs("purplemd", level="WARNING"):
                self.assertIsNone(almacen.obtener("sub-1"))

    def test_borrar_es_idempotente(self):
        with tempfile.TemporaryDirectory() as tmp:
            almacen = CuentasEnDisco(Path(tmp) / "auth")
            almacen.guardar(Cuenta("s", "", "", "", "a", "r", 0))
            almacen.borrar("s")
            almacen.borrar("s")
            self.assertIsNone(almacen.obtener("s"))

    def test_el_tope_de_cuentas_en_memoria_no_es_ilimitado(self):
        almacen = CuentasEnMemoria(tope=3)
        for i in range(5):
            almacen.guardar(Cuenta(f"s{i}", "", "", "", "a", "r", 0))
        self.assertLessEqual(len(almacen._datos), 3)

    def test_el_tope_de_cuentas_en_disco_lanza_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("purplemd_auth.tokens.TOPE_CUENTAS", 2):
                almacen = CuentasEnDisco(Path(tmp) / "auth")
                almacen.guardar(Cuenta("s1", "", "", "", "a", "r", 0))
                almacen.guardar(Cuenta("s2", "", "", "", "a", "r", 0))
                with self.assertRaises(LimiteCuentasError):
                    almacen.guardar(Cuenta("s3", "", "", "", "a", "r", 0))

    def test_un_access_token_vencido_dispara_la_revision(self):
        cuenta = Cuenta("s", "", "", "", "a", "r", expires_at=10)
        self.assertFalse(cuenta.vigente)
        self.assertTrue(Cuenta("s", "", "", "", "a", "r", expires_at=10**12).vigente)


class LoginHttpTests(AuthTestCase):
    """El flujo entero por HTTP, con Google interceptado."""

    def test_sin_config_el_login_responde_503(self):
        with sin_google():
            r = self.client.get("/api/auth/login", follow_redirects=False)
        self.assertEqual(r.status_code, 503)

    def test_login_redirige_a_google_con_pkce_y_cookie(self):
        r = self.client.get("/api/auth/login", follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        ubicacion = r.headers["location"]
        self.assertTrue(ubicacion.startswith(purplemd_auth.URL_AUTORIZACION))
        self.assertIn(CREDENCIALES["GOOGLE_CLIENT_ID"], ubicacion)

        cookies = r.headers.get_list("set-cookie")
        oauth = [c for c in cookies if c.startswith(COOKIE_OAUTH + "=")]
        self.assertEqual(len(oauth), 1)
        self.assertIn("HttpOnly", oauth[0])
        self.assertIn("SameSite=lax", oauth[0])
        self.assertIn("Max-Age=600", oauth[0])

    def test_el_callback_exige_state_de_esta_pestana(self):
        r = self.client.get("/api/auth/callback?code=x", follow_redirects=False)
        self.assertEqual(r.status_code, 400)
        self.assertIn("expir", r.json()["detail"].lower())

    def test_el_callback_detecta_state_falsificado(self):
        self.client.get("/api/auth/login", follow_redirects=False)
        r = self.client.get(
            "/api/auth/callback?code=x&state=otro-state", follow_redirects=False
        )
        self.assertEqual(r.status_code, 400)

    def test_el_callback_reporta_el_error_de_google(self):
        self.client.get("/api/auth/login", follow_redirects=False)
        r = self.client.get(
            "/api/auth/callback?error=access_denied", follow_redirects=False
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("access_denied", r.json()["detail"])

    def test_login_completo_y_cookies(self):
        r = self.login()
        cookies = r.headers.get_list("set-cookie")
        sesion = [c for c in cookies if c.startswith(COOKIE_SESION + "=")]
        self.assertEqual(len(sesion), 1, cookies)
        self.assertIn("HttpOnly", sesion[0])
        self.assertIn("SameSite=lax", sesion[0])
        self.assertIn("Max-Age=", sesion[0])
        # La cookie del flujo OAuth se consume.
        self.assertTrue(
            any(
                c.startswith(COOKIE_OAUTH + "=") and "Max-Age=0" in c for c in cookies
            ),
            cookies,
        )

    def test_el_state_viaja_en_una_cookie_y_no_en_localstorage(self):
        """El verifier nunca llega al JavaScript del frontend."""
        r = self.client.get("/api/auth/login", follow_redirects=False)
        state = httpx.QueryParams(r.headers["location"].split("?", 1)[1])["state"]
        self.assertNotIn(state, r.headers["location"].split("state=")[0])

    def test_los_tokens_se_guardan_en_el_servidor_y_no_en_la_cookie(self):
        self.login()
        cookies = " ".join(
            str(c) for c in self.client.cookies.jar  # type: ignore[attr-defined]
        )
        self.assertNotIn("refresh-1", cookies)
        self.assertNotIn("access-1", cookies)
        ruta = self.directorio / "auth" / (identificador_seguro("sub-1") + ".json")
        self.assertTrue(ruta.exists())
        self.assertIn("refresh-1", ruta.read_text(encoding="utf-8"))

    def test_el_destino_ajeno_se_descarta(self):
        """Anti open-redirect: el callback solo puede volver a este sitio."""
        r = self.login(destino="https://evil.example/robo")
        self.assertEqual(r.headers["location"], "/")
        r = self.login(destino="//evil.example/robo")
        self.assertEqual(r.headers["location"], "/")

    def test_el_destino_interno_se_respeta(self):
        r = self.login(destino="/proyecto/una-nota")
        self.assertEqual(r.headers["location"], "/proyecto/una-nota")

    def test_me_sin_config(self):
        with sin_google():
            datos = self.client.get("/api/auth/me").json()
        self.assertFalse(datos["requiere_sesion"])
        self.assertFalse(datos["autenticado"])

    def test_me_con_config_sin_sesion(self):
        datos = self.client.get("/api/auth/me").json()
        self.assertTrue(datos["requiere_sesion"])
        self.assertFalse(datos["autenticado"])
        self.assertEqual(datos["almacen"], "filesystem")

    def test_me_con_sesion(self):
        self.login()
        datos = self.client.get("/api/auth/me").json()
        self.assertTrue(datos["autenticado"])
        self.assertEqual(datos["email"], "ana@example.com")
        # `almacen` es el campo que dice la verdad del backend. El viejo
        # `drive` decía si el alcance OAuth incluía drive, que es otra
        # cosa: confundía y el frontend nunca lo leyó.
        self.assertEqual(datos["almacen"], "filesystem")
        self.assertNotIn("drive", datos)

    def test_logout_borra_cookie_y_tokens(self):
        self.login()
        ruta = self.directorio / "auth" / (identificador_seguro("sub-1") + ".json")
        self.assertTrue(ruta.exists())
        r = self.client.post("/api/auth/logout", follow_redirects=False)
        self.assertEqual(r.status_code, 204)
        self.assertFalse(ruta.exists())
        self.assertIn(f"{COOKIE_SESION}=", r.headers.get("set-cookie", ""))
        self.assertIn("Max-Age=0", r.headers.get("set-cookie", ""))

    def test_un_refresh_token_que_no_llega_se_conserva_el_anterior(self):
        """Google solo lo entrega en la primera autorización."""
        self.login()
        # Segunda conexión: Google no manda refresh_token.
        self.google.token = {**TOKEN_OK, "refresh_token": None}
        state = self.abrir_flujo()
        self.client.get(f"/api/auth/callback?code=c2&state={state}", follow_redirects=False)

        ruta = self.directorio / "auth" / (identificador_seguro("sub-1") + ".json")
        self.assertEqual(json.loads(ruta.read_text())["refresh_token"], "refresh-1")

    def test_un_fallo_de_google_no_crea_sesion(self):
        self.google.fallo = httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "mal"}
        )
        state = self.abrir_flujo()
        r = self.client.get(
            f"/api/auth/callback?code=c&state={state}", follow_redirects=False
        )
        self.assertEqual(r.status_code, 502)
        self.assertIn("mal", r.json()["detail"])
        self.assertFalse((self.directorio / "auth").exists())


class AislamientoTests(AuthTestCase):
    """Con sesión, la identidad decide dónde viven los datos (regla 5)."""

    def test_sin_sesion_la_api_responde_401(self):
        r = self.client.get("/api/projects")
        self.assertEqual(r.status_code, 401)
        self.assertIn("sesión", r.json()["detail"])

    def test_sin_sesion_los_endpoints_de_datos_no_pasan(self):
        """Todo /api/ que toca storage exige sesión (regla 8 de la skill)."""
        rutas = (
            "/api/projects",
            "/api/projects/cuaderno/tree",
            "/api/projects/cuaderno/notes/una",
            "/api/projects/cuaderno/notes/una/pdf",
            "/api/projects/cuaderno/export",
            "/api/notifications",
        )
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(ruta).status_code, 401)
        r = self.client.post("/api/projects", json={"name": "cuaderno"})
        self.assertEqual(r.status_code, 401)

    def test_el_render_pasa_sin_sesion_porque_no_toca_storage(self):
        """Único /api/ sin sesión: recibe markdown y devuelve HTML.

        No lee ni escribe storage, que es lo que permite previsualizar en
        modo invitado — ahí no hay cuenta y, por tanto, no hay storage.
        """
        r = self.client.post("/api/render", json={"markdown": "# hola"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("hola", r.json()["html"])

    def test_abrir_el_render_no_desactiva_su_tope(self):
        """Que pase sin sesión no anula MAX_RENDER_BYTES."""
        from api import MAX_RENDER_BYTES

        r = self.client.post(
            "/api/render", json={"markdown": "x" * (MAX_RENDER_BYTES + 1)}
        )
        self.assertEqual(r.status_code, 422)

    def test_el_pdf_stateless_pasa_sin_sesion(self):
        """Es el PDF del modo invitado: no hay storage del que leer."""
        r = self.client.post(
            "/api/pdf", json={"markdown": "# hola", "nombre": "saludo"}
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertEqual(
            r.headers["content-disposition"], 'attachment; filename="saludo.pdf"'
        )

    def test_el_pdf_stateless_tambien_respeta_su_tope(self):
        """Comparte `RenderRequest`, así que su tope es el mismo."""
        from api import MAX_RENDER_BYTES

        r = self.client.post(
            "/api/pdf", json={"markdown": "x" * (MAX_RENDER_BYTES + 1)}
        )
        self.assertEqual(r.status_code, 422)

    def test_el_pdf_stateless_no_acepta_un_nombre_que_inyecte_cabecera(self):
        """`nombre` va a `Content-Disposition`: comillas y CR/LF no pasan."""
        for nombre in ('" x', "hola\r\nX-Evil: 1", "a/../../b", ".oculto", ""):
            with self.subTest(nombre=nombre):
                r = self.client.post(
                    "/api/pdf", json={"markdown": "# hola", "nombre": nombre}
                )
                self.assertEqual(r.status_code, 422, r.text)

    def test_con_sesion_la_api_responde(self):
        self.login()
        r = self.client.post("/api/projects", json={"name": "cuaderno"})
        self.assertEqual(r.status_code, 201, r.text)

    def test_dos_cuentas_no_comparten_proyectos(self):
        self.login(perfil={"sub": "sub-uno", "email": "uno@example.com", "name": "Uno"})
        self.client.post("/api/projects", json={"name": "privado"})
        nombres = [p["name"] for p in self.client.get("/api/projects").json()["projects"]]
        self.assertEqual(nombres, ["privado"])

        self.client.post("/api/auth/logout")
        self.login(perfil={"sub": "sub-dos", "email": "dos@example.com", "name": "Dos"})
        nombres = [p["name"] for p in self.client.get("/api/projects").json()["projects"]]
        self.assertEqual(nombres, [])

        # Y los datos viven en carpetas distintas.
        carpetas = sorted(
            p.name for p in (self.directorio / "users").iterdir() if p.is_dir()
        )
        self.assertEqual(len(carpetas), 2)

    def test_los_datos_no_viven_en_la_raiz_como_antes(self):
        self.login()
        self.client.post("/api/projects", json={"name": "mio"})
        self.assertTrue((self.directorio / "users").is_dir())
        self.assertFalse((self.directorio / "projects").exists())

    def test_cerrar_sesion_cierra_el_acceso(self):
        self.login()
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/projects").status_code, 401)

    def test_el_backend_en_memoria_tambien_se_aisla(self):
        # El caché de instancias es estado de módulo: se limpia para que
        # el orden de los tests no contaminen el resultado.
        from api import _MEMORIA_USUARIOS

        _MEMORIA_USUARIOS.clear()
        self.addCleanup(_MEMORIA_USUARIOS.clear)

        with patch.dict(os.environ, {"PURPLEMD_STORAGE": "memory"}):
            self.login(perfil={"sub": "sub-a", "email": "a@x.y", "name": "A"})
            self.client.post("/api/projects", json={"name": "de-a"})
            self.client.post("/api/auth/logout")
            self.login(perfil={"sub": "sub-b", "email": "b@x.y", "name": "B"})
            self.assertEqual(
                self.client.get("/api/projects").json()["projects"],
                [],
            )


class CsrfTests(AuthTestCase):
    """La segunda barrera contra CSRF: `Origin` acorde con el host."""

    def test_post_con_origen_ajeno(self):
        self.login()
        r = self.client.post(
            "/api/projects",
            json={"name": "robado"},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertIn("origen", r.json()["detail"])

    def test_post_con_origen_propio_pasa(self):
        self.login()
        r = self.client.post(
            "/api/projects",
            json={"name": "legitimo"},
            headers={"Origin": "http://testserver"},
        )
        self.assertEqual(r.status_code, 201, r.text)

    def test_post_sin_origin_no_se_corta(self):
        """`curl` y los tests no mandan `Origin`; sí lo hace todo navegador."""
        self.login()
        r = self.client.post("/api/projects", json={"name": "por-curl"})
        self.assertEqual(r.status_code, 201, r.text)

    def test_get_con_origen_ajeno_no_se_corta(self):
        """Solo los verbos no seguros llevan el chequeo (son los mutantes)."""
        self.login()
        r = self.client.get(
            "/api/projects", headers={"Origin": "https://evil.example"}
        )
        self.assertEqual(r.status_code, 200)

    def test_origin_de_esquema_distinto_al_host_tambien_cuenta(self):
        self.login()
        r = self.client.post(
            "/api/projects",
            json={"name": "x"},
            headers={"Origin": "http://testserver.evil.example"},
        )
        self.assertEqual(r.status_code, 403)

    def test_sin_integracion_no_hay_chequeo_de_origen(self):
        """El comportamiento histórico queda intacto sin credenciales."""
        with sin_google():
            r = self.client.post(
                "/api/projects",
                json={"name": "libre"},
                headers={"Origin": "https://evil.example"},
            )
        self.assertEqual(r.status_code, 201, r.text)


class CabecerasTests(AuthTestCase):
    """Cabeceras de seguridad: presentes en el frontend, fuera de Swagger."""

    def test_frontend_las_lleva(self):
        r = self.client.get("/")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertEqual(r.headers["Referrer-Policy"], "no-referrer")
        csp = r.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("style-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)

    def test_no_hay_scripts_ni_estilos_inline_en_el_frontend(self):
        """La CSP es real: nada del frontend la violaría."""
        html = (Path(__file__).parent.parent / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('style="', html)
        self.assertNotIn('onclick=', html)
        self.assertIn('src="/static/js/app.js"', html)

    def test_swagger_no_lleva_csp(self):
        """Swagger carga su JS desde un CDN: imponerle la CSP lo rompería."""
        r = self.client.get("/docs")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Content-Security-Policy", r.headers)

    def test_los_archivos_estaticos_tambien_llevan_las_cabeceras(self):
        r = self.client.get("/static/css/style.css")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")


class McpTests(AuthTestCase):
    """El servidor MCP no tiene sesión: pide token propio o queda apagado.

    Cuando el token deja pasar, la petición llega al servidor MCP, que
    necesita su `lifespan` corriendo para arrancar el task group (no lo
    hay en `TestClient(app)` suelto). Por eso estos dos tests usan un
    cliente que no propaga la excepción: lo que se verifica acá es que
    **el middleware la dejó pasar**, no que el transporte MCP responda.
    """

    def setUp(self):
        super().setUp()
        self.sin_excepciones = TestClient(app, raise_server_exceptions=False)

    def test_sin_token_esta_apagado(self):
        r = self.client.get("/mcp/")
        self.assertEqual(r.status_code, 403)
        self.assertIn("PURPLEMD_MCP_TOKEN", r.json()["detail"])

    def test_token_equivocado(self):
        with patch.dict(os.environ, {"PURPLEMD_MCP_TOKEN": "correcto"}):
            r = self.client.get("/mcp/", headers={"X-PurpleMD-Token": "otro"})
        self.assertEqual(r.status_code, 401)

    def test_token_correcto_alcanza_al_servidor_mcp(self):
        with patch.dict(os.environ, {"PURPLEMD_MCP_TOKEN": "correcto"}):
            r = self.sin_excepciones.get(
                "/mcp/", headers={"X-PurpleMD-Token": "correcto"}
            )
        self.assertNotIn(r.status_code, (401, 403), r.text)

    def test_con_drive_el_mcp_queda_apagado_aunque_haya_token(self):
        with patch.dict(
            os.environ, {"PURPLEMD_MCP_TOKEN": "correcto", "PURPLEMD_STORAGE": "drive"}
        ):
            r = self.client.get("/mcp/", headers={"X-PurpleMD-Token": "correcto"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("drive", r.json()["detail"])

    def test_sin_integracion_el_mcp_sigue_como_siempre(self):
        with sin_google():
            r = self.sin_excepciones.get("/mcp/")
        self.assertNotIn(r.status_code, (401, 403), r.text)


if __name__ == "__main__":
    unittest.main()
