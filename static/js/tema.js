/* Tema claro/oscuro: se resuelve y se aplica ANTES del primer pintado.
 *
 * Va como `<script src>` clásico en el `<head>` (la CSP del backend
 * permite `script-src 'self'`, no inline). Si esperara a `app.js` —que
 * es un módulo diferido— el tema se pintaría después y habría un
 * destello del color opuesto cuando la elección guardada difiere del
 * sistema.
 *
 * Una sola clave en `localStorage`: `purplemd_tema`, con `claro` u
 * `oscuro`. Sin clave (primera visita, almacenamiento bloqueado o valor
 * corrupto) manda `prefers-color-scheme`; con clave manda el usuario y
 * el sistema ya no se consulta. Elegir se hace con `elegir()`, que llama
 * `app.js` desde el botón sol/luna de la barra. Este archivo no tiene
 * más lógica que aplicar el atributo `data-tema`, sobre el que se apoya
 * toda la paleta de `style.css`.
 */
(function () {
  const CLAVE = "purplemd_tema";
  /** Preferencia del sistema, leída en vivo (no cacheada). */
  const sistema = window.matchMedia("(prefers-color-scheme: dark)");

  /** Elección explícita del usuario, o `null` si no la hay. */
  function eleccion() {
    try {
      const valor = localStorage.getItem(CLAVE);
      return valor === "claro" || valor === "oscuro" ? valor : null;
    } catch (_) {
      // Almacenamiento bloqueado (modo privado): manda el sistema.
      return null;
    }
  }

  /** Tema vigente: la elección guardada o, en su defecto, el sistema. */
  function actual() {
    return eleccion() || (sistema.matches ? "oscuro" : "claro");
  }

  /** Pinta `data-tema` en `<html>`, lo que decide toda la paleta. */
  function aplicar() {
    document.documentElement.setAttribute("data-tema", actual());
  }

  /**
   * Fija la elección del usuario: guarda en `localStorage` y aplica.
   * Con clave guardada el sistema ya no se consulta; borrar la clave
   * vuelve a dejarlo en manos de `prefers-color-scheme`.
   * @param {"claro"|"oscuro"} tema - Tema elegido.
   */
  function elegir(tema) {
    try {
      localStorage.setItem(CLAVE, tema);
    } catch (_) {
      // Almacenamiento bloqueado: igual se aplica, pero no persiste.
    }
    aplicar();
  }

  /** ¿Está el tema oscuro ahora mismo? */
  function esOscuro() {
    return actual() === "oscuro";
  }

  aplicar();

  window.PurpleMDTema = { CLAVE, sistema, eleccion, actual, aplicar, elegir, esOscuro };
})();
