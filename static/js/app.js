// Frontend de PurpleMD: explorador de proyectos con carpetas, editor,
// guardado manual, descarga e importación de `.md`, previsualización en vivo
// y acciones inline para renombrar y eliminar proyectos, carpetas y notas.
//
// Capas, de arriba hacia abajo: estado, API, indicadores, proyectos,
// árbol, acciones inline, notas, preview, editor y arranque. Todas
// comparten un mismo estado, así que viven en este único módulo:
// separarlas en varios archivos obligaría a exportar casi todo sin
// ganar claridad.
//
// El markdown lo renderiza el backend (`renderer.py`): acá solo se pide
// el HTML con debounce, se cachea por hash del texto y se descartan las
// respuestas que llegan fuera de orden.

const DEBOUNCE_MS = 400;
const CACHE_MAX = 100;
// Tamaño máximo de un archivo a importar. Hay que mantenerla sincronizada
// con MAX_BYTES de `purplemd.py` (línea ~41): el backend rechaza el mismo
// tope, pero el cliente corta antes de leer ni de mandar nada.
const MAX_BYTES = 1048576;

// --------------------------------------------------------------- Namespace
/**
 * Namespace único por navegador (localStorage).
 * Persiste entre sesiones y recargas, aislando los proyectos de cada usuario
 * sin autenticación. El backend no conoce el namespace: solo ve nombres
 * prefijados, y el filtro lo hace el frontend.
 *
 * Regla de prefijos en el cliente (única fuente de verdad):
 *
 * - Lo que viene del backend se guarda CON el prefijo: `estado.proyectos`,
 *   `estado.nota.project` (se guarda tal cual responde la API) y
 *   `Accion.path` cuando la entidad es un proyecto.
 * - Lo que elige o escribe el usuario va SIN prefijo: `estado.proyectoActivo`,
 *   `Accion.proyecto` y los inputs del formulario.
 * - `nsProject()` normaliza al «con prefijo» justo antes de armar una URL de
 *   la API, y `stripNs()` normaliza al «sin prefijo» justo antes de mostrar
 *   un nombre o de compararlo con un valor de la UI.
 */

/**
 * Genera un namespace nuevo cuando todavía no hay ninguno guardado.
 *
 * `crypto.randomUUID` es un API de contexto seguro (HTTPS o `localhost`):
 * cuando la app se abre por `http://` con la IP de la red —como hace un
 * celular en la red local— no existe y esta línea lanzaría un `TypeError`
 * **antes** de registrar cualquier oyente, dejando los botones de la
 * topbar muertos. Por eso se respalda con `getRandomValues` (permitido
 * también en contextos inseguros) y, si todo falla, con `Math.random`:
 * el módulo no puede morir acá.
 *
 * @returns {string} Namespace con el formato `u_` + 8 hexadecimales.
 */
function generarNamespace() {
  try {
    if (typeof crypto.randomUUID === "function") {
      return "u_" + crypto.randomUUID().slice(0, 8);
    }
    const bytes = new Uint8Array(4);
    crypto.getRandomValues(bytes);
    return "u_" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  } catch (_) {
    return "u_" + Math.random().toString(16).slice(2, 10);
  }
}

/** Obtiene o crea el namespace del usuario en localStorage. */
function obtenerNamespace() {
  let ns = null;
  try {
    ns = localStorage.getItem("purplemd_ns");
  } catch (_) {
    // Almacenamiento bloqueado (modo privado con cookies desactivadas):
    // se genera uno nuevo y no se persiste, pero el módulo sigue vivo.
  }
  if (!ns) ns = generarNamespace();
  try {
    localStorage.setItem("purplemd_ns", ns);
  } catch (_) {
    // Sin persistencia: el namespace dura solo mientras viva la pestaña.
  }
  return ns;
}

const NAMESPACE = obtenerNamespace();
const NS_PREFIX = NAMESPACE + "_";

/**
 * Normaliza un nombre de proyecto para la API: garantía de «con prefijo».
 *
 * Es idempotente por diseño: si el valor ya viene prefijado del backend
 * (p. ej. `estado.nota.project`) se devuelve tal cual. Aplicarlo dos veces
 * sobre el mismo valor producía URLs como
 * `.../projects/u_x_u_x_proy/...`, que el backend responde con 404.
 *
 * @param {string} name - Nombre de proyecto, con o sin prefijo.
 * @returns {string} Nombre con el prefijo del namespace.
 */
function nsProject(name) {
  return name.startsWith(NS_PREFIX) ? name : NS_PREFIX + name;
}

/**
 * Quita el prefijo del namespace para mostrar al usuario.
 * También es idempotente: un nombre ya sin prefijo pasa tal cual.
 *
 * @param {string} name - Nombre de proyecto, con o sin prefijo.
 * @returns {string} Nombre sin el prefijo del namespace.
 */
function stripNs(name) {
  return name.startsWith(NS_PREFIX) ? name.slice(NS_PREFIX.length) : name;
}

/** Filtra proyectos que pertenecen a este namespace. */
function filtrarMisProyectos(proyectos) {
  return proyectos.filter(p => p.name.startsWith(NS_PREFIX));
}

// Badge visual del namespace en la topbar
function inicializarNamespaceBadge() {
  const badge = document.getElementById("namespace-badge");
  if (badge) {
    badge.textContent = `👤 ${NAMESPACE}`;
    // Mostrar en desktop (>= 60rem), ocultar en mobile
    const esDesktop = window.matchMedia("(min-width: 60rem)").matches;
    badge.hidden = !esDesktop;
  }
}

// Actualizar visibilidad del badge al redimensionar
function actualizarNamespaceBadge() {
  const badge = document.getElementById("namespace-badge");
  if (badge) {
    // Mostrar en desktop (>= 60rem) y en sidebar intermedia (>= 48rem)
    const esDesktop = window.matchMedia("(min-width: 48rem)").matches;
    badge.hidden = !esDesktop;
  }
}

// ------------------------------------------------------------------- DOM

const editor = document.getElementById("editor");
const preview = document.getElementById("preview");
const previewVacio = document.getElementById("preview-vacio");
const zona = document.getElementById("zona");
const exploradorEstado = document.getElementById("explorador-estado");
const bienvenida = document.getElementById("bienvenida");
const proyectosLista = document.getElementById("proyectos-lista");
const proyectosCantidad = document.getElementById("proyectos-cantidad");
const proyectoForm = document.getElementById("proyecto-form");
const proyectoNombre = document.getElementById("proyecto-nombre");
const proyectoEstado = document.getElementById("proyecto-estado");
const notaForm = document.getElementById("nota-form");
const notaRuta = document.getElementById("nota-ruta");
const notaEstado = document.getElementById("nota-estado");
const importarBoton = document.getElementById("importar-boton");
const importarArchivo = document.getElementById("importar-archivo");
const importarEstado = document.getElementById("importar-estado");
const arbol = document.getElementById("arbol");
const arbolVacio = document.getElementById("arbol-vacio");
const notaTitulo = document.getElementById("nota-actual");
const guardarEstado = document.getElementById("guardar-estado");
const renderEstado = document.getElementById("render-estado");
const botonGuardar = document.getElementById("guardar");
const explorador = document.getElementById("explorador");
const botonExplorador = document.getElementById("explorador-toggle");
// Contenedor de la barra superior: el corte de 48rem devuelve acá el foco
// que queda en un control recién oculto (ver `moverFocoTrasCorte`).
const accionesBarra = document.querySelector(".acciones");
const menuOverflow = document.querySelector(".menu-overflow");
const menuOverflowTrigger = document.querySelector(".menu-overflow-trigger");
const menuOverflowPanel = document.querySelector(".menu-overflow-panel");
// Ítems del grupo «Visualizador» del menú ☰: cada uno lleva `data-vista` con el
// estado que aplica (WAI-ARIA APG, patrón «Menu»: `menuitemradio` con
// `aria-checked` para una selección exclusiva, no un ciclo).
const itemsVista = [...menuOverflowPanel.querySelectorAll("[role='menuitemradio']")];
// Segmentado de visualizador de la barra (superficie ancha): radios nativos
// con el mismo `data-vista` espejo; su `checked` es el estado visible.
const radiosVista = [...document.querySelectorAll(".segmentado input[name='vista']")];
// Menú «Menú ▾» de la barra (superficie ancha): APG «Menu Button» con
// el mismo ciclo de vida que el menú ☰.
const menuAcciones = document.querySelector(".menu-acciones");
const menuAccionesTrigger = document.querySelector(".menu-acciones-trigger");
const menuAccionesPanel = document.querySelector(".menu-acciones-panel");
const importarProyectoBtn = document.getElementById("importar-proyecto");
const importarProyectoArchivo = document.getElementById("importar-proyecto-archivo");

// ---------------------------------------------------------------- Estado

/**
 * Estado compartido por todas las capas.
 * @type {{
 *   proyectos: Array<{name: string, modified: number}>,
 *   proyectoActivo: string|null,
 *   nota: {project: string, path: string, content: string, modified: number}|null,
 *   guardando: boolean,
 * }}
 */
const estado = {
  /** Proyectos recibidos de la API, del más reciente al más antiguo. */
  proyectos: [],
  /** Nombre del proyecto seleccionado; null si no hay ninguno. */
  proyectoActivo: null,
  /** Nota abierta; `content` es lo último que se guardó en disco. */
  nota: null,
  /** true mientras un PUT está en vuelo: evita guardados superpuestos. */
  guardando: false,
};

/** Markdown cuyo HTML está mostrando ahora el preview. */
let textoRenderizado = "";
/** Caché hash -> `{texto, html}`, acotada a CACHE_MAX entradas. */
const cacheRender = new Map();
let timerPreview = 0;
/** Cada renderización lo incrementa: las respuestas viejas se descartan. */
let idRender = 0;
/** Rutas de las carpetas que el usuario plegó (sobreviven al refresco). */
const carpetasColapsadas = new Set();
/** Últimas `entries` del árbol: sirven para repintar sin volver a pedirlas. */
let entradasActuales = [];

// ------------------------------------------------------------------ API

/**
 * Pide un recurso a la API y devuelve su JSON.
 * @param {string} ruta - Ruta relativa, p. ej. `/api/projects`.
 * @param {RequestInit} [opciones] - Opciones de fetch (método, body, ...).
 * @returns {Promise<any>} Cuerpo JSON de la respuesta.
 * @throws {Error} Con el detalle del backend o un mensaje de red, en español.
 */
async function pedir(ruta, opciones) {
  let respuesta;
  try {
    respuesta = await fetch(ruta, opciones);
  } catch (cause) {
    throw new Error(`no se pudo contactar al servidor (${cause.message})`);
  }
  if (!respuesta.ok) throw new Error(await detalleDeError(respuesta));
  // DELETE responde 204 sin cuerpo: no hay JSON que parsear.
  if (respuesta.status === 204) return null;
  return respuesta.json();
}

/**
 * Convierte el `detail` de FastAPI (string o lista de validación) en texto.
 * @param {Response} respuesta - Respuesta HTTP fallida.
 * @returns {Promise<string>} Mensaje legible para mostrarle al usuario.
 */
async function detalleDeError(respuesta) {
  try {
    const datos = await respuesta.json();
    if (typeof datos.detail === "string") return datos.detail;
    if (Array.isArray(datos.detail)) {
      return datos.detail.map(falloPydantic).join(" | ");
    }
  } catch (_) {
    // Respuesta sin cuerpo JSON: cae al mensaje genérico de abajo.
  }
  return `error HTTP ${respuesta.status}`;
}

/**
 * Da formato a un fallo de validación de Pydantic: `campo: mensaje`.
 * @param {{loc?: Array<string>, msg?: string}} fallo - Item de `detail`.
 * @returns {string} Texto listo para mostrar.
 */
function falloPydantic(fallo) {
  const campo = (fallo.loc || []).slice(1).join(".");
  // Pydantic antepone "Value error, " a los mensajes de nuestros validadores.
  const mensaje = String(fallo.msg || "").replace(/^Value error, /, "");
  return campo ? `${campo}: ${mensaje}` : mensaje;
}

/**
 * Arma las opciones de fetch para enviar un payload JSON.
 * @param {string} metodo - HTTP: `POST`, `PUT`, ...
 * @param {object} payload - Objeto a serializar como cuerpo.
 * @returns {RequestInit} Opciones para `fetch`.
 */
function conJson(metodo, payload) {
  return {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
}

/**
 * Codifica una ruta de nota segmento por segmento: los `/` separadores
 * tienen que llegar intactos al parámetro `{path:path}` de FastAPI, así
 * que no se escapa la ruta entera de una sola vez.
 * @param {string} ruta - Ruta lógica, p. ej. `diseños/logo`.
 * @returns {string} Ruta lista para pegar en la URL.
 */
function rutaUrl(ruta) {
  return ruta.split("/").map(encodeURIComponent).join("/");
}

/**
 * Último segmento de una ruta.
 * @param {string} ruta - Ruta lógica, p. ej. `diseños/logo`.
 * @returns {string} `logo`.
 */
function ultimoSegmento(ruta) {
  const indice = ruta.lastIndexOf("/");
  return indice === -1 ? ruta : ruta.slice(indice + 1);
}

/**
 * Carpeta que contiene una ruta (sin barra final).
 * @param {string} ruta - Ruta lógica, p. ej. `diseños/logo`.
 * @returns {string} `diseños`, o `""` si la ruta está en la raíz.
 */
function carpetaContenedora(ruta) {
  const indice = ruta.lastIndexOf("/");
  return indice === -1 ? "" : ruta.slice(0, indice);
}

// ---------------------------------------------------------- Indicadores

/**
 * Pinta un indicador de estado (guardado, render, errores).
 * @param {HTMLElement} elemento - `<p role="status">` a actualizar.
 * @param {"ok"|"error"|"trabajando"|""} clase - Tono del mensaje.
 * @param {string} texto - Mensaje visible en español.
 */
function pintarEstado(elemento, clase, texto) {
  // Solo se cambia la clase de tono: la lista conserva sus clases fijas
  // (p. ej. `estado-lista`, que alinea el mensaje a la izquierda).
  elemento.classList.remove("ok", "error", "trabajando");
  if (clase) elemento.classList.add(clase);
  elemento.textContent = texto;
}

/** ¿El editor difiere de lo último que se guardó? */
function hayCambios() {
  return estado.nota !== null && editor.value !== estado.nota.content;
}

/**
 * Sincroniza solo el botón «Guardar»: se le puede llamar sin tocar el
 * texto del indicador (p. ej. para conservar un error recién pintado).
 * De paso refresca la fila de importación, que comparte sus
 * disparadores: cada cambio de `hayCambios` (tecla, apertura y cierre
 * de nota, guardado).
 */
function refrescarBotonGuardar() {
  botonGuardar.disabled = estado.nota === null || estado.guardando || !hayCambios();
  refrescarImportacion();
}

/**
 * Sincroniza la fila única de importación del explorador (`.md` y `.zip`):
 * los dos botones comparten la misma regla —proyecto activo y ninguna
 * modificación sin guardar—, la misma que crear una nota (que además lo
 * vuelve a comprobar al enviar, porque el estado puede cambiar mientras
 * el archivo se lee). La fila no se oculta nunca: sin proyecto los dos
 * quedan deshabilitados. Se llama desde `refrescarBotonGuardar` y desde
 * `refrescarHabilitacion` (cambios de proyecto y de nota abierta).
 */
function refrescarImportacion() {
  const bloqueado = estado.proyectoActivo === null || hayCambios();
  importarBoton.disabled = bloqueado;
  importarProyectoBtn.disabled = bloqueado;
}

/**
 * Sincroniza el indicador de guardado y el botón.
 * Mientras hay un PUT en vuelo no toca el texto: mantiene «Guardando…».
 */
function refrescarGuardado() {
  refrescarBotonGuardar();
  if (estado.guardando) return;
  if (!estado.nota) pintarEstado(guardarEstado, "", "Sin nota abierta");
  else if (hayCambios()) pintarEstado(guardarEstado, "", "Cambios sin guardar");
  else pintarEstado(guardarEstado, "", "Sin cambios");
}

/**
 * Habilita o deshabilita una acción en TODAS las superficies que la
 * ofrecen: cada control lleva `data-accion` y los dos juegos (menú ☰ en
 * `<48rem` y menú «Menú ▾» de la barra en `>=48rem`) se pintan juntos,
 * con una sola regla.
 * @param {"descargar"|"pdf"|"zip"} accion - Valor de `data-accion`.
 * @param {boolean} habilitar - true para habilitar.
 */
function habilitarAccion(accion, habilitar) {
  for (const control of document.querySelectorAll(`[data-accion="${accion}"]`)) {
    control.disabled = !habilitar;
  }
}

/**
 * Refleja en la interfaz si se puede escribir: solo con una nota abierta,
 * porque markdown que no se puede guardar no debería escribirse.
 * También actualiza los textos de ayuda que explican por qué está apagado.
 */
function refrescarHabilitacion() {
  const conNota = estado.nota !== null;
  const conProyecto = estado.proyectoActivo !== null;
  editor.disabled = !conNota;
  // Habilitación espejo (invariante): «Descargar .md» y «Exportar .pdf»
  // requieren nota abierta; «Exportar .zip», proyecto activo. Los dos
  // juegos quedan con el mismo `disabled`.
  habilitarAccion("descargar", conNota);
  habilitarAccion("pdf", conNota);
  habilitarAccion("zip", conProyecto);
  // El trigger «Menú» se apaga cuando no hay nada que exportar (ni nota
  // ni proyecto), para no abrir un menú con las exportaciones apagadas.
  // El menú ☰ nunca se deshabilita: contiene el grupo «Vista», siempre
  // disponible.
  const exportarApagado = !conNota && !conProyecto;
  menuAccionesTrigger.disabled = exportarApagado;
  if (exportarApagado) cerrarMenuAcciones();
  notaForm.hidden = !conProyecto;
  // Mismo sitio donde se habilita `#nota-ruta`: la fila de importación
  // depende del proyecto activo, que es lo que cambia acá.
  refrescarImportacion();
  editor.placeholder = mensajeParaEditor();
  if (conNota) {
    previewVacio.hidden = true;
    return;
  }
  // Sin nota no queda HTML de una nota anterior en pantalla.
  previewVacio.hidden = false;
  previewVacio.textContent = mensajePreviewVacio();
  preview.replaceChildren();
  textoRenderizado = "";
}

/**
 * Texto de ayuda del textarea según lo que haya disponible.
 * @returns {string} Placeholder en español.
 */
function mensajeParaEditor() {
  if (estado.nota) return "Escribí el markdown de la nota acá.";
  if (!estado.proyectos.length) return "Creá tu primer proyecto para empezar a escribir.";
  if (!estado.proyectoActivo) return "Seleccioná un proyecto para empezar a escribir.";
  return "Creá o abrí una nota para empezar a escribir.";
}

/**
 * Mensaje del panel de previsualización cuando no hay nota abierta.
 * @returns {string} Texto en español.
 */
function mensajePreviewVacio() {
  if (estado.proyectos.length) return "La previsualización aparecerá acá cuando abras una nota.";
  return "La previsualización aparecerá acá cuando crees un proyecto y abras una nota.";
}

// ------------------------------------------------------------ Proyectos

/**
 * Carga (o recarga) los proyectos y repinta el explorador.
 * @returns {Promise<Array<{name: string, modified: number}>>} Proyectos
 *   recibidos; vacío si falló (el error queda pintado en el explorador).
 */
async function cargarProyectos() {
  try {
    const datos = await pedir("/api/projects");
    // Filtrar solo los proyectos de este namespace
    const misProyectos = filtrarMisProyectos(datos.projects);
    // Guardar con nombres originales (prefijados) para operaciones API
    estado.proyectos = misProyectos;
    // Pero mostrar sin prefijo en la UI
    pintarProyectos();
    pintarEstado(exploradorEstado, "", "");
    return misProyectos;
  } catch (error) {
    // No se afirma «no hay proyectos» con una lectura fallida: se limpia
    // la lista y el error queda visible en su indicador.
    estado.proyectos = [];
    proyectosLista.replaceChildren();
    proyectosLista.hidden = true;
    proyectosCantidad.textContent = "";
    bienvenida.hidden = true;
    pintarEstado(exploradorEstado, "error", `No se pudieron cargar los proyectos: ${error.message}`);
    return [];
  }
}

/**
 * Dibuja la lista de proyectos y actualiza el resto del explorador.
 * Si el proyecto activo ya no está en la lista, vuelve al estado sin
 * selección (sucede si se borró el directorio desde fuera de la app).
 */
function pintarProyectos() {
  const focoPrevio = document.activeElement instanceof Element ? document.activeElement : null;
  // estado.proyectoActivo se guarda SIN prefijo para la UI
  const sigueActivo = estado.proyectos.some((proyecto) => stripNs(proyecto.name) === estado.proyectoActivo);
  if (estado.proyectoActivo && !sigueActivo) deseleccionarProyecto();
  proyectosLista.replaceChildren(...estado.proyectos.map(filaProyecto));
  proyectosLista.hidden = estado.proyectos.length === 0;
  proyectosCantidad.textContent = estado.proyectos.length ? String(estado.proyectos.length) : "";
  bienvenida.hidden = estado.proyectos.length > 0;
  marcarProyectoActivo();
  refrescarHabilitacion();
  restaurarFocoAccion(focoPrevio);
  // El panel (si esta lista es la que lo contiene) se insertó recién sin
  // ubicar: su esquina sale del rectángulo de la fila que lo abrió.
  ubicarPanel();
}

/**
 * Arma la fila de un proyecto. El nombre va por `textContent`, nunca por
 * innerHTML: son datos del usuario y no debe interpretarse como marcado.
 * @param {{name: string, modified: number}} proyecto - Resumen de la API.
 * @returns {HTMLElement} `<li>` con nombre y fecha del proyecto.
 */
function filaProyecto(proyecto) {
  const item = document.createElement("li");
  // Claves para volver a la fila desde `filaDe` (foco tras una operación).
  // Guardamos el nombre CON prefijo para operaciones API
  item.dataset.tipo = "proyecto";
  item.dataset.ruta = proyecto.name;

  const boton = document.createElement("button");
  boton.type = "button";
  boton.className = "proyecto";

  const nombre = document.createElement("span");
  nombre.className = "proyecto-nombre";
  // Mostrar SIN prefijo
  nombre.textContent = stripNs(proyecto.name);

  const fecha = document.createElement("time");
  fecha.className = "proyecto-fecha";
  fecha.dateTime = new Date(proyecto.modified * 1000).toISOString();
  fecha.textContent = formatearFecha(proyecto.modified);

  boton.append(nombre, fecha);
  // Pasar SIN prefijo a seleccionarProyecto (UI usa nombres sin prefijo)
  boton.addEventListener("click", () => seleccionarProyecto(stripNs(proyecto.name)));

  const fila = document.createElement("div");
  fila.className = "fila";
  fila.append(
    boton,
    crearAcciones(`el proyecto ${stripNs(proyecto.name)}`, {
      renombrar: () => abrirAccion("proyecto", "renombrar", proyecto.name),
      eliminar: () => abrirAccion("proyecto", "eliminar", proyecto.name),
    }),
  );

  item.append(fila);
  const panel = panelPara("proyecto", proyecto.name);
  if (panel) item.append(panel);
  return item;
}

/**
 * Marca en la lista el proyecto seleccionado con `aria-current`.
 * Compara contra `estado.proyectoActivo` para que sirva también tras
 * refrescar la lista, sin volver a renderizarla (así no se pierde el foco).
 */
function marcarProyectoActivo() {
  for (const boton of proyectosLista.querySelectorAll(".proyecto")) {
    const nombre = boton.querySelector(".proyecto-nombre").textContent;
    if (nombre === estado.proyectoActivo) {
      boton.setAttribute("aria-current", "true");
    } else {
      boton.removeAttribute("aria-current");
    }
  }
}

/**
 * Selecciona un proyecto y carga su árbol de carpetas y notas.
 * Con cambios sin guardar no cambia de proyecto: la nota abierta vive en
 * el anterior y esos cambios se perderían.
 * @param {string} nombre - Nombre del proyecto SIN prefijo (para UI).
 * @returns {Promise<boolean>} Si el proyecto quedó seleccionado.
 */
async function seleccionarProyecto(nombre) {
  if (estado.proyectoActivo === nombre) return true;
  if (hayCambios()) {
    // El bloqueo es un error: vive en el indicador del explorador, que es
    // la superficie que recibió el clic. `#guardar-estado` queda exclusivo
    // del estado de guardado.
    pintarEstado(
      exploradorEstado,
      "error",
      "Tenés cambios sin guardados: guardá antes de cambiar de proyecto.",
    );
    return false;
  }

  // UI guarda SIN prefijo
  estado.proyectoActivo = nombre;
  // La acción abierta (si la hay) pertenecía a la lista anterior: se quita
  // su panel del DOM sin repintar, para no perder el foco en la fila.
  cerrarAccion();
  // La nota abierta pertenecía al proyecto anterior: se cierra.
  cerrarNota();
  marcarProyectoActivo();
  // API necesita CON prefijo
  await cargarArbol(nsProject(nombre));
  // Cambiar de proyecto NO cierra el desplegable: el usuario quiere ver el
  // árbol del nuevo proyecto. Al abrir una nota sí se cierra (ver abrirNota).
  return true;
}

/**
 * Vuelve al estado «sin nota abierta»: editor vacío, título genérico y
 * preview limpio (lo limpia `refrescarHabilitacion`).
 * No toca la selección de proyecto.
 */
function cerrarNota() {
  estado.nota = null;
  editor.value = "";
  notaTitulo.textContent = "Sin nota abierta";
  refrescarGuardado();
  refrescarHabilitacion();
}

/**
 * Vuelve al estado sin proyecto seleccionado. Solo se usa cuando el
 * proyecto activo desapareció del listado: en ese caso la nota abierta
 * tampoco existe, así que no hay nada que guardar.
 */
function deseleccionarProyecto() {
  estado.proyectoActivo = null;
  // El panel de acción apuntaba a entradas que ya no están.
  cerrarAccion();
  entradasActuales = [];
  cerrarNota();
  arbol.replaceChildren();
  arbolVacio.hidden = true;
}

/**
 * Fecha legible de un epoch en segundos.
 * @param {number} epoch - Segundos desde el epoch (formato del backend).
 * @returns {string} Fecha y hora en español.
 */
function formatearFecha(epoch) {
  return new Date(epoch * 1000).toLocaleString("es", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

// ---------------------------------------------------------------- Árbol

/**
 * Pide el árbol del proyecto indicado y lo repinta.
 * @param {string} proyecto - Nombre del proyecto CON prefijo (para API).
 */
async function cargarArbol(proyecto) {
  try {
    const datos = await pedir(`/api/projects/${encodeURIComponent(proyecto)}/tree`);
    // Comparar con el proyecto activo SIN prefijo (estado.proyectoActivo no tiene prefijo)
    if (estado.proyectoActivo !== stripNs(proyecto)) return; // ya se cambió de proyecto
    entradasActuales = datos.entries;
    pintarArbol(datos.entries);
    pintarEstado(exploradorEstado, "", "");
  } catch (error) {
    if (estado.proyectoActivo !== stripNs(proyecto)) return;
    entradasActuales = [];
    arbol.replaceChildren();
    arbolVacio.hidden = true;
    pintarEstado(exploradorEstado, "error", `No se pudo cargar el árbol: ${error.message}`);
  }
}

/**
 * Organiza la lista plana del backend en un árbol anidado.
 *
 * El backend manda primero todas las carpetas y después todas las notas,
 * cada grupo en orden alfabético; como una carpeta siempre precede a sus
 * hijas ("alpha" antes que "alpha/sub"), alcanza con dos pasadas: una
 * para crear las carpetas y otra para colgar cada nota en la suya.
 *
 * @param {Array<{type: string, path: string, modified: number}>} entradas - `entries` del árbol.
 * @returns {Array<Object>} Nodos raíz, con `{tipo, path, nombre, ...}`.
 */
function construirArbol(entradas) {
  /** @type {Map<string, Object>} Carpeta por su ruta, para colgar hijas. */
  const carpetas = new Map();
  /** @type {Array<Object>} Contenido de la raíz del proyecto. */
  const raiz = [];

  for (const entrada of entradas) {
    if (entrada.type !== "dir") continue;
    const nodo = {
      tipo: "carpeta",
      path: entrada.path,
      nombre: ultimoSegmento(entrada.path),
      hijos: [],
      modified: entrada.modified,
    };
    carpetas.set(entrada.path, nodo);
    const contenedora = carpetas.get(carpetaContenedora(entrada.path));
    (contenedora ? contenedora.hijos : raiz).push(nodo);
  }

  for (const entrada of entradas) {
    if (entrada.type !== "note") continue;
    const nodo = {
      tipo: "nota",
      path: entrada.path,
      nombre: ultimoSegmento(entrada.path),
      modified: entrada.modified,
    };
    const contenedora = carpetas.get(carpetaContenedora(entrada.path));
    (contenedora ? contenedora.hijos : raiz).push(nodo);
  }

  return raiz;
}

/**
 * Repinta el árbol completo del proyecto activo.
 * @param {Array<{type: string, path: string, modified: number}>} entradas - `entries` del árbol.
 */
function pintarArbol(entradas) {
  const focoPrevio = document.activeElement instanceof Element ? document.activeElement : null;
  const nodos = construirArbol(entradas);
  arbol.replaceChildren(...nodos.map(pintarNodo));
  arbolVacio.hidden = nodos.length > 0;
  marcarNotaActiva();
  restaurarFocoAccion(focoPrevio);
  // Igual que en `pintarProyectos`: el panel reinsertado se ubica recién
  // acá, cuando su fila ya está en el DOM con su rectángulo definitivo.
  ubicarPanel();
}

/**
 * Crea el elemento de una entrada del árbol.
 * @param {{tipo: string}} nodo - Nodo devuelto por `construirArbol`.
 * @returns {HTMLElement} `<li>` con la carpeta o la nota.
 */
function pintarNodo(nodo) {
  return nodo.tipo === "carpeta" ? pintarCarpeta(nodo) : pintarNota(nodo);
}

/**
 * Crea una carpeta plegable con `<details>`: el plegado es nativo, se
 * opera con el teclado y el estado va en `aria-expanded` sin JS extra.
 * @param {Object} nodo - Carpeta con sus hijos.
 * @returns {HTMLElement} `<li>` con el resumen y la lista anidada.
 */
function pintarCarpeta(nodo) {
  const item = document.createElement("li");
  item.className = "carpeta";
  item.dataset.tipo = "carpeta";
  item.dataset.ruta = nodo.path;

  const detalles = document.createElement("details");
  detalles.open = !carpetasColapsadas.has(nodo.path);

  const resumen = document.createElement("summary");
  resumen.textContent = nodo.nombre;
  resumen.title = nodo.path;

  const hijos = document.createElement("ul");
  hijos.replaceChildren(...nodo.hijos.map(pintarNodo));

  detalles.addEventListener("toggle", () => {
    if (detalles.open) carpetasColapsadas.delete(nodo.path);
    else carpetasColapsadas.add(nodo.path);
  });
  detalles.append(resumen, hijos);

  // Las acciones van fuera de `<summary>`: al pulsar un hijo interactivo
  // del resumen se abriría o cerraría la carpeta junto con el clic.
  const fila = document.createElement("div");
  fila.className = "fila";
  fila.append(
    detalles,
    crearAcciones(`la carpeta ${nodo.path}`, {
      renombrar: () => abrirAccion("carpeta", "renombrar", nodo.path),
      eliminar: () => abrirAccion("carpeta", "eliminar", nodo.path),
    }),
  );

  item.append(fila);
  const panel = panelPara("carpeta", nodo.path);
  if (panel) item.append(panel);
  return item;
}

/**
 * Crea la entrada de una nota del árbol.
 * @param {Object} nodo - Nota con su ruta y fecha.
 * @returns {HTMLElement} `<li>` con el botón que la abre.
 */
function pintarNota(nodo) {
  const item = document.createElement("li");
  item.className = "entrada";
  item.dataset.tipo = "nota";
  item.dataset.ruta = nodo.path;

  const boton = document.createElement("button");
  boton.type = "button";
  boton.className = "entrada-nota";
  boton.dataset.ruta = nodo.path;
  boton.textContent = nodo.nombre;
  // El nombre visible es solo el último segmento: la ruta completa va al
  // tooltip y a la etiqueta accesible, donde no se corta.
  boton.title = nodo.path;
  boton.setAttribute("aria-label", `Abrir la nota ${nodo.path}`);
  boton.addEventListener("click", () => abrirNota(nodo.path));

  const fila = document.createElement("div");
  fila.className = "fila";
  fila.append(
    boton,
    crearAcciones(`la nota ${nodo.path}`, {
      renombrar: () => abrirAccion("nota", "renombrar", nodo.path),
      eliminar: () => abrirAccion("nota", "eliminar", nodo.path),
    }),
  );

  item.append(fila);
  const panel = panelPara("nota", nodo.path);
  if (panel) item.append(panel);
  return item;
}

/**
 * Marca la nota abierta en el árbol con `aria-current`.
 * Compara contra `estado.nota` para que sirva también tras refrescar.
 */
function marcarNotaActiva() {
  for (const boton of arbol.querySelectorAll(".entrada-nota")) {
    const activa = estado.nota !== null && boton.dataset.ruta === estado.nota.path;
    if (activa) boton.setAttribute("aria-current", "true");
    else boton.removeAttribute("aria-current");
  }
}

// ------------------------------------------ Acciones inline: editar y borrar

/**
 * Acción inline abierta (renombrar o eliminar). Solo puede haber una:
 * abrir otra cierra la anterior. `valor` guarda el contenido actual del
 * input (se actualiza mientras se escribe) para sobrevivir a los
 * repintados de fondo, `enVuelo` bloquea cambios mientras el request está
 * en curso y `proyecto` guarda el proyecto en el que se abre, que puede
 * no ser el activo. `path` es siempre el valor original de la entidad.
 *
 * @typedef {{
 *   tipo: "proyecto"|"nota"|"carpeta",
 *   modo: "renombrar"|"eliminar",
 *   proyecto: string|null,
 *   path: string,
 *   valor: string,
 *   enVuelo: boolean,
 * }} Accion
 */

/** @type {Accion|null} */
let accion = null;

// ------------------------------------------------ Apertura y cierre

/**
 * Abre la acción indicada, repinta las listas (ahí se cuelga el panel)
 * y lleva el foco al campo del panel recién creado.
 * @param {"proyecto"|"nota"|"carpeta"} tipo - Entrada a editar.
 * @param {"renombrar"|"eliminar"} modo - Acción a realizar.
 * @param {string} path - Clave interna de la entrada: nombre CON prefijo en
 *   proyectos, ruta en notas y carpetas. Al renombrar un proyecto el input
 *   arranca sin prefijo (es entrada del usuario, ver regla de namespace).
 */
function abrirAccion(tipo, modo, path) {
  // Con un request en vuelo no se cambia de panel: se pisaría su resultado.
  if (accion && accion.enVuelo) return;
  // Las notas y carpetas solo existen dentro de un proyecto seleccionado.
  if (tipo !== "proyecto" && !estado.proyectoActivo) return;
  // `path` es la clave interna (CON prefijo para proyectos, para casar con
  // `dataset.ruta` de la fila), pero el input de renombrar es entrada del
  // usuario: se abre sin prefijo y se vuelve a agregar al confirmar.
  const valorInicial = tipo === "proyecto" ? stripNs(path) : path;
  accion = { tipo, modo, proyecto: estado.proyectoActivo, path, valor: valorInicial, enVuelo: false };
  repintarListas();
  enfocarAccion(null);
}

/**
 * Quita la acción abierta y su panel del DOM. No repinta las listas:
 * sus filas no cambian, porque los botones de acción siempre están.
 */
function cerrarAccion() {
  accion = null;
  const panel = document.querySelector("[data-accion-panel]");
  if (panel) panel.remove();
}

/**
 * Botones de acción de la propia fila, excluyendo los de las entradas
 * anidadas: una carpeta lleva adentro las filas de sus hijas, así que hay
 * que buscar colgando directo de `.fila` y no de todo el `<li>`.
 * @param {HTMLElement} fila - `<li>` de la entrada.
 * @returns {NodeList} Botones de acción, renombrar primero y eliminar después.
 */
function botonesDeFila(fila) {
  return fila.querySelectorAll(":scope > .fila > .fila-acciones > .btn-mini");
}

/**
 * Cancela la acción (botón «Cancelar» o Escape) y devuelve el foco al
 * botón que la abrió, para que el foco no caiga en el body.
 */
function cancelarAccion() {
  if (!accion || accion.enVuelo) return;
  const { tipo, path, modo } = accion;
  cerrarAccion();
  const fila = filaDe(tipo, path);
  if (!fila) return;
  const botones = botonesDeFila(fila);
  const objetivo = botones[modo === "renombrar" ? 0 : 1];
  if (objetivo) objetivo.focus();
}

/**
 * Repinta proyectos y árbol, que es donde pueden vivir paneles de acción.
 * Se usa al cambiar de acción abierta; los refresco de fondo repintan por
 * su cuenta y el panel se reconstruye desde `accion`.
 */
function repintarListas() {
  pintarProyectos();
  if (estado.proyectoActivo) pintarArbol(entradasActuales);
}

/**
 * Devuelve el foco al panel de la acción después de un repintado: el
 * control que lo tenía dejó de existir con el DOM viejo.
 * @param {Element|null} focoPrevio - `document.activeElement` antes del repintado.
 */
function restaurarFocoAccion(focoPrevio) {
  if (!accion || !focoPrevio) return;
  if (!focoPrevio.closest("[data-accion-panel]")) return;
  enfocarAccion(focoPrevio);
}

/**
 * Pone el foco en un control del panel abierto: el que tenía el foco
 * (`anterior`), el marcado como principal (el input al renombrar y el
 * botón de confirmación al eliminar; el orden visual pone «Cancelar»
 * primero, así que sin este marcador el foco caería en él) o, si no,
 * el primero del panel.
 * @param {Element|null} anterior - Control del panel anterior, o null.
 */
function enfocarAccion(anterior) {
  const panel = document.querySelector("[data-accion-panel]");
  if (!panel) return;
  const controles = [...panel.querySelectorAll("input, button")];
  const mismo =
    anterior &&
    controles.find((c) => c.tagName === anterior.tagName && c.textContent === anterior.textContent);
  const destino = mismo || panel.querySelector("[data-principal]") || controles[0];
  if (!destino) return;
  destino.focus();
  // Se selecciona todo solo al abrir, para que escribir reemplace el valor;
  // tras un repintado se respeta el cursor de quien venía escribiendo.
  if (destino instanceof HTMLInputElement && (!anterior || anterior.tagName !== "INPUT")) {
    destino.select();
  }
}

/**
 * Foco después de una operación exitosa: a la fila que quedó (si existe)
 * o, si la entrada se eliminó, al indicador del explorador (no al body).
 * @param {"proyecto"|"nota"|"carpeta"} tipo - Entrada que se operó.
 * @param {string} path - Ruta o nombre de la entrada.
 */
function enfocarTrasOperacion(tipo, path) {
  const fila = filaDe(tipo, path);
  const principal = fila && fila.querySelector(".proyecto, .entrada-nota, summary");
  if (principal) principal.focus();
  else exploradorEstado.focus();
}

/**
 * Fila del explorador que corresponde a una entrada.
 * @param {"proyecto"|"nota"|"carpeta"} tipo - Entidad.
 * @param {string} path - Nombre o ruta.
 * @returns {HTMLElement|null} `<li>` de la entrada, o null si ya no está.
 */
function filaDe(tipo, path) {
  for (const item of document.querySelectorAll("[data-tipo]")) {
    if (item.dataset.tipo === tipo && item.dataset.ruta === path) return item;
  }
  return null;
}

// -------------------------------------------------- Paneles de acción

/**
 * Botones «renombrar» y «eliminar» de una fila. Van como hermanos del
 * botón de la entrada: no se anidan controles interactivos dentro de un
 * `<button>` ni de un `<summary>` (al pulsar el resumen se alternaría la
 * carpeta junto con la acción).
 * @param {string} descripcion - Base del nombre accesible, p. ej. `la nota diseños/logo`.
 * @param {{renombrar: () => void, eliminar: () => void}} alPulsar - Aperturas.
 * @returns {HTMLElement} `<span>` con ambos botones.
 */
function crearAcciones(descripcion, alPulsar) {
  const caja = document.createElement("span");
  caja.className = "fila-acciones";
  caja.append(
    botonAccion("✎", `Renombrar ${descripcion}`, alPulsar.renombrar),
    botonAccion("✕", `Eliminar ${descripcion}`, alPulsar.eliminar),
  );
  return caja;
}

/**
 * Botón de acción con símbolo visible y nombre accesible completo.
 * @param {string} simbolo - Carácter que se muestra (decorativo).
 * @param {string} etiqueta - Nombre accesible y tooltip.
 * @param {() => void} alPulsar - Apertura de la acción.
 * @returns {HTMLElement} `<button>` listo.
 */
function botonAccion(simbolo, etiqueta, alPulsar) {
  const boton = document.createElement("button");
  boton.type = "button";
  boton.className = "btn-mini";
  boton.title = etiqueta;

  const visible = document.createElement("span");
  visible.setAttribute("aria-hidden", "true");
  visible.textContent = simbolo;

  const accesible = document.createElement("span");
  accesible.className = "solo-lectores";
  accesible.textContent = etiqueta;

  boton.append(visible, accesible);
  boton.addEventListener("click", alPulsar);
  return boton;
}

/**
 * Panel de la acción abierta si corresponde a esa entrada.
 * @param {"proyecto"|"nota"|"carpeta"} tipo - Entidad de la fila.
 * @param {string} path - Ruta o nombre de la fila.
 * @returns {HTMLElement|null} Panel a colgar debajo de la fila.
 */
function panelPara(tipo, path) {
  if (!accion || accion.tipo !== tipo || accion.path !== path) return null;
  return crearPanelAccion(accion);
}

/**
 * Arma el panel inline de la acción: formulario para renombrar o
 * confirmación explícita para eliminar (nunca `alert()` ni `confirm()`).
 * Reutiliza las clases `crear` del explorador para heredar los estilos
 * de input, botones e indicador. El panel se inserta en la fila (así el
 * estado `accion` y el refresco siguen igual) y `ubicarPanel()` lo deja
 * superpuesto sobre la columna.
 * @param {Accion} a - Acción abierta.
 * @returns {HTMLElement} `<form>` al renombrar, `<div>` al eliminar.
 */
function crearPanelAccion(a) {
  const config = descripcionAccion(a);
  const panel = document.createElement(a.modo === "renombrar" ? "form" : "div");
  panel.className = "crear accion";
  panel.dataset.accionPanel = "1";

  if (a.modo === "renombrar") armarRenombrar(panel, config, a);
  else armarEliminar(panel, config);

  // Escape cierra la acción mientras no haya un request en curso.
  panel.addEventListener("keydown", (evento) => {
    siEscapeCancela(evento, a);
  });

  if (a.enVuelo) {
    // Un repintado en medio de la operación reconstruye el panel: hay que
    // volver a dejarlo inoperable hasta que llegue la respuesta.
    habilitarPanel(panel, false);
    pintarEstado(panel.querySelector(".estado"), "trabajando", "Aplicando…");
  }
  return panel;
}

// ------------------------------------- Ubicación del panel superpuesto

/** Hueco (px) que el panel deja entre su fila y su propio borde. */
const HUECO_PANEL = 4;

/** Margen (px) que el panel respeta respecto del borde del lienzo. */
const MARGEN_LIENZO = 8;

/**
 * Superpone el panel de la acción sobre la columna que lo limitaba.
 *
 * El panel sigue siendo hijo de la fila que lo abre: el estado `accion`,
 * el refresco desde estado y la devolución de foco no cambian. Lo que
 * cambia es que se dibuja `fixed` respecto del viewport, así que el ancho
 * de la columna del explorador no le roba lugar y una ruta larga entra
 * entera. La esquina sale del rectángulo de la fila, el `max-width` del
 * CSS la recorta contra el borde derecho del lienzo y, en vertical, se
 * queda dentro de la columna visible del explorador: así la caja tapa la
 * columna que la limitaba y no estorba el editor ni la vista previa.
 *
 * Hay que volver a llamarla cuando algo puede mover a la fila: cada
 * repintado (ahí se inserta el panel), scroll, resize y plegado.
 */
function ubicarPanel() {
  if (!accion) return;
  const panel = document.querySelector("[data-accion-panel]");
  if (!panel) return;
  const fila = filaDe(accion.tipo, accion.path);
  const ancla = fila && fila.querySelector(":scope > .fila");
  // Sin fila renderizada (carpeta plegada, refresco a medias) no hay
  // rectángulo que seguir: el panel está oculto con su contenido.
  if (!ancla) return;
  const rect = ancla.getBoundingClientRect();
  if (!rect.height) return;

  // Primero la izquierda: el ancho máximo depende de `left` y, con ese
  // ancho, del alto con el que se calcula el repliegue vertical. Si la
  // fila quedó corrida fuera del borde (árbol con scroll horizontal por un
  // proyecto muy anidado), la caja arranca igual dentro del lienzo.
  const izq = Math.max(rect.left, MARGEN_LIENZO);
  panel.style.setProperty("--accion-izq", `${izq}px`);

  const alto = panel.offsetHeight;
  const limiteAbajo = document.documentElement.clientHeight - MARGEN_LIENZO;

  // Límites verticales: primero contra la columna visible del explorador,
  // que es el sitio de la caja (tapa la columna que la limitaba y no el
  // resto del programa). El lienzo queda como tope duro para el caso en
  // que la columna no le dé abasto.
  const explorador = ancla.closest(".panel-explorador");
  const columna = explorador ? explorador.getBoundingClientRect() : null;
  let desde = MARGEN_LIENZO;
  let hasta = limiteAbajo;
  if (columna) {
    const colDesde = Math.max(MARGEN_LIENZO, columna.top + MARGEN_LIENZO);
    const colHasta = Math.min(limiteAbajo, columna.bottom - MARGEN_LIENZO);
    // Columna más baja que la caja (ventana angosta con la caja alta):
    // se vuelve a los límites del lienzo y la caja pisa lo que haya.
    if (colHasta - colDesde >= alto) {
      desde = colDesde;
      hasta = colHasta;
    }
  }

  let top = rect.bottom + HUECO_PANEL;
  if (top + alto > hasta) {
    // No entra debajo de la fila: se cuelga arriba si ahí entra.
    const arriba = rect.top - HUECO_PANEL - alto;
    if (arriba >= desde) top = arriba;
  }
  // Tope duro: la caja no se sale de ese rectángulo aunque la fila esté
  // fuera de la vista (se abrió con un clic y después se scrolleó el
  // explorador, o la fila quedó recortada por ese mismo scroll).
  top = Math.min(Math.max(top, desde), Math.max(desde, hasta - alto));
  panel.style.setProperty("--accion-top", `${top}px`);
}

// El panel es fijo respecto del viewport: hay que recalcularlo cuando el
// lienzo cambia de tamaño o cuando la fila ancla se mueve (scroll de
// cualquier panel y plegado de carpetas). Los oyentes quedan vivos con
// la acción cerrada, donde `ubicarPanel` no hace nada.
window.addEventListener("resize", ubicarPanel);
document.addEventListener("scroll", ubicarPanel, true);
document.addEventListener("toggle", ubicarPanel, true);

/**
 * Escape cancela la acción (si no está en vuelo) desde cualquier control
 * del panel.
 * @param {KeyboardEvent} evento - Tecla pulsada dentro del panel.
 * @param {Accion} a - Acción del panel.
 */
function siEscapeCancela(evento, a) {
  if (evento.key !== "Escape" || a.enVuelo) return;
  evento.preventDefault();
  cancelarAccion();
}

/**
 * Formulario de renombrar/mover: label arriba, input a todo el ancho del
 * panel (el dato importante), botones debajo y envío con Enter o con el
 * botón principal.
 * @param {HTMLElement} panel - Panel a rellenar.
 * @param {Object} config - Textos y operación (ver `descripcionAccion`).
 * @param {Accion} a - Acción abierta.
 */
function armarRenombrar(panel, config, a) {
  const etiqueta = document.createElement("label");
  etiqueta.htmlFor = "accion-campo";
  etiqueta.textContent = config.etiqueta;

  const campo = document.createElement("input");
  campo.id = "accion-campo";
  campo.type = "text";
  campo.autocomplete = "off";
  campo.value = a.valor;
  // El foco al abrir va al campo, aunque «Cancelar» vaya primero en el
  // orden visual (ver `enfocarAccion`).
  campo.dataset.principal = "1";
  ajustarSizeCampo(campo);

  const aplicar = document.createElement("button");
  aplicar.type = "submit";
  aplicar.className = "btn";
  aplicar.textContent = config.textoBoton;

  // Botones en su propia fila, debajo del input: no compiten por ancho.
  const botones = document.createElement("div");
  botones.className = "accion-botones";
  botones.append(botonCancelar(), aplicar);

  const indicador = crearIndicador();
  panel.append(etiqueta, campo, botones, indicador);

  // El valor escrito se copia a la acción: un repintado de fondo no lo
  // pierde, y la marca de inválido se retira al seguir escribiendo.
  campo.addEventListener("input", () => {
    campo.removeAttribute("aria-invalid");
    pintarEstado(indicador, "", "");
    if (accion === a) accion.valor = campo.value;
    // Un valor más largo agranda el campo: hay que volver a medirlo.
    ajustarSizeCampo(campo);
    ubicarPanel();
  });

  panel.addEventListener("submit", (evento) => {
    evento.preventDefault();
    const valor = campo.value.trim();
    if (!valor) {
      marcarInvalido(campo, indicador, config.vacio);
      return;
    }
    // Sin cambios contra el valor original no se manda nada: se cierra.
    // Para proyectos el input va sin prefijo (ver `abrirAccion`), así que
    // la comparación es contra el nombre mostrado, no contra la clave.
    const original = a.tipo === "proyecto" ? stripNs(a.path) : a.path;
    if (valor === original) {
      cancelarAccion();
      return;
    }
    ejecutarAccion(panel, config, valor);
  });
}

/**
 * Confirmación de eliminar: aviso con todo lo que se pierde y dos
 * botones; al backend se le pide recién cuando se confirma.
 * @param {HTMLElement} panel - Panel a rellenar.
 * @param {Object} config - Textos y operación (ver `descripcionAccion`).
 */
function armarEliminar(panel, config) {
  const aviso = document.createElement("p");
  aviso.className = "accion-aviso";
  aviso.textContent = config.aviso;

  const confirmar = document.createElement("button");
  confirmar.type = "button";
  confirmar.className = "btn btn-peligro";
  confirmar.textContent = "Eliminar";
  // Marca cuál control recibe el foco al abrir (ver `enfocarAccion`).
  confirmar.dataset.principal = "1";
  confirmar.addEventListener("click", () => ejecutarAccion(panel, config, ""));

  // Mismo orden que al renombrar: «Cancelar» a la izquierda, el que
  // confirma a la derecha y ambos por debajo del aviso.
  const botones = document.createElement("div");
  botones.className = "accion-botones";
  botones.append(botonCancelar(), confirmar);

  panel.append(aviso, botones, crearIndicador());
}

/**
 * Ajusta el `size` del campo al texto que lleva: de ese atributo sale el
 * ancho `max-content` del panel, así la ruta completa se ve entera sin
 * cortarse. El techo lo pone el CSS contra el lienzo.
 * @param {HTMLInputElement} campo - Input del panel de renombrar.
 */
function ajustarSizeCampo(campo) {
  // Dos caracteres de holgura y un piso, para que con rutas cortas el
  // panel no quede más angosto que su propia etiqueta.
  campo.size = Math.max(24, campo.value.length + 2);
}

/** Botón «Cancelar»: solo cierra el panel, nunca envía nada. */
function botonCancelar() {
  const boton = document.createElement("button");
  boton.type = "button";
  boton.className = "btn";
  boton.textContent = "Cancelar";
  boton.addEventListener("click", cancelarAccion);
  return boton;
}

/** Indicador `aria-live` propio de cada panel de acción. */
function crearIndicador() {
  const indicador = document.createElement("p");
  indicador.className = "estado";
  indicador.setAttribute("role", "status");
  indicador.setAttribute("aria-live", "polite");
  return indicador;
}

/**
 * Habilita o desabilita todos los controles del panel.
 * @param {HTMLElement} panel - Panel de la acción.
 * @param {boolean} habilitar - true para habilitar.
 */
function habilitarPanel(panel, habilitar) {
  for (const control of panel.querySelectorAll("input, button")) {
    control.disabled = !habilitar;
  }
}

/**
 * Textos y operación de la acción abierta, según entidad y modo.
 * `etiqueta`, `vacio` y `textoBoton` solo se usan al renombrar.
 * @param {Accion} a - Acción abierta.
 * @returns {{
 *   etiqueta: string,
 *   vacio: string,
 *   textoBoton: string,
 *   aviso: string,
 *   fallo: string,
 *   confirmar: (valor: string) => Promise<string>,
 * }}
 */
function descripcionAccion(a) {
  const eliminar = a.modo === "eliminar";
  const deshacer = "Esta acción no se puede deshacer.";

  if (a.tipo === "proyecto") {
    // `a.path` es el nombre CON prefijo (clave interna): al usuario se le
    // muestra sin prefijo y el nombre nuevo se le vuelve a prefijar.
    const nombre = stripNs(a.path);
    return {
      etiqueta: "Nuevo nombre del proyecto",
      vacio: "El nombre del proyecto no puede estar vacío.",
      textoBoton: "Renombrar",
      aviso: `Se eliminará el proyecto «${nombre}» con todas sus notas y carpetas. ${deshacer}`,
      fallo: eliminar ? "No se pudo eliminar el proyecto" : "No se pudo renombrar el proyecto",
      confirmar: eliminar
        ? () => eliminarProyecto(a.path)
        : (nuevo) => renombrarProyecto(a.path, nsProject(nuevo)),
    };
  }

  if (a.tipo === "nota") {
    return {
      etiqueta: "Nueva ruta de la nota (renombrar o mover)",
      vacio: "La ruta de la nota no puede estar vacía.",
      textoBoton: "Mover",
      aviso: `Se eliminará la nota «${a.path}» y todo su contenido. ${deshacer}`,
      fallo: eliminar ? "No se pudo eliminar la nota" : "No se pudo renombrar la nota",
      confirmar: eliminar
        ? () => eliminarNota(a.proyecto, a.path)
        : (nueva) => renombrarNota(a.proyecto, a.path, nueva),
    };
  }

  return {
    etiqueta: "Nueva ruta de la carpeta (renombrar o mover)",
    vacio: "La ruta de la carpeta no puede estar vacía.",
    textoBoton: "Mover",
    aviso: `Se eliminará la carpeta «${a.path}» con todo lo que contiene. ${deshacer}`,
    fallo: eliminar ? "No se pudo eliminar la carpeta" : "No se pudo renombrar la carpeta",
    confirmar: eliminar
      ? () => eliminarCarpeta(a.proyecto, a.path)
      : (nueva) => renombrarCarpeta(a.proyecto, a.path, nueva),
  };
}

/**
 * Ejecuta la operación confirmada: bloquea el panel, pide el backend y,
 * si sale bien, cierra el panel y avisa el resultado con un toast de
 * éxito (el indicador general del explorador queda vacío). Si falla, el
 * error queda en el panel para corregir el valor y reintentar.
 * @param {HTMLElement} panel - Panel de la acción.
 * @param {Object} config - Textos y operación (ver `descripcionAccion`).
 * @param {string} valor - Valor del input, vacío al eliminar.
 */
async function ejecutarAccion(panel, config, valor) {
  if (!accion || accion.enVuelo) return;
  const a = accion;
  a.enVuelo = true;
  habilitarPanel(panel, false);
  pintarEstado(panel.querySelector(".estado"), "trabajando", "Aplicando…");

  let mensaje;
  try {
    mensaje = await config.confirmar(valor);
  } catch (error) {
    // El panel pudo ser reconstruido (o descartado) por un refresco
    // durante el pedido: se busca el que esté vivo antes de pintar.
    if (accion === a) a.enVuelo = false;
    const texto = `${config.fallo}: ${error.message}`;
    const vivo = document.querySelector("[data-accion-panel]");
    if (vivo) {
      habilitarPanel(vivo, true);
      pintarEstado(vivo.querySelector(".estado"), "error", texto);
      enfocarAccion(null);
    } else {
      pintarEstado(exploradorEstado, "error", texto);
    }
    return;
  }

  // Solo se cierra si la acción que hizo el pedido sigue siendo la abierta.
  if (accion === a) cerrarAccion();
  // El éxito es transitorio: va al toast y el indicador del explorador
  // queda vacío (el error, en cambio, sigue en el panel de la acción).
  // El título nombra el control que dispara la operación —«Renombrar» o
  // «Mover» según `textoBoton`, «Eliminar» al confirmar— más el objeto.
  pintarEstado(exploradorEstado, "", "");
  const disparador = a.modo === "eliminar" ? "Eliminar" : config.textoBoton;
  mostrarToast(null, `${disparador} ${a.tipo}`, mensaje);
  enfocarTrasOperacion(a.tipo, a.path);
}

// --------------------------------------------- Operaciones con backend

/**
 * PATCH /api/projects/{project}: renombra el proyecto.
 * Si era el activo, el estado se actualiza en el lugar: la nota abierta y
 * el árbol se conservan porque solo cambia el nombre del proyecto.
 * @param {string} viejo - Nombre actual (CON prefijo, para API).
 * @param {string} nuevo - Nombre nuevo (CON prefijo, para API).
 * @returns {Promise<string>} Mensaje de éxito para el toast.
 */
async function renombrarProyecto(viejo, nuevo) {
  await pedir(`/api/projects/${encodeURIComponent(viejo)}`, conJson("PATCH", { name: nuevo }));
  // viejo y nuevo ya tienen prefijo
  const viejoUI = stripNs(viejo);
  const nuevoUI = stripNs(nuevo);
  if (estado.proyectoActivo === viejoUI) {
    estado.proyectoActivo = nuevoUI;
    if (estado.nota) {
      // `estado.nota.project` guarda el nombre CON prefijo (regla de
      // namespace): `nsProject` garantiza que siga prefijado.
      estado.nota.project = nsProject(nuevo);
      notaTitulo.textContent = `${nuevoUI} / ${estado.nota.path}`;
    }
  }
  await cargarProyectos();
  if (estado.proyectoActivo === nuevoUI) await cargarArbol(nsProject(nuevoUI));
  return `Proyecto renombrado a «${nuevoUI}».`;
}

/**
 * DELETE /api/projects/{project}: borra el proyecto con todo su contenido.
 * @param {string} nombre - Proyecto a eliminar (CON prefijo, para API).
 * @returns {Promise<string>} Mensaje de éxito para el toast.
 */
async function eliminarProyecto(nombre) {
  const nombreUI = stripNs(nombre);
  if (estado.proyectoActivo === nombreUI && hayCambios()) {
    throw new Error("hay cambios sin guardar en la nota abierta (guardá primero)");
  }
  await pedir(`/api/projects/${encodeURIComponent(nombre)}`, { method: "DELETE" });
  // Si era el activo, `pintarProyectos` lo deselecciona al no encontrarlo.
  const proyectos = await cargarProyectos();
  if (!estado.proyectoActivo && proyectos.length) {
    // Quedan proyectos: se selecciona el más reciente, como al arrancar.
    await seleccionarProyecto(stripNs(proyectos[0].name));
  }
  return `Proyecto «${nombreUI}» eliminado.`;
}

/**
 * PATCH .../notes/{path}: renombra o mueve la nota dentro del proyecto.
 * Si era la nota abierta, solo cambia su ruta: el contenido del editor,
 * incluidos cambios sin guardar, se conserva tal cual.
 * @param {string} proyecto - Proyecto que contiene la nota (SIN prefijo, UI).
 * @param {string} vieja - Ruta actual.
 * @param {string} nueva - Ruta nueva.
 * @returns {Promise<string>} Mensaje de éxito para el toast.
 */
async function renombrarNota(proyecto, vieja, nueva) {
  // API necesita proyecto CON prefijo
  const datos = await pedir(
    `/api/projects/${encodeURIComponent(nsProject(proyecto))}/notes/${rutaUrl(vieja)}`,
    conJson("PATCH", { path: nueva }),
  );
  // `estado.nota.project` lleva el prefijo del backend; `proyecto` llega
  // sin prefijo (valor de UI), por eso se normaliza antes de comparar.
  if (estado.nota && estado.nota.project === nsProject(proyecto) && estado.nota.path === vieja) {
    estado.nota.path = datos.path;
    estado.nota.modified = datos.modified;
    notaTitulo.textContent = `${stripNs(datos.project)} / ${datos.path}`;
    refrescarGuardado();
  }
  await Promise.all([cargarProyectos(), cargarArbol(nsProject(proyecto))]);
  return mensajeCambio("Nota", vieja, nueva);
}

/**
 * DELETE .../notes/{path}: borra la nota.
 * Si era la nota abierta, se cierra: editor vacío y preview limpio.
 * @param {string} proyecto - Proyecto que contiene la nota (SIN prefijo, UI).
 * @param {string} ruta - Ruta de la nota.
 * @returns {Promise<string>} Mensaje de éxito para el toast.
 */
async function eliminarNota(proyecto, ruta) {
  if (estado.nota && estado.nota.path === ruta && hayCambios()) {
    throw new Error("hay cambios sin guardar en esta nota (guardá primero)");
  }
  // API necesita proyecto CON prefijo
  await pedir(
    `/api/projects/${encodeURIComponent(nsProject(proyecto))}/notes/${rutaUrl(ruta)}`,
    { method: "DELETE" },
  );
  if (estado.nota && estado.nota.path === ruta) cerrarNota();
  await Promise.all([cargarProyectos(), cargarArbol(nsProject(proyecto))]);
  return `Nota «${ruta}» eliminada.`;
}

/**
 * PATCH .../dirs/{path}: renombra o mueve la carpeta.
 * Si la nota abierta vivía adentro, su ruta se reescribe con el prefijo
 * nuevo sin tocar el contenido del editor.
 * @param {string} proyecto - Proyecto que contiene la carpeta (SIN prefijo, UI).
 * @param {string} vieja - Ruta actual.
 * @param {string} nueva - Ruta nueva.
 * @returns {Promise<string>} Mensaje de éxito para el toast.
 */
async function renombrarCarpeta(proyecto, vieja, nueva) {
  // API necesita proyecto CON prefijo
  await pedir(
    `/api/projects/${encodeURIComponent(nsProject(proyecto))}/dirs/${rutaUrl(vieja)}`,
    conJson("PATCH", { path: nueva }),
  );
  moverRutaAbierta(vieja, nueva);
  // El plegado se guarda por ruta: hay que reescribirlo con la ruta nueva.
  moverCarpetasColapsadas(vieja, nueva);
  await Promise.all([cargarProyectos(), cargarArbol(nsProject(proyecto))]);
  return mensajeCambio("Carpeta", vieja, nueva);
}

/**
 * DELETE .../dirs/{path}?recursive=true: borra la carpeta con todo su
 * contenido. `recursive` se envía recién después de la confirmación
 * explícita del panel (sin él el backend responde 409 si no está vacía).
 * @param {string} proyecto - Proyecto que contiene la carpeta (SIN prefijo, UI).
 * @param {string} ruta - Ruta de la carpeta.
 * @returns {Promise<string>} Mensaje de éxito para el toast.
 */
async function eliminarCarpeta(proyecto, ruta) {
  const notaAdentro = Boolean(estado.nota) && estado.nota.path.startsWith(`${ruta}/`);
  if (notaAdentro && hayCambios()) {
    throw new Error("hay cambios sin guardar en una nota de esta carpeta (guardá primero)");
  }
  // API necesita proyecto CON prefijo
  await pedir(
    `/api/projects/${encodeURIComponent(nsProject(proyecto))}/dirs/${rutaUrl(ruta)}?recursive=true`,
    { method: "DELETE" },
  );
  if (notaAdentro) cerrarNota();
  // El plegado de una carpeta borrada ya no aplica: se limpia para no
  // acumular claves viejas.
  for (const clave of [...carpetasColapsadas]) {
    if (clave === ruta || clave.startsWith(`${ruta}/`)) carpetasColapsadas.delete(clave);
  }
  await Promise.all([cargarProyectos(), cargarArbol(nsProject(proyecto))]);
  return `Carpeta «${ruta}» eliminada.`;
}

/**
 * Mensaje de éxito al cambiar la ruta: distingue un rename dentro de la
 * misma carpeta de un movimiento a otra.
 * @param {"Nota"|"Carpeta"} tipo - Nombre de la entidad (femenino).
 * @param {string} vieja - Ruta anterior.
 * @param {string} nueva - Ruta nueva.
 * @returns {string} Mensaje en español.
 */
function mensajeCambio(tipo, vieja, nueva) {
  const mismaCarpeta = carpetaContenedora(vieja) === carpetaContenedora(nueva);
  return `${tipo} ${mismaCarpeta ? "renombrada" : "movida"} a «${nueva}».`;
}

/**
 * Reescribe la ruta de la nota abierta si estaba dentro de una carpeta
 * que se renombró o movió; el editor no se toca.
 * @param {string} vieja - Carpeta antes del cambio.
 * @param {string} nueva - Carpeta después del cambio.
 */
function moverRutaAbierta(vieja, nueva) {
  const nota = estado.nota;
  if (!nota || !nota.path.startsWith(`${vieja}/`)) return;
  nota.path = nueva + nota.path.slice(vieja.length);
  // `nota.project` lleva prefijo: al título se le muestra sin él.
  notaTitulo.textContent = `${stripNs(nota.project)} / ${nota.path}`;
  refrescarGuardado();
}

/**
 * Reescribe las carpetas plegadas cuando una carpeta cambia de ruta, para
 * conservar el plegado de la movida y de sus hijas.
 * @param {string} vieja - Carpeta antes del cambio.
 * @param {string} nueva - Carpeta después del cambio.
 */
function moverCarpetasColapsadas(vieja, nueva) {
  for (const clave of [...carpetasColapsadas]) {
    if (clave === vieja) {
      carpetasColapsadas.delete(clave);
      carpetasColapsadas.add(nueva);
    } else if (clave.startsWith(`${vieja}/`)) {
      carpetasColapsadas.delete(clave);
      carpetasColapsadas.add(nueva + clave.slice(vieja.length));
    }
  }
}

// -------------------------------------------------------- Crear proyecto

proyectoForm.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const nombre = proyectoNombre.value.trim();
  if (!nombre) {
    marcarInvalido(proyectoNombre, proyectoEstado, "El nombre del proyecto no puede estar vacío.");
    return;
  }
  if (hayCambios()) {
    // Si se creara el proyecto, la selección saltaría a otro lado y la
    // nota con cambios sin guardar quedaría huérfana. El bloqueo vive en
    // el indicador del propio formulario.
    pintarEstado(proyectoEstado, "error", "Tenés cambios sin guardados: guardá antes de crear un proyecto.");
    return;
  }

  pintarEstado(proyectoEstado, "trabajando", "Creando…");
  try {
    // API recibe CON prefijo
    const proyecto = await pedir("/api/projects", conJson("POST", { name: nsProject(nombre) }));
    proyectoNombre.value = "";
    // El éxito es transitorio (toast de 6 s) y el indicador vuelve a
    // quedar vacío; un error, en cambio, se queda junto al formulario.
    pintarEstado(proyectoEstado, "", "");
    // Mostrar SIN prefijo
    mostrarToast(null, "Crear proyecto", `Proyecto «${stripNs(proyecto.name)}» creado.`);
    await cargarProyectos();
    // El proyecto nuevo queda seleccionado: ya se puede crear una nota.
    // seleccionarProyecto espera SIN prefijo
    await seleccionarProyecto(stripNs(proyecto.name));
  } catch (error) {
    // 409 (ya existe) y 422 (nombre inválido) llegan acá con su detalle.
    pintarEstado(proyectoEstado, "error", error.message);
  }
});

// ---------------------------------------------------------- Crear nota

notaForm.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const proyecto = estado.proyectoActivo;
  if (!proyecto) {
    pintarEstado(notaEstado, "error", "Elegí un proyecto antes de crear una nota.");
    return;
  }
  const ruta = notaRuta.value.trim();
  if (!ruta) {
    marcarInvalido(notaRuta, notaEstado, "La ruta de la nota no puede estar vacía.");
    return;
  }
  if (hayCambios()) {
    pintarEstado(notaEstado, "error", "Tenés cambios sin guardados: guardá antes de crear otra nota.");
    return;
  }

  pintarEstado(notaEstado, "trabajando", "Creando…");
  try {
    // API necesita proyecto CON prefijo
    const nota = await pedir(
      `/api/projects/${encodeURIComponent(nsProject(proyecto))}/notes`,
      conJson("POST", { path: ruta, content: "" }),
    );
    notaRuta.value = "";
    // Éxito transitorio en toast; el indicador del formulario queda limpio.
    pintarEstado(notaEstado, "", "");
    mostrarToast(null, "Crear nota", `Nota «${nota.path}» creada.`);
    await Promise.all([cargarProyectos(), cargarArbol(nsProject(proyecto))]);
    await abrirNota(nota.path);
  } catch (error) {
    // 404 (proyecto borrado), 409 (ruta ocupada) y 422 (ruta inválida).
    pintarEstado(notaEstado, "error", error.message);
  }
});

/**
 * Marca un campo como inválido y explica el motivo en su indicador.
 * El `required` nativo corta el submit antes de llegar a nuestro código:
 * este mensaje (más el oyente `invalid` de abajo) evita depender del
 * idioma del navegador.
 * @param {HTMLInputElement} campo - Input rechazado.
 * @param {HTMLElement} indicador - `<p role="status">` donde mostrarlo.
 * @param {string} texto - Motivo en español.
 */
function marcarInvalido(campo, indicador, texto) {
  campo.setAttribute("aria-invalid", "true");
  pintarEstado(indicador, "error", texto);
  campo.focus();
}

// La validación nativa (campo vacío con `required`) no dispara el submit:
// en fase de captura se previene su burbuja y se traduce al indicador.
proyectoForm.addEventListener("invalid", (evento) => {
  evento.preventDefault();
  marcarInvalido(proyectoNombre, proyectoEstado, "El nombre del proyecto no puede estar vacío.");
}, true);

notaForm.addEventListener("invalid", (evento) => {
  evento.preventDefault();
  marcarInvalido(notaRuta, notaEstado, "La ruta de la nota no puede estar vacía.");
}, true);

// Al escribir de nuevo, el campo deja de estar inválido: `aria-invalid`
// tiene que reflejar el estado actual, no el del último envío fallido.
for (const campo of [proyectoNombre, notaRuta]) {
  campo.addEventListener("input", () => campo.removeAttribute("aria-invalid"));
}

// Al empezar a escribir se limpia la marca de campo inválido y su aviso.
proyectoNombre.addEventListener("input", () => {
  proyectoNombre.removeAttribute("aria-invalid");
  pintarEstado(proyectoEstado, "", "");
});
notaRuta.addEventListener("input", () => {
  notaRuta.removeAttribute("aria-invalid");
  pintarEstado(notaEstado, "", "");
});

// -------------------------------------------------------- Importar .md

// El input de archivo va oculto: quien dispara su selector es el botón
// (un `<label for>` no se puede deshabilitar, y el botón sí apaga sin
// proyecto activo o con cambios sin guardar).
importarBoton.addEventListener("click", () => importarArchivo.click());

importarArchivo.addEventListener("change", () => {
  importarArchivoElegido(importarArchivo.files[0]);
});

/**
 * Valida y envía el archivo elegido como nota nueva, en la raíz del
 * proyecto activo.
 *
 * Las validaciones cortan, en este orden y antes de tocar la red:
 * extensión `.md`, tamaño (sin llegar a leer el archivo) y decodificación
 * UTF-8 estricta. Los errores y el bloqueo por cambios sin guardar quedan
 * en el indicador del propio bloque (`#importar-estado`); el éxito es un
 * toast transitorio.
 *
 * @param {File|undefined} archivo - Archivo elegido en el selector.
 * @returns {Promise<void>} El error se pinta en `#importar-estado`.
 */
async function importarArchivoElegido(archivo) {
  // Selector cancelado: no hay nada que validar.
  if (!archivo) return;

  const nombre = archivo.name;
  // Se vacía de entrada para que elegir el mismo archivo otra vez vuelva a
  // disparar `change`, aunque la importación termine mal. El `File` ya
  // quedó tomado en `archivo` y se sigue leyendo igual.
  importarArchivo.value = "";

  const proyecto = estado.proyectoActivo;
  if (!proyecto) {
    pintarEstado(importarEstado, "error", "Elegí un proyecto antes de importar una nota.");
    return;
  }
  if (hayCambios()) {
    // El bloqueo es error y va al indicador de esta misma fila (ahí está
    // el control que lo dispara); `#guardar-estado` no lo pinta más.
    pintarEstado(
      importarEstado,
      "error",
      "Tenés cambios sin guardados: guardá antes de importar una nota.",
    );
    return;
  }

  // El `accept` del input es solo una ayuda al selector de archivos: la
  // extensión se valida acá, sin depender de lo que el navegador filtre.
  if (!nombre.toLowerCase().endsWith(".md")) {
    pintarEstado(importarEstado, "error", `El archivo «${nombre}» no tiene extensión .md.`);
    return;
  }
  // El tamaño sale de los metadatos del archivo, así que este corte ocurre
  // sin haberlo leído: un archivo gigante ni siquiera se carga en memoria.
  if (archivo.size > MAX_BYTES) {
    pintarEstado(
      importarEstado,
      "error",
      `El archivo ocupa ${archivo.size} bytes y el máximo es ${MAX_BYTES}.`,
    );
    return;
  }

  pintarEstado(importarEstado, "trabajando", "Importando…");
  let contenido;
  try {
    contenido = await decodificarUtf8(archivo);
  } catch (_) {
    // Bytes que no son UTF-8: un binario renombrado a `.md`.
    pintarEstado(importarEstado, "error", "El archivo no es texto UTF-8 válido.");
    return;
  }
  if (contenido.includes("\x00")) {
    // UTF-8 válido pero binario de todas formas: el NUL es la señal clásica
    // (la misma que usa el backend en `_validar_contenido`).
    pintarEstado(
      importarEstado,
      "error",
      "El archivo no es texto UTF-8 válido: contiene un byte NUL (\\x00).",
    );
    return;
  }

  try {
    const nota = await pedir(
      // API necesita proyecto CON prefijo
      `/api/projects/${encodeURIComponent(nsProject(proyecto))}/notes`,
      // `path` va tal cual, sin sanitizar: un nombre que el backend no
      // acepta responde 422 y su detalle se muestra sin traducir.
      conJson("POST", { path: nombre, content: contenido }),
    );
    // Éxito transitorio en toast; «Importando…» no queda colgado.
    pintarEstado(importarEstado, "", "");
    mostrarToast(null, "Importar .md", `Nota «${nota.path}» importada.`);
    await Promise.all([cargarProyectos(), cargarArbol(nsProject(proyecto))]);
    await abrirNota(nota.path);
  } catch (error) {
    // 409 (la ruta ya está ocupada: no se pisa la nota existente), 422
    // (ruta inválida o demasiado grande) y 404 (proyecto borrado).
    pintarEstado(importarEstado, "error", error.message);
  }
}

/**
 * Lee un archivo como texto UTF-8 estricto.
 *
 * `File.text()` decodifica en modo permisivo: los bytes inválidos quedan
 * como U+FFFD y un binario renombrado a `.md` pasaría por un texto lleno
 * de reemplazos. Por eso se leen los bytes crudos y se decodifican con
 * `fatal: true`, que lanza ante el primer byte inválido.
 *
 * @param {File} archivo - Archivo elegido (tamaño ya validado).
 * @returns {Promise<string>} Contenido del archivo.
 * @throws {TypeError} Si los bytes no son UTF-8 válido.
 */
async function decodificarUtf8(archivo) {
  const buffer = await archivo.arrayBuffer();
  return new TextDecoder("utf-8", { fatal: true }).decode(buffer);
}

// -------------------------------------------------- Exportar/Importar proyecto (ZIP)

/**
 * Exporta el proyecto activo como archivo `.zip`.
 * Descarga directa vía blob. El resultado va en un toast (y no en el
 * explorador, que puede estar cerrado en pantallas angostas).
 */
async function exportarProyecto() {
  const proyecto = estado.proyectoActivo;
  if (!proyecto) return;

  // El «Exportando…» es un aviso de trabajo: se retira apenas llega el
  // resultado, para no dejar en pantalla un mensaje que ya no es cierto.
  const enVuelo = mostrarToast(null, "Exportar .zip", "Exportando…");
  try {
    // API necesita proyecto CON prefijo
    const respuesta = await fetch(
      `/api/projects/${encodeURIComponent(nsProject(proyecto))}/export`,
      { method: "GET" }
    );
    if (!respuesta.ok) {
      const error = await respuesta.json().catch(() => ({}));
      throw new Error(error.detail || `error HTTP ${respuesta.status}`);
    }
    const blob = await respuesta.blob();
    const url = URL.createObjectURL(blob);
    const enlace = document.createElement("a");
    enlace.href = url;
    enlace.download = `${proyecto}.zip`;
    enlace.hidden = true;
    document.body.append(enlace);
    enlace.click();
    enlace.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    quitarToast(enVuelo);
    mostrarToast(null, "Exportar .zip", `Proyecto «${proyecto}» exportado.`);
  } catch (error) {
    // El error de exportación vive en la barra ☰/Exportar, que puede estar
    // cerrada: va en toast SIN auto-cierre (solo la X lo cierra).
    quitarToast(enVuelo);
    mostrarToast(null, "Exportar .zip", `No se pudo exportar: ${error.message}`, "error");
  }
}

/**
 * Importa un proyecto desde archivo `.zip` (fila única del explorador).
 * Los errores y el bloqueo por cambios sin guardar quedan en el indicador
 * compartido `#importar-estado`, debajo de la fila; el resumen sin
 * errores es un toast de éxito.
 * @param {File|undefined} archivo - Archivo `.zip` elegido.
 */
async function importarProyectoElegido(archivo) {
  if (!archivo) return;

  const proyecto = estado.proyectoActivo;
  if (!proyecto) {
    pintarEstado(importarEstado, "error", "Elegí un proyecto antes de importar.");
    return;
  }
  if (hayCambios()) {
    // Bloqueo en el indicador de esta fila, no en el de guardado.
    pintarEstado(
      importarEstado,
      "error",
      "Tenés cambios sin guardados: guardá antes de importar un proyecto.",
    );
    return;
  }

  const nombre = archivo.name;
  importarProyectoArchivo.value = "";

  if (!nombre.toLowerCase().endsWith(".zip")) {
    pintarEstado(importarEstado, "error", `El archivo «${nombre}» no es .zip.`);
    return;
  }

  pintarEstado(importarEstado, "trabajando", "Importando…");
  try {
    const formData = new FormData();
    formData.append("file", archivo);
    // API necesita proyecto CON prefijo
    const resultado = await fetch(
      `/api/projects/${encodeURIComponent(nsProject(proyecto))}/import`,
      { method: "POST", body: formData }
    );
    const data = await resultado.json();
    if (!resultado.ok) {
      throw new Error(data.detail || data.error || `error HTTP ${resultado.status}`);
    }
    const { creadas, actualizadas, omitidas, errores } = data;
    const resumen =
      `Importado: ${creadas} creadas, ${actualizadas} actualizadas` +
      (omitidas ? `, ${omitidas} omitidas` : "");
    if (errores.length) {
      // Un resumen con errores es un error: se queda junto al control
      // (Carbon) hasta que algo lo reemplace.
      pintarEstado(importarEstado, "error", resumen);
      console.warn("Errores de importación:", errores);
    } else {
      // Éxito transitorio en toast; «Importando…» no queda colgado.
      pintarEstado(importarEstado, "", "");
      mostrarToast(null, "Importar .zip", `${resumen}.`);
    }
    await Promise.all([cargarProyectos(), cargarArbol(nsProject(proyecto))]);
  } catch (error) {
    pintarEstado(importarEstado, "error", `No se pudo importar: ${error.message}`);
  }
}

// El menú ☰ y la barra exportan; la fila del explorador importa. Cada
// botón de importación dispara su propio input de archivo oculto.
importarProyectoBtn.addEventListener("click", () => importarProyectoArchivo.click());
importarProyectoArchivo.addEventListener("change", () => {
  importarProyectoElegido(importarProyectoArchivo.files[0]);
});

// ------------------------------------------------------ Abrir y guardar

/**
 * Abre una nota del proyecto activo en el editor y actualiza el preview.
 * Con cambios sin guardar no cambia de nota: esos cambios se perderían.
 * @param {string} ruta - Ruta dentro del proyecto (con o sin `.md`).
 * @returns {Promise<boolean>} Si la nota se abrió.
 */
async function abrirNota(ruta) {
  const proyecto = estado.proyectoActivo;
  if (!proyecto) return false;
  if (estado.nota && estado.nota.path === ruta) return true;
  if (hayCambios()) {
    // El clic fue en una fila del árbol: el bloqueo va al indicador del
    // explorador. `#guardar-estado` queda exclusivo del guardado.
    pintarEstado(
      exploradorEstado,
      "error",
      "Tenés cambios sin guardados: guardá antes de cambiar de nota.",
    );
    return false;
  }

  try {
    // API necesita proyecto CON prefijo
    const nota = await pedir(
      `/api/projects/${encodeURIComponent(nsProject(proyecto))}/notes/${rutaUrl(ruta)}`,
    );
    estado.nota = nota;
    editor.value = nota.content;
    // Resetear scroll al inicio al abrir nueva nota
    editor.scrollTop = 0;
    if (previewVisible()) preview.scrollTop = 0;
    notaTitulo.textContent = `${stripNs(nota.project)} / ${nota.path}`;
    marcarNotaActiva();
    refrescarGuardado();
    refrescarHabilitacion();
    // Con la vista previa oculta no se pide render (se retoma al
    // mostrarla: entonces `editor.value` difiere de lo renderizado).
    if (previewVisible()) renderizarPreview(nota.content);
    // Con el editor oculto `focus()` no haría nada: el foco se queda en
    // el elemento del árbol desde el que se abrió la nota, que es donde
    // conviene que siga.
    if (elementoVisible(editor)) {
      editor.selectionStart = editor.selectionEnd = 0;
      editor.focus();
    }
    cerrarExploradorSiAngosto();
    return true;
  } catch (error) {
    pintarEstado(exploradorEstado, "error", `No se pudo abrir la nota: ${error.message}`);
    return false;
  }
}

/**
 * Guarda el contenido del editor con PUT sobre la nota abierta.
 * @returns {Promise<boolean>} Si el guardado salió bien.
 */
async function guardarNota() {
  if (!estado.nota || estado.guardando) return false;

  estado.guardando = true;
  refrescarBotonGuardar();
  pintarEstado(guardarEstado, "trabajando", "Guardando…");

  let notaGuardada;
  try {
    // `estado.nota.project` ya viene CON prefijo del backend: se usa tal
    // cual (prefijarlo de nuevo mandaba un 404, ver la regla de namespace).
    notaGuardada = await pedir(
      `/api/projects/${encodeURIComponent(estado.nota.project)}/notes/${rutaUrl(estado.nota.path)}`,
      conJson("PUT", { content: editor.value }),
    );
  } catch (error) {
    // Sin `refrescarGuardado()`: pisaría este mensaje con el estado real.
    estado.guardando = false;
    refrescarBotonGuardar();
    pintarEstado(guardarEstado, "error", `No se pudo guardar: ${error.message}`);
    return false;
  }

  estado.guardando = false;
  estado.nota = notaGuardada;
  refrescarBotonGuardar();
  pintarEstado(guardarEstado, "ok", "Guardado");

  // Las fechas del árbol cambian con el guardado; el listado de proyectos
  // no, porque el directorio del proyecto no se toca al escribir una nota.
  // `notaGuardada.project` conserva el prefijo, como espera `cargarArbol`.
  await cargarArbol(notaGuardada.project);
  // Si siguió escribiendo durante el guardado, el indicador vuelve al
  // estado real en vez de dejar un «Guardado» que ya no es cierto.
  if (hayCambios()) refrescarGuardado();
  return true;
}

// ---------------------------------------------------------- Descargar

/**
 * Descarga el contenido del editor como archivo `.md`.
 *
 * El archivo se arma en el cliente (Blob + enlace temporal): no hay
 * endpoint de descarga. Va el contenido del editor y no el guardado para
 * que lo descargado coincida exactamente con lo que se ve en pantalla;
 * con cambios sin guardar, esa es la versión que el usuario considera
 * actual. Si no hay nota abierta no se descarga nada (el botón está
 * deshabilitado, pero la función se resguarda igual).
 */
function descargarNota() {
  if (!estado.nota) return;

  const nombreArchivo = `${ultimoSegmento(estado.nota.path)}.md`;
  const blob = new Blob([editor.value], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);

  const enlace = document.createElement("a");
  enlace.href = url;
  enlace.download = nombreArchivo;
  enlace.hidden = true;
  document.body.append(enlace);
  enlace.click();
  enlace.remove();

  // La descarga ya arrancó: se libera la URL en el siguiente ciclo para
  // no cortar la lectura del Blob en navegadores más lentos.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Exporta la nota abierta como `.pdf`.
 *
 * Pide el `.pdf` al backend (que renderiza el markdown con resaltado de
 * sintaxis y lo convierte con WeasyPrint) y lo descarga como Blob.
 * Va el contenido guardado, no el del editor: la exportación es de la
 * nota, no de los cambios sin guardar. Éxito y error se avisan con un
 * toast (hoy un fallo quedaba solo en la consola).
 */
async function exportarPdf() {
  if (!estado.nota) return;

  const nombreArchivo = `${ultimoSegmento(estado.nota.path)}.pdf`;
  try {
    // `estado.nota.project` ya viene CON prefijo del backend: sin volver a
    // prefijar (el doble prefijo terminaba en 404).
    const respuesta = await fetch(
      `/api/projects/${encodeURIComponent(estado.nota.project)}/notes/${rutaUrl(estado.nota.path)}/pdf`
    );
    if (!respuesta.ok) {
      const error = await respuesta.json().catch(() => ({}));
      throw new Error(error.detail || `error HTTP ${respuesta.status}`);
    }

    const blob = await respuesta.blob();
    const url = URL.createObjectURL(blob);

    const enlace = document.createElement("a");
    enlace.href = url;
    enlace.download = nombreArchivo;
    enlace.hidden = true;
    document.body.append(enlace);
    enlace.click();
    enlace.remove();

    setTimeout(() => URL.revokeObjectURL(url), 1000);
    mostrarToast(null, "Exportar .pdf", "Nota exportada como .pdf.");
  } catch (error) {
    // Mismo criterio que "Exportar .zip": el error va en toast y persiste
    // hasta que lo cierra la X.
    mostrarToast(null, "Exportar .pdf", `No se pudo exportar: ${error.message}`, "error");
  }
}
// ------------------------------------------------------ Compartir en redes

/**
 * Comparte PurpleMD en redes sociales.
 * Usa Web Share API si está disponible; si no, abre modal con opciones.
 */
async function compartirApp() {
  const url = "https://purplemd.onrender.com";
  const texto = "Estoy usando PurpleMD, un editor de Markdown ligero con explorador de proyectos, previsualización en vivo y exportación a PDF 💜";
  const titulo = "PurpleMD — Editor de Markdown ligero";

  if (navigator.share) {
    try {
      await navigator.share({ title: titulo, text: texto, url });
      mostrarToast(null, "Compartir", "¡Gracias por compartir PurpleMD! 💜");
      return;
    } catch (error) {
      if (error.name === "AbortError") return; // Usuario canceló
      // Fallback a método manual
    }
  }

  // Fallback: modal con opciones. Los iconos son SVG estáticos con
  // `fill="currentColor"` (marcas de simple-icons, sobre de Bootstrap
  // Icons): heredan el color del texto y siguen el tema claro/oscuro.
  // El `innerHTML` de acá es markup fijo de este archivo, sin datos de
  // usuario (la regla del proyecto es no interpretar como marcado nada
  // que venga del exterior).
  const codificada = encodeURIComponent(texto);
  const urlCodificada = encodeURIComponent(url);
  const opciones = [
    {
      label: "Copiar enlace",
      url: null,
      icono: '<svg class="compartir-icono" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0z"/></svg>',
      accion: async () => {
        try {
          await navigator.clipboard.writeText(url);
          mostrarToast(null, "Compartir", "¡Enlace copiado al portapapeles! 💜");
        } catch {
          // Sin API de portapapeles (contexto no seguro o permiso denegado).
          mostrarToast(null, "Compartir", "No se pudo copiar el enlace.", "error");
        }
        cleanup();
      },
    },
    {
      label: "X (Twitter)",
      url: `https://x.com/intent/tweet?text=${codificada}&url=${urlCodificada}`,
      icono: '<svg class="compartir-icono" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929 1.329 7.754 11.09h-3.182z"/></svg>',
    },
    {
      label: "LinkedIn",
      url: `https://www.linkedin.com/sharing/share-offsite/?url=${urlCodificada}`,
      icono: '<svg class="compartir-icono" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>',
    },
    {
      label: "Mastodon",
      url: `https://mastodon.social/share?text=${codificada}&url=${urlCodificada}`,
      icono: '<svg class="compartir-icono" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M23.268 5.313c-.35-2.578-2.617-4.61-5.304-5.004C17.51.242 15.792 0 11.813 0h-.03c-3.98 0-4.835.242-5.288.309C3.882.692 1.496 2.518.917 5.127.64 6.412.61 7.837.661 9.143c.074 1.874.088 3.745.26 5.611.118 1.24.325 2.47.62 3.68.55 2.237 2.777 4.098 4.96 4.857 2.336.792 4.849.923 7.256.38.265-.061.527-.132.786-.213.585-.184 1.27-.39 1.774-.753a.057.057 0 0 0 .023-.043v-1.809a.052.052 0 0 0-.02-.041.053.053 0 0 0-.046-.01 20.282 20.282 0 0 1-4.709.545c-2.73 0-3.463-1.284-3.674-1.818a5.593 5.593 0 0 1-.319-1.433.053.053 0 0 1 .066-.054c1.517.363 3.072.546 4.632.546.376 0 .75 0 1.125-.01 1.57-.044 3.224-.124 4.768-.422.038-.008.077-.015.11-.024 2.435-.464 4.753-1.92 4.989-5.604.008-.145.03-1.52.03-1.67.002-.512.167-3.63-.024-5.545zm-3.748 9.195h-2.561V8.29c0-1.309-.55-1.976-1.67-1.976-1.23 0-1.846.79-1.846 2.35v3.403h-2.546V8.663c0-1.56-.617-2.35-1.848-2.35-1.112 0-1.668.668-1.67 1.977v6.218H4.822V8.102c0-1.31.337-2.35 1.011-3.12.696-.77 1.608-1.164 2.74-1.164 1.311 0 2.302.5 2.962 1.498l.638 1.06.638-1.06c.66-.999 1.65-1.498 2.96-1.498 1.13 0 2.043.395 2.74 1.164.675.77 1.012 1.81 1.012 3.12z"/></svg>',
    },
    {
      label: "Email",
      url: `mailto:?subject=${encodeURIComponent(titulo)}&body=${codificada}%0A%0A${urlCodificada}`,
      icono: '<svg class="compartir-icono" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M.05 3.555A2 2 0 0 1 2 2h12a2 2 0 0 1 1.95 1.555L8 8.414zM0 4.697v7.104l5.803-3.558zM6.761 8.83l-6.57 4.027A2 2 0 0 0 2 14h12a2 2 0 0 0 1.808-1.144l-6.57-4.027L8 9.586zm3.436-.586L16 11.801V4.697z"/></svg>',
    },
  ];

  // Crear backdrop semi-transparente (overlay)
  const backdrop = document.createElement("div");
  backdrop.className = "compartir-backdrop";
  backdrop.style.cssText = `
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.4);
    backdrop-filter: blur(2px);
    z-index: 9998;
    animation: fadeIn 0.15s ease-out;
  `;

  // Crear panel modal centrado
  const panel = document.createElement("div");
  panel.className = "accion compartir-panel";
  panel.style.cssText = `
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background: var(--panel);
    border: 1px solid var(--borde);
    border-radius: var(--radio);
    box-shadow: 0 16px 48px rgb(0 0 0 / 0.3);
    padding: 16px;
    z-index: 9999;
    width: min(300px, 90vw);
    max-width: 90vw;
    animation: slideUp 0.2s ease-out;
  `;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  panel.setAttribute("aria-label", "Compartir PurpleMD");

  // Título del modal
  const tituloModal = document.createElement("h3");
  tituloModal.textContent = "Compartir PurpleMD";
  tituloModal.style.cssText = `
    margin: 0 0 12px;
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--texto);
    padding-bottom: 8px;
    border-bottom: 1px solid var(--borde);
  `;
  panel.append(tituloModal);

  // Cierre del modal: se define antes de los botones que lo usan (si no,
  // referenciarlo en su declaración lanza ReferenceError y el modal nunca
  // llega a insertarse en el DOM).
  const cleanup = () => {
    backdrop.remove();
    panel.remove();
    document.removeEventListener("keydown", onKeydown);
  };

  // Escape cierra el modal.
  const onKeydown = (e) => {
    if (e.key === "Escape") cleanup();
  };
  document.addEventListener("keydown", onKeydown);

  // Click en el fondo gris para cerrar.
  backdrop.onclick = cleanup;

  opciones.forEach((opt) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.innerHTML = `${opt.icono}<span>${opt.label}</span>`;
    btn.style.cssText = `
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
      padding: 10px 14px;
      border: none;
      background: transparent;
      color: var(--texto);
      font: inherit;
      font-size: 0.9rem;
      cursor: pointer;
      border-radius: 6px;
      margin: 2px 0;
      transition: background 0.1s;
    `;
    btn.onmouseenter = () => btn.style.background = "var(--acento-suave)";
    btn.onmouseleave = () => btn.style.background = "transparent";
    btn.onclick = opt.accion ?? (() => {
      window.open(opt.url, "_blank", "noopener,noreferrer");
      cleanup();
      mostrarToast(null, "Compartir", "¡Gracias por compartir PurpleMD! 💜");
    });
    panel.append(btn);
  });

  // Botón cerrar
  const btnCerrar = document.createElement("button");
  btnCerrar.type = "button";
  btnCerrar.textContent = "Cancelar";
  btnCerrar.style.cssText = `
    display: block;
    width: 100%;
    padding: 10px 14px;
    margin-top: 8px;
    border: 1px solid var(--borde);
    background: transparent;
    color: var(--texto);
    font: inherit;
    font-size: 0.9rem;
    font-weight: 500;
    text-align: center;
    cursor: pointer;
    border-radius: 6px;
    transition: background 0.1s;
  `;
  btnCerrar.onmouseenter = () => btnCerrar.style.background = "var(--acento-suave)";
  btnCerrar.onmouseleave = () => btnCerrar.style.background = "transparent";
  btnCerrar.onclick = cleanup;
  panel.append(btnCerrar);

  // Insertar en DOM
  document.body.append(backdrop);
  document.body.append(panel);

  // Focus management
  setTimeout(() => panel.querySelector("button").focus(), 0);
}

// ------------------------------------------------------ Preview en vivo

/**
 * Debounce adaptativo según longitud del texto: notas cortas = rápido,
 * notas largas = más tiempo para no saturar.
 * @param {number} textLength - Longitud del markdown en caracteres.
 * @returns {number} Ms de debounce.
 */
function debounceAdaptativo(textLength) {
  if (textLength < 1000) return 120;      // <1KB: casi instantáneo
  if (textLength < 5000) return 200;      // 1-5KB: fluido
  if (textLength < 20000) return 350;     // 5-20KB: equilibrado
  return 500;                              // >20KB: prioriza respuesta
}

/**
 * Programa render con debounce adaptativo + requestIdleCallback.
 * Evita bloquear hilo principal en notas grandes.
 */
function programarPreview() {
  clearTimeout(timerPreview);
  if (!previewVisible()) return;

  const debounceMs = debounceAdaptativo(editor.value.length);

  timerPreview = setTimeout(() => {
    // requestIdleCallback para trabajo no crítico (render preview)
    // fallback a setTimeout si no soportado
    if ('requestIdleCallback' in window) {
      requestIdleCallback(() => renderizarPreview(editor.value), { timeout: 1000 });
    } else {
      renderizarPreview(editor.value);
    }
  }, debounceMs);
}

/**
 * Pide el HTML a POST /api/render y lo muestra en el panel.
 * Cada llamada invalida a las anteriores: una respuesta vieja no pisa
 * el preview de un texto más nuevo.
 * @param {string} texto - Markdown a renderizar.
 */
async function renderizarPreview(texto) {
  const id = ++idRender;
  const cacheado = cacheObtener(texto);
  if (cacheado !== null) {
    aplicarPreview(cacheado, texto);
    return;
  }

  try {
    const datos = await pedir("/api/render", conJson("POST", { markdown: texto }));
    if (id !== idRender) return; // ya se pidió un texto más nuevo
    cacheGuardar(texto, datos.html);
    // Aplicar preview en siguiente frame para no bloquear
    requestAnimationFrame(() => aplicarPreview(datos.html, texto));
  } catch (error) {
    if (id !== idRender) return;
    pintarEstado(renderEstado, "error", `No se pudo renderizar: ${error.message}`);
  }
}

/**
 * Muestra el HTML en el preview preservando el desplazamiento del panel.
 * @param {string} html - HTML devuelto por el backend (allí está saneado).
 * @param {string} texto - Markdown que produjo ese HTML.
 */
function aplicarPreview(html, texto) {
  const desplazamiento = preview.scrollTop;
  preview.innerHTML = html;
  preview.scrollTop = desplazamiento;
  textoRenderizado = texto;
  pintarEstado(renderEstado, "", "");
}

/**
 * Hash simple (djb2) del texto: no es criptografía, solo detecta
 * repeticiones para no repetir el mismo request.
 * @param {string} texto - Markdown a hashear.
 * @returns {string} Hash en base 36.
 */
function hash(texto) {
  let numero = 5381;
  for (let i = 0; i < texto.length; i++) {
    numero = ((numero << 5) + numero + texto.charCodeAt(i)) >>> 0;
  }
  return numero.toString(36);
}

/**
 * Busca el HTML cacheado para ese texto.
 * Se compara el texto completo porque dos textos distintos pueden
 * compartir hash (colisión): sin esa comparación se mostraría HTML viejo.
 * @param {string} texto - Markdown consultado.
 * @returns {string|null} HTML cacheado, o null si no había.
 */
function cacheObtener(texto) {
  const entrada = cacheRender.get(hash(texto));
  return entrada && entrada.texto === texto ? entrada.html : null;
}

/**
 * Guarda un render en la caché, descartando la entrada más vieja
 * al llegar a CACHE_MAX para que la caché no crezca sin límite.
 * @param {string} texto - Markdown renderizado.
 * @param {string} html - HTML resultante.
 */
function cacheGuardar(texto, html) {
  if (cacheRender.size >= CACHE_MAX) {
    cacheRender.delete(cacheRender.keys().next().value);
  }
  cacheRender.set(hash(texto), { texto, html });
}

// -------------------------------------------------------------- Editor

editor.addEventListener("input", () => {
  refrescarGuardado();
  programarPreview();
});

// Tab escribe dos espacios adentro del textarea en vez de mover el foco;
// para salir del editor se usa Shift+Tab, así la navegación con teclado
// sigue siendo posible.
editor.addEventListener("keydown", (evento) => {
  if (evento.key !== "Tab" || evento.shiftKey || evento.ctrlKey || evento.metaKey) return;
  evento.preventDefault();
  insertarEspacios();
});

/** Inserta dos espacios en la selección actual del editor. */
function insertarEspacios() {
  const inicio = editor.selectionStart;
  const fin = editor.selectionEnd;
  editor.value = `${editor.value.slice(0, inicio)}  ${editor.value.slice(fin)}`;
  editor.selectionStart = editor.selectionEnd = inicio + 2;
  editor.dispatchEvent(new Event("input", { bubbles: true }));
}

// ------------------------------------------------------- Barra superior

botonGuardar.addEventListener("click", guardarNota);

// Cada acción se ofrece en dos superficies (menú ☰ en `<48rem` y menú
// «Menú ▾» de la barra en `>=48rem`): un solo juego de manejadores, atados por
// `data-accion`, así las dos caras ejecutan exactamente la misma función.
const accionesCompartidas = {
  descargar: descargarNota,
  pdf: exportarPdf,
  zip: exportarProyecto,
  compartir: compartirApp,
};
for (const [nombre, manejar] of Object.entries(accionesCompartidas)) {
  for (const boton of document.querySelectorAll(`[data-accion="${nombre}"]`)) {
    boton.addEventListener("click", manejar);
  }
}

// Atalaya Ctrl/Cmd+S en toda la página, no solo cuando el foco está en el editor.
window.addEventListener("keydown", (evento) => {
  if (evento.key.toLowerCase() !== "s" || !(evento.ctrlKey || evento.metaKey)) return;
  evento.preventDefault();
  guardarNota();
});

// ------------------------------------------------------ Selector de visualizador

/**
 * Estados de visualizador: `ambos` (editor y previsualización), `preview` (solo
 * previsualización) y `editor` (solo editor). Se eligen en dos superficies con el
 * mismo valor espejo `data-vista`: el menú ☰ (`<48rem`) con tres ítems
 * `menuitemradio` + `aria-checked` (WAI-ARIA APG, patrón «Menu») y el
 * segmentado de la barra (`>=48rem`) con tres `radio` nativos cuyo
 * estado es el `checked` (WAI-ARIA APG, «Radio Group»). No hay ciclo que
 * recorrer, cada opción nombra su estado y solo la vigente queda
 * marcada. Vive solo en memoria: al recargar la página se vuelve a
 * `ambos`, sin persistir nada en `localStorage` (decisión de diseño, no
 * un olvido).
 */

/** ¿`vista` es uno de los tres estados conocidos? */
function esVistaValida(vista) {
  return (
    itemsVista.some((item) => item.dataset.vista === vista) ||
    radiosVista.some((radio) => radio.dataset.vista === vista)
  );
}

/** ¿La previsualización está visible? Con ella oculta no se piden renders. */
function previewVisible() {
  return zona.dataset.vista !== "editor";
}

/** ¿El elemento está en pantalla (no oculto con `display:none`)? */
function elementoVisible(elemento) {
  return elemento.getClientRects().length > 0;
}

/**
 * Scroll y cursor del textarea justo antes de ocultarlo. Firefox
 * descarta el scroll de un textarea con `display:none` (un `div` sí lo
 * conserva), así que se guarda acá y se restaura al mostrarlo.
 * @type {{valor: string, scroll: number, inicio: number, fin: number}|null}
 */
let posicionEditorOculta = null;

/** Guarda scroll y cursor del editor. Se llama justo antes de ocultarlo. */
function guardarPosEditor() {
  posicionEditorOculta = {
    valor: editor.value,
    scroll: editor.scrollTop,
    inicio: editor.selectionStart,
    fin: editor.selectionEnd,
  };
}

/**
 * Restaura lo que guardó `guardarPosEditor`. Se llama después de
 * mostrarlo (recién ahí hay layout y el scroll se puede fijar). Si el
 * texto cambió mientras estuvo oculto (p. ej. se abrió otra nota), no se
 * restaura nada: el estado nuevo es el que manda.
 *
 * El orden importa: primero el cursor y después el scroll. Fijar la
 * selección hace que Firefox programe un desplazamiento hacia el cursor;
 * si el scroll se asigna antes, ese desplazamiento llega después y lo
 * pisa (devuelve la vista al final del texto).
 */
function restaurarPosEditor() {
  const guardada = posicionEditorOculta;
  posicionEditorOculta = null;
  if (!guardada || guardada.valor !== editor.value) return;
  editor.selectionStart = guardada.inicio;
  editor.selectionEnd = guardada.fin;
  editor.scrollTop = guardada.scroll;
}

/**
 * Sincroniza scroll editor <-> preview (proporcional).
 * Solo activo en vista "ambos". Usa RAF para evitar layout thrashing.
 */
let sincronizandoScroll = false;
let scrollRAF = null;

/**
 * Calcula ratio de scroll una vez y lo cachea.
 * @returns {{maxEditor: number, maxPreview: number, ratio: number}|null}
 */
function obtenerMetricasScroll() {
  const maxEditor = editor.scrollHeight - editor.clientHeight;
  const maxPreview = preview.scrollHeight - preview.clientHeight;
  if (maxEditor <= 0 || maxPreview <= 0) return null;
  return { maxEditor, maxPreview, ratio: maxPreview / maxEditor };
}

function sincronizarPreviewDesdeEditor(scrollTop) {
  if (sincronizandoScroll || zona.dataset.vista !== "ambos") return;
  const metricas = obtenerMetricasScroll();
  if (!metricas) return;

  const target = scrollTop * metricas.ratio;
  if (scrollRAF) cancelAnimationFrame(scrollRAF);
  scrollRAF = requestAnimationFrame(() => {
    preview.scrollTop = Math.max(0, Math.min(metricas.maxPreview, target));
  });
}

function sincronizarEditorDesdePreview(scrollTop) {
  if (sincronizandoScroll || zona.dataset.vista !== "ambos") return;
  const metricas = obtenerMetricasScroll();
  if (!metricas) return;

  const target = scrollTop / metricas.ratio;
  if (scrollRAF) cancelAnimationFrame(scrollRAF);
  scrollRAF = requestAnimationFrame(() => {
    editor.scrollTop = Math.max(0, Math.min(metricas.maxEditor, target));
  });
}

function activarScrollSincronizado() {
  if (editor._scrollSyncHandler) return;
  editor._scrollSyncHandler = () => sincronizarPreviewDesdeEditor(editor.scrollTop);
  preview._scrollSyncHandler = () => sincronizarEditorDesdePreview(preview.scrollTop);
  editor.addEventListener("scroll", editor._scrollSyncHandler, { passive: true });
  preview.addEventListener("scroll", preview._scrollSyncHandler, { passive: true });
}

function desactivarScrollSincronizado() {
  if (editor._scrollSyncHandler) {
    editor.removeEventListener("scroll", editor._scrollSyncHandler);
    preview.removeEventListener("scroll", preview._scrollSyncHandler);
    editor._scrollSyncHandler = null;
    preview._scrollSyncHandler = null;
  }
  if (scrollRAF) cancelAnimationFrame(scrollRAF);
  scrollRAF = null;
}

/**
 * Sincroniza las dos superficies con `zona[data-vista]`: `aria-checked`
 * de los `menuitemradio` del menú ☰ y `checked` de los `radio` del
 * segmentado (WAI-ARIA APG: en un menú la selección se refleja con
 * `aria-checked`; en un grupo de radios, con el `checked` nativo —nunca
 * al revés, ni pintado a mano—). Se llama al elegir y al arrancar, para
 * que ambas superficies digan la verdad también tras recargar.
 * @param {string} vista - Valor de `zona.dataset.vista`.
 */
function sincronizarOpcionesVista(vista) {
  for (const item of itemsVista) {
    item.setAttribute("aria-checked", item.dataset.vista === vista ? "true" : "false");
  }
  for (const radio of radiosVista) {
    radio.checked = radio.dataset.vista === vista;
  }
}

/**
 * Muestra el visualizador indicado y sincroniza las dos superficies. Ocultar un
 * panel es solo `display:none` en CSS: el DOM no se toca, así que el
 * textarea conserva texto, cursor y scroll, y el preview lo renderizado.
 * @param {string} vista - `ambos`, `preview` o `editor`.
 */
function aplicarVista(vista) {
  if (!esVistaValida(vista)) return;
  const actual = zona.dataset.vista;
  sincronizarOpcionesVista(vista);
  if (actual === vista) return;
  const ocultandoPreview = vista === "editor";

  // Desactivar scroll sincronizado si salimos de vista "ambos"
  if (actual === "ambos") desactivarScrollSincronizado();

  // Antes de ocultar el editor se guarda su posición; después de
  // mostrarlo (si viene de `preview`) se restaura.
  if (vista === "preview") guardarPosEditor();
  zona.dataset.vista = vista;
  if (actual === "preview") restaurarPosEditor();

  // Activar scroll sincronizado si entramos en vista "ambos"
  if (vista === "ambos") activarScrollSincronizado();

  // Con la vista previa oculta no se pide nada: se cancela hasta el
  // render que esperaba al debounce.
  if (ocultandoPreview) clearTimeout(timerPreview);
  // Al volver a mostrarla, render recién si hay cambios pendientes
  // (`textoRenderizado` es lo último que se puso en pantalla).
  if (actual === "editor" && estado.nota && editor.value !== textoRenderizado) {
    renderizarPreview(editor.value);
  }
}

// Cada opción del menú ☰ aplica su vista. El cierre del menú y la
// devolución del foco los hace el oyente del panel, común a los seis
// ítems (ver «Menú overflow», más abajo).
for (const item of itemsVista) {
  item.addEventListener("click", () => aplicarVista(item.dataset.vista));
}

// El segmentado de la barra hace lo mismo con el `change` nativo del
// radio: sin ARIA a mano, el estado es el `checked` del input y la
// sincronización con `zona[data-vista]` va por la misma `aplicarVista`.
for (const radio of radiosVista) {
  radio.addEventListener("change", () => aplicarVista(radio.dataset.vista));
}

// ------------------------------------------------- Desplegable del explorador

/** ¿El desplegable del explorador está abierto? */
function exploradorAbierto() {
  return explorador.classList.contains("abierto");
}

/**
 * Fija `--topbar-alto` con la altura real de la barra superior: tiene
 * `flex-wrap` y en pantallas angostas puede ocupar dos filas, así que
 * el desplegable no puede asumir un alto fijo.
 */
function actualizarTopbarAlto() {
  const alto = document.querySelector(".topbar").offsetHeight;
  document.documentElement.style.setProperty("--topbar-alto", `${alto}px`);
}

/**
 * Abre o cierra el desplegable y sincroniza el botón: el texto es fijo
 * («Explorador») y `aria-expanded` refleja el estado.
 */
function alternarExplorador() {
  if (exploradorAbierto()) {
    cerrarExplorador();
    return;
  }
  explorador.classList.add("abierto");
  actualizarTopbarAlto();
  botonExplorador.setAttribute("aria-expanded", "true");
}

/**
 * Cierra el desplegable y deja el botón en su estado inicial. En
 * pantallas anchas no tiene efecto visible (el CSS abierto está scoped
 * a angosto y el botón está oculto), pero se llama igual desde
 * `abrirNota` para no dejar el estado a medias.
 */
function cerrarExplorador() {
  explorador.classList.remove("abierto");
  botonExplorador.setAttribute("aria-expanded", "false");
}

/**
 * Cierra el desplegable solo en pantallas angostas: al abrir una nota
 * el usuario pasa a ver el editor. Cambiar de proyecto no cierra el
 * desplegable (el usuario quiere ver el árbol del nuevo proyecto). En
 * anchas el explorador siempre está visible y no hay clase que quitar.
 */
function cerrarExploradorSiAngosto() {
  if (window.matchMedia("(max-width: 60rem)").matches) cerrarExplorador();
}

// Un solo oyente por botón: dos oyentes sobre el mismo botón alternarían
// dos veces por toque y el desplegable abriría y cerraría de inmediato.
botonExplorador.addEventListener("click", alternarExplorador);

// Menú overflow: superficie angosta (< 48rem) de visualizador y archivo
function alternarMenuOverflow() {
  const abierto = menuOverflowPanel.hidden === false;
  if (abierto) {
    cerrarMenuOverflow();
  } else {
    abrirMenuOverflow();
  }
}

function abrirMenuOverflow() {
  // El panel cae justo debajo de la topbar: hay que medirla ahora, porque
  // en pantallas angostas puede cambiar de una fila a dos sin que llegue
  // un `resize` (p. ej. aparece o desaparece el badge del namespace).
  actualizarTopbarAlto();
  menuOverflowPanel.hidden = false;
  menuOverflowTrigger.setAttribute("aria-expanded", "true");
  // Cerrar al hacer click fuera (con pequeño delay para no cerrar inmediatamente)
  setTimeout(() => {
    document.addEventListener("click", clickFueraMenuOverflow, { once: true });
  }, 0);
}

function cerrarMenuOverflow() {
  menuOverflowPanel.hidden = true;
  menuOverflowTrigger.setAttribute("aria-expanded", "false");
}

function clickFueraMenuOverflow(evento) {
  if (!menuOverflow.contains(evento.target)) {
    cerrarMenuOverflow();
  } else {
    setTimeout(() => {
      document.addEventListener("click", clickFueraMenuOverflow, { once: true });
    }, 0);
  }
}

// Un solo oyente por botón: un toque/clic tiene que alternar una única vez.
menuOverflowTrigger.addEventListener("click", alternarMenuOverflow);

// Al activar cualquier ítem del menú, este se cierra y el foco vuelve al
// trigger (WAI-ARIA APG, patrón «Menu Button»: un menú se cierra al
// activar un ítem y al pulsar `Escape`, devolviendo el foco al control que
// lo abrió). Va en el panel (burbuja) para correr después del oyente
// propio de cada ítem —que aplica la vista o dispara la exportación— y
// antes de que el clic salga hacia `document`.
menuOverflowPanel.addEventListener("click", (evento) => {
  const item = evento.target.closest("[role='menuitem'], [role='menuitemradio']");
  if (!item) return;
  cerrarMenuOverflow();
  menuOverflowTrigger.focus();
});

// -------------------------------------------------- Menú «Menú ▾» (barra)

// Superficie ancha (>= 48rem) de las acciones: exportar, compartir y
// repo. Mismo ciclo de vida que el menú ☰ (WAI-ARIA APG, patrón
// «Menu Button»): alternar con el trigger, clic fuera cierra, `Escape`
// cierra y devuelve el foco al trigger, y activar un ítem cierra y
// devuelve el foco. En `<48rem` este menú está oculto y las mismas
// acciones viven en el menú ☰.

/** ¿El menú «Menú ▾» está abierto? */
function menuAccionesAbierto() {
  return !menuAccionesPanel.hidden;
}

function alternarMenuAcciones() {
  if (menuAccionesAbierto()) cerrarMenuAcciones();
  else abrirMenuAcciones();
}

function abrirMenuAcciones() {
  menuAccionesPanel.hidden = false;
  menuAccionesTrigger.setAttribute("aria-expanded", "true");
  // Cerrar al hacer click fuera (con pequeño delay para no cerrar
  // inmediatamente), igual que el menú ☰.
  setTimeout(() => {
    document.addEventListener("click", clickFueraMenuAcciones, { once: true });
  }, 0);
}

function cerrarMenuAcciones() {
  menuAccionesPanel.hidden = true;
  menuAccionesTrigger.setAttribute("aria-expanded", "false");
}

function clickFueraMenuAcciones(evento) {
  if (!menuAcciones.contains(evento.target)) {
    cerrarMenuAcciones();
  } else {
    setTimeout(() => {
      document.addEventListener("click", clickFueraMenuAcciones, { once: true });
    }, 0);
  }
}

// Un solo oyente por botón: un toque/clic tiene que alternar una única vez.
menuAccionesTrigger.addEventListener("click", alternarMenuAcciones);

// Al activar un ítem, el menú se cierra y el foco vuelve al trigger. Va en
// el panel (burbuja) para correr después del oyente propio del ítem —que
// dispara la exportación— y antes de que el clic salga hacia `document`.
menuAccionesPanel.addEventListener("click", (evento) => {
  // El checkbox entra en el selector: si no, al alternarlo el menú no se
  // cierra ni devuelve el foco al trigger.
  const item = evento.target.closest("[role='menuitem'], [role='menuitemcheckbox']");
  if (!item) return;
  cerrarMenuAcciones();
  menuAccionesTrigger.focus();
});

// Escape cierra menú «Menú ▾», menú overflow y explorador
window.addEventListener("keydown", (evento) => {
  if (evento.key !== "Escape" || evento.defaultPrevented) return;
  if (menuAccionesAbierto()) {
    evento.preventDefault();
    cerrarMenuAcciones();
    menuAccionesTrigger.focus();
    return;
  }
  if (!menuOverflowPanel.hidden) {
    evento.preventDefault();
    cerrarMenuOverflow();
    menuOverflowTrigger.focus();
    return;
  }
  const foco = document.activeElement;
  if (foco && foco.closest("[data-accion-panel]")) return;
  if (!exploradorAbierto()) return;
  evento.preventDefault();
  cerrarExplorador();
  botonExplorador.focus();
});

// ----------------------------------------- Reglas de corte (48rem)

/** Último control de `.acciones` que recibió el foco. */
let focoAcciones = null;

document.addEventListener("focusin", (evento) => {
  const destino = evento.target;
  focoAcciones = destino instanceof Element && destino.closest(".acciones") ? destino : null;
});

/**
 * Primer control enfocable visible de `.acciones`, en orden DOM.
 * @returns {HTMLElement|null} El control, o null si no queda ninguno.
 */
function primerControlAcciones() {
  const controles = accionesBarra.querySelectorAll("button, input");
  for (const control of controles) {
    if (control.disabled) continue;
    if (control.tabIndex < 0) continue;
    if (!elementoVisible(control)) continue;
    return control;
  }
  return null;
}

/**
 * Tras cruzar el corte de 48rem, si el foco quedó en un control que el
 * cambio ocultó (o el navegador lo perdió al `body` al ponerlo en
 * `display:none`), lo lleva al primer control enfocable visible de
 * `.acciones` en orden DOM: el foco nunca queda en un elemento oculto
 * (WCAG 2.4.3, «Foco visible»).
 */
function moverFocoTrasCorte() {
  // Si el documento está sin foco (ventana en segundo plano) el navegador
  // no emite `focusin`, así que `focoAcciones` puede quedar desfasado: en
  // ese caso manda `document.activeElement`, siempre que el control con
  // el foco esté en `.acciones` (si no, el foco está en otra parte y no
  // se toca).
  const activa = document.activeElement;
  const enAcciones = activa instanceof Element && activa.closest(".acciones")
    ? activa
    : null;
  const antes = enAcciones || focoAcciones;
  if (!antes) return;
  // Leer los rectángulos fuerza el recálculo de layout: con los estilos
  // del nuevo corte ya aplicados, un control oculto no tiene ninguno.
  if (elementoVisible(antes)) return;
  const foco = document.activeElement;
  if (foco && foco !== document.body && foco !== antes) return;
  const destino = primerControlAcciones();
  if (destino) destino.focus();
}

// Corte único en 48rem: una media query muestra la barra y oculta el ☰;
// al cruzar el corte, además se cierra el menú que quedó del lado opuesto
// y se reubica el foco. El resto del resize mide `--topbar-alto` (la
// topbar puede pasar a dos filas) y refresca badge y desplegable.
let corteAncho = window.matchMedia("(min-width: 48rem)").matches;

window.addEventListener("resize", () => {
  const ancho = window.matchMedia("(min-width: 48rem)").matches;
  // (1) menú «Menú ▾» abierto → bajar de 48rem lo cierra.
  if (!ancho && menuAccionesAbierto()) cerrarMenuAcciones();
  // (2) menú ☰ abierto → subir a >= 48rem lo cierra.
  if (ancho && !menuOverflowPanel.hidden) cerrarMenuOverflow();
  // (3) el foco en un control recién oculto pasa al primer control
  // enfocable visible de `.acciones` (solo al cruzar el corte).
  if (ancho !== corteAncho) {
    corteAncho = ancho;
    moverFocoTrasCorte();
  }
  // El badge se actualiza antes de medir: aparecer o desaparecer cambia
  // el alto de la topbar (puede pasar de una fila a dos), así que medir
  // antes dejaría `--topbar-alto` desfasado para el desplegable.
  actualizarNamespaceBadge();
  // Los dos desplegables (explorador y menú overflow) caen debajo de la
  // topbar con `--topbar-alto`: se re-mide en cada resize, con o sin
  // desplegable abierto, porque la topbar cambia de alto sola.
  if (!window.matchMedia("(max-width: 60rem)").matches) cerrarExplorador();
  actualizarTopbarAlto();
});

// Asegurar que --topbar-alto esté siempre disponible (fallback por si falla el JS inicial)
if (!document.documentElement.style.getPropertyValue("--topbar-alto")) {
  document.documentElement.style.setProperty("--topbar-alto", "3.5rem");
}

// -------------------------------------------------------------- Inicio

// ------------------------------------------------------ Notificaciones

/** Milisegundos que vive un toast de éxito (Material 3 Snackbar: 4–10 s). */
const TOAST_MS = 6000;
/** Tope de toasts apilados en pantalla (react-toastify / sonner). */
const TOAST_TOPE = 3;
/** Auto-cierre pendiente de cada toast en pantalla, por elemento. */
const timersToast = new Map();

/**
 * Consulta las notificaciones pendientes y las muestra como toast.
 * Van en tono `ok`: el backend solo avisa logros.
 * Se llama al cargar la página y cada 30 segundos.
 */
async function cargarNotificaciones() {
  try {
    const datos = await pedir("/api/notifications");
    for (const notif of datos.notifications) {
      mostrarToast(notif.id, notif.titulo, notif.mensaje);
    }
  } catch (_) {
    // Si el endpoint no existe o hay error de red, no se muestra nada.
  }
}

/**
 * Auto-cierre de un toast de éxito con pausa por hover y por foco
 * (WCAG 2.2.1 + técnica G4; igual que react-toastify y sonner): entrar
 * con el puntero o con el foco congela el timer y salir reanuda CON EL
 * TIEMPO RESTANTE, nunca desde cero. El timer recién corre cuando el
 * usuario se retira de las dos superficies.
 *
 * @param {HTMLElement} toast - Toast que se auto-cierra.
 * @param {() => void} alCerrar - Rutina que retira el toast.
 * @returns {() => void} Cancela el timer pendiente (lo usa la X).
 */
function programarAutoCierre(toast, alCerrar) {
  let restante = TOAST_MS;
  let inicio = 0;
  let timer = 0;
  let encima = false;
  let enfocado = false;

  const arrancar = () => {
    if (timer || !toast.isConnected) return;
    inicio = performance.now();
    timer = setTimeout(() => {
      timer = 0;
      alCerrar();
    }, restante);
  };

  const congelar = () => {
    if (!timer) return;
    clearTimeout(timer);
    timer = 0;
    restante = Math.max(0, restante - (performance.now() - inicio));
  };

  const sincronizar = () => {
    if (encima || enfocado) congelar();
    else arrancar();
  };

  toast.addEventListener("mouseenter", () => {
    encima = true;
    sincronizar();
  });
  toast.addEventListener("focusin", () => {
    enfocado = true;
    sincronizar();
  });
  toast.addEventListener("mouseleave", () => {
    encima = false;
    sincronizar();
  });
  toast.addEventListener("focusout", () => {
    enfocado = false;
    sincronizar();
  });
  arrancar();

  return () => {
    if (timer) clearTimeout(timer);
    timer = 0;
  };
}

/**
 * Cierra un toast: cancela su auto-cierre, lo quita del DOM y marca la
 * notificación como leída. Los avisos locales llevan `id` `null` (no
 * están en `dataset.notif`), así que no se toca el backend.
 * @param {HTMLElement} toast - Toast a retirar.
 */
function quitarToast(toast) {
  const cancelar = timersToast.get(toast);
  if (cancelar) cancelar();
  timersToast.delete(toast);
  toast.remove();
  marcarLeida(toast.dataset.notif ?? null);
}

/**
 * Respeta el tope de TOAST_TOPE toasts apilados: al superarlo se
 * descarta el más viejo que NO sea error (Carbon: el error persiste
 * hasta resolverse) y, si los que están en pantalla son todos error, el
 * más viejo. Se llama antes de agregar el nuevo, así que el toast
 * recién creado nunca se descarta a sí mismo.
 * @param {HTMLElement} contenedor - Contenedor `#toasts`.
 */
function limitarToasts(contenedor) {
  while (contenedor.children.length >= TOAST_TOPE) {
    const toasts = [...contenedor.children];
    let victima = null;
    for (let i = toasts.length - 1; i >= 0; i--) {
      if (!toasts[i].classList.contains("toast-error")) {
        victima = toasts[i];
        break;
      }
    }
    quitarToast(victima || toasts[toasts.length - 1]);
  }
}

/**
 * Segundo paso de la creación de un toast: escribe el texto recién en el
 * próximo frame, para que el navegador registre primero la región viva
 * vacía (WCAG 2.2 SC 4.1.3, técnicas ARIA22/ARIA19: si la región y el
 * texto llegan juntos, los lectores pueden no anunciar nada). Si el frame
 * no llega —una pestaña en segundo plano frena `requestAnimationFrame`—
 * un timer de respaldo completa el paso.
 *
 * @param {HTMLElement} toast - Toast ya insertado, todavía vacío.
 * @param {() => void} rellenar - Rutina que escribe título y mensaje.
 */
function rellenarToast(toast, rellenar) {
  let hecho = false;
  const paso = () => {
    if (hecho || !toast.isConnected) return;
    hecho = true;
    rellenar();
  };
  requestAnimationFrame(paso);
  setTimeout(paso, 120);
}

/**
 * Muestra un toast apilado en `#toasts`: la más reciente arriba y con un
 * tope de TOAST_TOPE en pantalla. Nunca roba el foco.
 *
 * Dos tonos, dos duraciones (regla de UI/UX: éxito efímero, error
 * persistente junto a su control):
 *
 * - `ok` (por omisión): `role="status"` con `aria-live="polite"` y
 *   auto-cierre a los 6 s, pausado por hover y por foco.
 * - `error`: `role="alert"` —ya es asertivo por ARIA, sin `aria-live`
 *   adicional— y SIN auto-cierre: solo lo cierra la X. Su superficie es
 *   la barra ☰/Exportar, que puede estar cerrada.
 *
 * @param {string|null} id - ID de la notificación; `null` para avisos
 *   locales de la app (operaciones y exportaciones), que no hay que
 *   marcar como leídos.
 * @param {string} titulo - Título del toast (etiqueta de la acción).
 * @param {string} mensaje - Mensaje del toast.
 * @param {"ok"|"error"} [tono] - Éxito transitorio o error persistente.
 * @returns {HTMLElement} El toast, por si hay que cerrarlo antes (p. ej.
 *   el «Exportando…» cuando llega el resultado).
 */
function mostrarToast(id, titulo, mensaje, tono = "ok") {
  const contenedor = document.getElementById("toasts");
  const esError = tono === "error";

  limitarToasts(contenedor);

  const toast = document.createElement("div");
  toast.className = esError ? "toast toast-error" : "toast";
  toast.setAttribute("role", esError ? "alert" : "status");
  if (!esError) toast.setAttribute("aria-live", "polite");
  if (id !== null && id !== undefined) toast.dataset.notif = String(id);
  // Apilado newest-on-top: el contenedor flex apila de arriba hacia abajo.
  contenedor.prepend(toast);

  // Paso 1: la región viva ya está en el árbol, todavía vacía.
  const tituloEl = document.createElement("strong");
  const mensajeEl = document.createElement("p");
  const cerrar = document.createElement("button");
  cerrar.type = "button";
  cerrar.className = "btn";
  cerrar.textContent = "X";
  cerrar.setAttribute("aria-label", "Cerrar notificación");
  cerrar.addEventListener("click", () => quitarToast(toast));
  toast.append(tituloEl, mensajeEl, cerrar);

  // Paso 2: recién ahí se escribe el mensaje y arranca su auto-cierre.
  rellenarToast(toast, () => {
    tituloEl.textContent = titulo;
    mensajeEl.textContent = mensaje;
    // El error no tiene timer: vive hasta que lo cierra la X.
    if (!esError) timersToast.set(toast, programarAutoCierre(toast, () => quitarToast(toast)));
  });

  return toast;
}

/**
 * Marca una notificación como leída en el backend. Los avisos locales
 * (operaciones y exportaciones) se crean sin `dataset.notif`: no hay
 * notificación que marcar, así que no se toca el backend.
 * @param {string|null} id - ID de la notificación, o `null` si es local.
 */
async function marcarLeida(id) {
  if (id === null) return;
  try {
    await pedir(`/api/notifications/${id}/read`, { method: "POST" });
  } catch (_) {
    // Si falla el marcado, no pasa nada: el toast ya se cerró.
  }
}

/**
 * Inicializa la toolbar Markdown estilo Office en el editor.
 * Inserta sintaxis Markdown en la posición del cursor.
 */
function inicializarToolbar() {
  const toolbar = document.querySelector('.editor-toolbar');
  const editor = document.getElementById('editor');
  if (!toolbar || !editor) return;

  // Mapeo de botones a sintaxis Markdown
  const formatos = {
    heading1: { prefix: '# ', suffix: '' },
    heading2: { prefix: '## ', suffix: '' },
    heading3: { prefix: '### ', suffix: '' },
    bold: { prefix: '**', suffix: '**' },
    italic: { prefix: '*', suffix: '*' },
    strikethrough: { prefix: '~~', suffix: '~~' },
    code: { prefix: '`', suffix: '`' },
    codeblock: { prefix: '```\n', suffix: '\n```' },
    quote: { prefix: '> ', suffix: '' },
    ul: { prefix: '- ', suffix: '' },
    ol: { prefix: '1. ', suffix: '' },
    task: { prefix: '- [ ] ', suffix: '' },
    link: { prefix: '[', suffix: '](url)' },
    image: { prefix: '![', suffix: '](url)' },
    table: { prefix: '| Col1 | Col2 |\n|------|------|\n| ', suffix: ' | |\n|  |  |' },
    hr: { prefix: '\n---\n', suffix: '' },
    math: { prefix: '$$', suffix: '$$' }
  };

  // Mostrar toolbar cuando hay nota activa
  const originalSeleccionarNota = window.seleccionarNota || (() => {});
  // Hook: cuando se habilita el editor, mostramos la toolbar
  const observer = new MutationObserver(() => {
    const habilitado = !editor.disabled;
    toolbar.hidden = !habilitado;
  });
  observer.observe(editor, { attributes: true, attributeFilter: ['disabled'] });
  toolbar.hidden = editor.disabled;

  toolbar.addEventListener('click', (e) => {
    const btn = e.target.closest('.tool-btn[data-md]');
    if (!btn) return;
    const fmt = btn.dataset.md;
    const f = formatos[fmt];
    if (!f) return;

    const { prefix, suffix } = f;
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const seleccion = editor.value.slice(start, end);
    const nuevoTexto = prefix + seleccion + suffix;

    // execCommand('insertText') preserva undo stack nativo
    editor.focus();
    document.execCommand('insertText', false, nuevoTexto);

    // Posicionar cursor según formato SIN romper undo:
    // - Si había selección: la selecciona (comportamiento nativo de insertText)
    // - Si no había selección:
    //   - Inline (bold, italic, code, strikethrough): cursor al final (entre prefix/suffix)
    //   - Block (headings, quote, listas, hr, codeblock): cursor después del prefix
    //   - Link/image/math/table: placeholder seleccionado (usuario escribe y reemplaza)
    if (!seleccion) {
      const isBlock = fmt === 'heading1' || fmt === 'heading2' || fmt === 'heading3' ||
                      fmt === 'quote' || fmt === 'ul' || fmt === 'ol' || fmt === 'task' ||
                      fmt === 'hr' || fmt === 'codeblock';
      const isInline = fmt === 'bold' || fmt === 'italic' || fmt === 'strikethrough' || fmt === 'code';

      if (isBlock) {
        // Block: mover cursor DESPUÉS del prefix (ej: después de "# ")
        // Usamos setRangeText con 'end' SOLO para mover cursor, no para insertar
        // Esto es una operación separada pero necesaria para UX
        const newStart = start + prefix.length;
        editor.setRangeText('', newStart, newStart, 'end');
      } else if (isInline) {
        // Inline: cursor ENTRE prefix y suffix (ej: **|**)
        const newStart = start + prefix.length;
        const newEnd = start + nuevoTexto.length - suffix.length;
        editor.setRangeText('', newStart, newEnd, 'select');
      }
      // link/image/math/table: deja placeholder seleccionado (comportamiento nativo)
    }

    // Actualizar UI en microtask: sin evento sintético = undo preservado
    Promise.resolve().then(() => {
      refrescarGuardado();
      programarPreview();
    });
  });
}

// ---------------------------------------------------------- Bienvenida
// Nota de entrada del producto: se crea solo si falta y es la que se
// muestra por defecto en cada arranque. Nunca se reescribe, así que el
// usuario puede editarla o vaciarla y su texto sobrevive.

const PROYECTO_BIENVENIDA = "Bienvenida";
const NOTA_BIENVENIDA = "nota-de-bienvenida";

const CONTENIDO_BIENVENIDA = `# ¡Hola! Bienvenido/a a PurpleMD 💜

 Tomate un minuto para leer esta nota: te cuenta lo más importante para empezar. Después, hacela tuya: podés vaciarla o escribir encima.

 ## Cómo se usa

 PurpleMD tiene dos paneles:

 - En **Desktop**, escribís a la **izquierda** y ves cómo queda a la **derecha**.
- En **Mobile**, escribís **arriba** y ves la vista previa **abajo**.

 La vista previa se actualiza sola apenas dejás de tipear.

 Solo tené presente algo importante: **no hay autoguardado**. Para guardar lo que escribiste, apretá **«Guardar»** o usá \`Ctrl\`/\`Cmd\` + \`S\`.

 ## Tus primeros pasos

 1. En **Desktop**, usá el panel izquierdo. En **Mobile**, abrí el **Explorador** con el botón correspondiente.
2. En **«Proyecto nuevo»**, escribí un nombre y apretá **«Crear»**. Un proyecto es tu espacio de trabajo: puede ser para trabajo, recetas, ideas o lo que quieras.
3. Con el proyecto seleccionado, creá tu primera nota desde **«Nota nueva (ruta)»**. Podés organizarla en carpetas, por ejemplo: \`recetas/tortas\`.
4. Escribí tranquilo: mientras no aprietes **«Guardar»**, los cambios no se guardan.

 ## Qué podés escribir

 Markdown te permite usar títulos, listas, casillas para tareas, **negrita**, _cursiva_, \`código\`, ~~texto tachado~~, citas y hasta tablas.

 La barra de herramientas que aparece arriba del editor hace la mayor parte del trabajo por vos.

 | Atajo | Qué hace |
| --- | --- |
| \`Ctrl\`/\`Cmd\` + \`S\` | Guarda lo que escribiste |
| \`Tab\` | Inserta dos espacios |
| \`Escape\` | Cierra lo que esté abierto |

> Un consejo queda así, escribiendo \`>\` al principio.

 ## Llevátelo con vos

 - **«Menú ▾» → «Descargar .md»** descarga la nota tal cual está.
- **«Menú ▾» → «Exportar .pdf»** convierte la nota en PDF.
- **«Menú ▾» → «Exportar .zip»** exporta el proyecto entero.

 ## Plantillas para arrancar más rápido

 En el explorador vas a encontrar el proyecto **«Plantillas»**, con documentos listos para copiar, completar y exportar a PDF:

 - **empresas/**: propuesta comercial, presupuesto, contrato de servicios, informe técnico, ficha de cliente y orden de trabajo.
 - **clientes/**: CV, carta de presentación, apuntes de estudio, presupuesto, detalle de cobro y guía paso a paso.

 Los campos a completar van entre corchetes, por ejemplo \`[FECHA]\` o \`[MONTO]\`. Abrí la que te sirva, hacé una copia en tu proyecto y rellená. Si editás o borrás alguna en «Plantillas», se respeta: no vuelve a crearse.

 ## Unas cositas más

 - **Sin cuentas ni registro:** cada navegador tiene su propio espacio, así que tus datos no se mezclan con los de otra persona.
- **Sin buscador (por ahora):** para moverte entre tus notas, usá el árbol del Explorador.
- **Sin sincronización entre equipos:** cada equipo tiene su propio espacio.

 ## Si querés apoyar el proyecto

 Si PurpleMD te sirvió, hay un par de maneras fáciles de darle una mano:

 - **Compartilo:** **«Compartir PurpleMD»**, disponible en el menú ☰ y también en **«Menú ▾»**, te permite compartir PurpleMD por X, LinkedIn, Mastodon o correo. También podés pasarle el link a quien creas que le pueda servir. ¿Querés compartir _tu_ proyecto en lugar del editor? Usá **«Menú ▾» → «Exportar .zip»** y mandale el archivo.
 - **Contribuí:** si sabés programar, documentar, traducir o testear, mirá [\`CONTRIBUTING.md\`](https://github.com/ltrecanao/purplemd/blob/main/CONTRIBUTING.md) en GitHub para ver cómo sumar código, reportar bugs o proponer mejoras. El repo está en [github.com/ltrecanao/purplemd](https://github.com/ltrecanao/purplemd) — también lo tenés en el menú ☰ → «Ver en GitHub».

 ## Cuando ya no la necesites

 Esta nota es solo una bienvenida. Cuando quieras, vaciala y escribí la tuya: si queda vacía, PurpleMD no va a volver a llenarla.

 Y si borrás el proyecto **«Bienvenida»**, se va a crear de nuevo la próxima vez que abras PurpleMD.
`;

/**
 * Comprueba si un recurso de la API responde.
 * @param {string} ruta - Ruta absoluta de la API.
 * @returns {Promise<boolean>} `true` si responde OK; `false` si da 404
 *   (o si la lectura falla por completo, que en ese caso lo decide la
 *   operación de creación siguiente).
 */
async function existeRecurso(ruta) {
  try {
    await pedir(ruta);
    return true;
  } catch (_) {
    return false;
  }
}

/**
 * Crea el proyecto «Bienvenida» y la nota «primeros-pasos» si faltan.
 *
 * Es idempotente y no destructiva: si el proyecto o la nota ya existen,
 * no se les toca el contenido (el usuario puede editarlos). Sirve tanto
 * con `PURPLEMD_STORAGE=memory` (donde la semilla se recrea en cada
 * arranque) como con `filesystem`.
 *
 * @returns {Promise<boolean>} `true` si la semilla está completa: hay
 *   que seleccionarla y abrirla.
 */
async function asegurarBienvenida() {
  const base = `/api/projects/${encodeURIComponent(nsProject(PROYECTO_BIENVENIDA))}`;
  const rutaNota = `${base}/notes/${rutaUrl(NOTA_BIENVENIDA)}`;
  let creóAlgo = false;

  if (!(await existeRecurso(`${base}/tree`))) {
    try {
      await pedir("/api/projects", conJson("POST", { name: nsProject(PROYECTO_BIENVENIDA) }));
      creóAlgo = true;
    } catch (_) {
      // 409 (alguien lo creó entre medio) u otro fallo: lo resuelve la
      // comprobación de la lista de abajo.
    }
  }

  let hayNota = await existeRecurso(rutaNota);
  if (!hayNota) {
    try {
      await pedir(
        `${base}/notes`,
        conJson("POST", { path: NOTA_BIENVENIDA, content: CONTENIDO_BIENVENIDA }),
      );
      hayNota = true;
      creóAlgo = true;
    } catch (_) {
      // 409 (ya existe) u otro fallo: idem.
    }
  }

  // Recién creada, la lista hay que refrescarla para que el proyecto
  // aparezca en el explorador antes de seleccionarlo.
  if (creóAlgo) await cargarProyectos();

  return hayNota && estado.proyectos.some((p) => p.name === nsProject(PROYECTO_BIENVENIDA));
}

// ------------------------------------------------------------- Plantillas
// Documentos de ejemplo (propuesta, presupuesto, CV, guías) que viven como
// recursos .md en `plantillas/`, servidos por /plantillas. El manifiesto
// `plantillas/indice.json` es el que enumera qué copiar: agregar una
// plantilla es dropear el archivo y sumarlo ahí, sin tocar este código.
// Mismo criterio que la bienvenida: idempotente y no destructiva, las
// notas que el usuario editó (o borró) no se vuelven a crear.

const MANIFIESTO_PLANTILLAS = "/plantillas/indice.json";

/**
 * Carga las plantillas de `plantillas/indice.json` en su proyecto.
 *
 * Pide el árbol una sola vez y solo crea las notas que falten: en cada
 * arranque son tres requests (manifiesto, proyecto, árbol) y ninguna
 * escritura si ya están todas.
 *
 * @returns {Promise<void>}
 */
async function asegurarPlantillas() {
  let manifiesto;
  try {
    manifiesto = await pedir(MANIFIESTO_PLANTILLAS);
  } catch (_) {
    return; // Sin manifiesto (instalación mínima) no hay nada que sembrar.
  }
  const proyecto = manifiesto.proyecto;
  const rutas = manifiesto.plantillas;
  if (!proyecto || !Array.isArray(rutas) || rutas.length === 0) return;

  const base = `/api/projects/${encodeURIComponent(nsProject(proyecto))}`;
  if (!(await existeRecurso(`${base}/tree`))) {
    try {
      await pedir("/api/projects", conJson("POST", { name: nsProject(proyecto) }));
    } catch (_) {
      return; // 409 u otro fallo: sin proyecto no se puede sembrar.
    }
  }

  // Árbol actual: lo que ya existe no se toca (ni se descarga).
  let existentes = new Set();
  try {
    const arbol = await pedir(`${base}/tree`);
    existentes = new Set(arbol.entries.filter((e) => e.type === "note").map((e) => e.path));
  } catch (_) {
    return;
  }

  let creóAlgo = false;
  for (const ruta of rutas) {
    if (existentes.has(ruta)) continue;
    try {
      // El .md es texto plano, no JSON: `pedir` no sirve acá.
      const origen = await fetch(`/plantillas/${rutaUrl(`${ruta}.md`)}`);
      if (!origen.ok) continue;
      const contenido = await origen.text();
      await pedir(`${base}/notes`, conJson("POST", { path: ruta, content: contenido }));
      creóAlgo = true;
    } catch (_) {
      // 409 (alguien la creó entre medio) u otro fallo: se omite y listo.
    }
  }

  // Recién creada, la lista hay que refrescarla para que el proyecto
  // aparezca en el explorador (sin deseleccionar el que está abierto).
  if (creóAlgo) await cargarProyectos();
}

async function iniciar() {
  inicializarNamespaceBadge();
  actualizarTopbarAlto(); // Fijar --topbar-alto antes de cualquier dropdown
  // Las dos superficies del visualizador (menú ☰ y segmentado de la barra)
  // contra `zona[data-vista]`: al recargar tiene que mostrar «Editor y
  // previsualización», el estado inicial.
  sincronizarOpcionesVista(zona.dataset.vista);
  // Activar scroll sincronizado si la vista inicial es "ambos"
  if (zona.dataset.vista === "ambos") activarScrollSincronizado();
  inicializarToolbar(); // Toolbar Markdown estilo Office
  refrescarGuardado();
  refrescarHabilitacion();
  const proyectos = await cargarProyectos();
  // La nota de bienvenida es la que se muestra por defecto: es el
  // primer contacto con el producto y explica el resto.
  if (await asegurarBienvenida()) {
    if (await seleccionarProyecto(PROYECTO_BIENVENIDA)) {
      await abrirNota(NOTA_BIENVENIDA);
    }
  } else if (proyectos.length) {
    // Sin semilla (p. ej. la API no respondió): el proyecto más reciente
    // y ninguna nota abierta, como hasta ahora.
    await seleccionarProyecto(stripNs(proyectos[0].name));
  }
  // Las plantillas van después de la bienvenida para no robarle el foco:
  // solo aparecen en el explorador, sin seleccionarse ni abrirse.
  await asegurarPlantillas();
  cargarNotificaciones();
  setInterval(cargarNotificaciones, 30000);
}

iniciar();
