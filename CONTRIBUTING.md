# Contribuir a PurpleMD

¡Gracias por tu interés en mejorar PurpleMD! 💜

Esta guía explica cómo participar: reportar bugs, proponer mejoras o mandar
código. Está pensada para que cualquier persona pueda contribuir, sin importar
su nivel de experiencia.

## Índice

- [Código de conducta](#código-de-conducta)
- [Cómo contribuir](#cómo-contribuir)
- [Reportar un bug](#reportar-un-bug)
- [Proponer una mejora](#proponer-una-mejora)
- [Flujo de trabajo (Pull Request)](#flujo-de-workflow-pull-request)
- [Configuración local](#configuración-local)
- [Reglas del proyecto](#reglas-del-proyecto)
- [Convenciones de código](#convenciones-de-código)
- [Commits](#commits)
- [Licencia](#licencia)

---

## Código de conducta

Este proyecto adhiere al
[Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).

Se espera un trato **respetuoso e inclusivo** en issues, pull requests,
discusiones y cualquier espacio del proyecto. No se tolera acoso, insultos,
discriminación ni trato despectivo.

**Para reportar una conducta inapropiada** (sin exponer tu email):

- Usá la función **“Report abuse” de GitHub**: perfil del usuario → `...` →
  *Report abuse*.
- O abrí un **Security Advisory** en la pestaña *Security* del repo: llega solo
  a los maintainers.

---

## Cómo contribuir

Hay muchas formas de ayudar, no solo con código:

| Tipo de contribución | Dónde empezar |
| --- | --- |
| 🐛 Reportar un bug | [Issues](https://github.com/ltrecanao/purplemd/issues) |
| 💡 Proponer una mejora | Issues con label `enhancement` |
| 📝 Mejorar la documentación | Issues con label `docs` o PR directo |
| 🌐 Traducir | Issues con label `i18n` |
| ✅ Escribir tests | Issues con label `tests` |
| 🧪 Probar versiones nuevas | Issues con label `help wanted` |

> **Antes de escribir código grande**, abrí un issue para comentar la idea.
> Evita trabajo duplicado y alineamos expectativas.

---

## Reportar un bug

1. **Buscá primero** en [issues abiertos](https://github.com/ltrecanao/purplemd/issues)
   y cerrados: puede ya estar reportado.
2. Si no existe, creá uno nuevo con:
   - **Título claro**: qué falla y en qué contexto.
   - **Pasos para reproducir**: uno por uno.
   - **Comportamiento esperado** vs. **comportamiento actual**.
   - **Entorno**: navegador, SO, versión de Python/`uv`, y si corrés con
     `PURPLEMD_STORAGE=memory` o `filesystem`.
   - **Screenshots o logs** si ayudan.

---

## Proponer una mejora

1. Abrí un issue describiendo:
   - El problema que resuelve (¿por qué es útil?).
   - Una propuesta concreta de solución, si la tenés.
   - Alternativas que consideraste.
2. Esperá el visto bueno de un maintainer antes de invertir mucho tiempo.

---

## Flujo de trabajo (Pull Request)

1. **Forkeá** el repo y creá una rama desde `main`:
   ```bash
   git checkout -b feat/nombre-corto-descriptivo
   ```
2. **Hacé cambios chicos y enfocados**: un PR = una idea. Si querés meter
   varias cosas, mandá varios PRs.
3. **Seguí las reglas del proyecto** (más abajo) y los
   [AGENTS.md](AGENTS.md) del repo.
4. **Corré la suite completa** antes de mandar el PR:
   ```bash
   uv run ruff check .
   uv run ty check .
   uv run pytest -q
   ```
5. **Escribí commits convencionales** (más abajo).
6. **Abrí el PR** contra `main` con:
   - Título en formato convencional (`fix: ...`, `feat: ...`).
   - Descripción de **qué** cambia y **por qué**.
   - Cierre automático de issues si aplica (`Closes #12`).
7. **Respondé los reviews**; el maintainer hará *merge* cuando esté listo.

### Checklist pre-PR

- [ ] Tests: `uv run pytest -q` ✓
- [ ] Lint: `uv run ruff check .` ✓
- [ ] Type-check: `uv run ty check .` ✓
- [ ] Prueba local (backend + frontend): `uv run uvicorn api:app --reload` ✓
- [ ] Commit message convencional ✓
- [ ] Documentación actualizada si cambiaste comportamiento visible

---

## Configuración local

### Requisitos

- **Python 3.13+** (la versión vive en `pyproject.toml` y
  `Dockerfile`: tienen que coincidir).
- **[uv](https://docs.astral.sh/uv/)** como gestor de paquetes.
- **Podman** o Docker (solo si querés probar la imagen).
- Librerías de sistema para el export a PDF (`weasyprint`):
  ```bash
  # Debian/Ubuntu
  sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0
  ```

### Arranque

```bash
git clone https://github.com/ltrecanao/purplemd.git
cd purplemd
uv sync --dev            # instala deps de producción y desarrollo
uv run uvicorn api:app --reload
```

La app queda en <http://127.0.0.1:8000>.

### Comandos útiles

| Comando | Qué hace |
| --- | --- |
| `uv sync --dev` | Instala/actualiza dependencias |
| `uv run uvicorn api:app --reload` | Servidor dev con recarga |
| `uv run pytest -q` | Corre la suite (306 tests + 263 subtests) |
| `uv run pytest tests/test_api.py -k pdf` | Test específico |
| `uv run ruff check .` | Lint |
| `uv run ruff check . --fix` | Lint con auto-corrección |
| `uv run ty check .` | Type-check |

---

## Reglas del proyecto

Son transversales a toda contribución (ver [AGENTS.md](AGENTS.md)):

1. **Todo en español**: respuestas, documentación, comentarios y textos de UI.
   Inglés solo para identificadores, nombres propios y comandos.
2. **Consistencia de versiones de Python**: si cambiás la versión, actualizá
   `Dockerfile`, CI (`PYTHON_VERSION`), `pyproject.toml`
   (`requires-python`) **y** el CI debe seguir pasando.
3. **Rutas relativas** en HTML/CSS/JS (subpath de GitHub Pages). La URL de la
   API solo en un archivo de config del frontend, nunca hardcodeada.
4. **CORS sin wildcards**: origen de explícito de prod +
   `allow_origin_regex` para localhost.
5. **Tests de funcionalidad eliminada**: si borrás una feature, borrá también
   sus tests. Los tests reflejan el comportamiento actual, no la historia.
6. **Accesibilidad WCAG AAA (7:1)** para texto normal, con test automatizado
   de contraste.
7. **Marca de agua en el PDF**: siempre visible en la versión open source.
   No agregar checkbox ni opción para quitarla (es exclusiva de la versión
   enterprise).
8. **Fuentes 100% libres/comerciales** en el PDF (Liberation Sans, Noto
   Color Emoji — sin Arial).
9. **Sin commits/pushes/merges/borrados** sin autorización explícita del
   maintainer.

---

## Convenciones de código

### Python

- Formato y lint con **ruff** (respetá su criterio; no agregues `# noqa`
  sin justificación).
- Type hints donde aporten; `ty` tiene que pasar.
- Comentarios y docstrings **en español**.
- Tests con `unittest` (la suite es unittest; `pytest` es solo el runner).

### Frontend (vanilla JS)

- **Rutas relativas** (`css/style.css`, `js/app.js`).
- Sin frameworks ni build step: es JS vanilla a propósito.
- Accesibilidad: patrones WAI-ARIA APG, contraste AAA, targets de 44px,
  navegación por teclado.
- Manejo de errores en español, vía toasts (nunca `alert()` ni `confirm()`).

### Documentación

- Si cambiás algo visible, **actualizá el `README.md`** en el mismo PR.
- Markdown en español, con ejemplos copiables.

---

## Commits

[Convención de Commits](https://www.conventionalcommits.org/):

```
<tipo>: <descripción en imperativo, minúscula, sin punto final>
```

| Tipo | Para qué |
| --- | --- |
| `feat:` | Nueva funcionalidad |
| `fix:` | Corrección de un bug |
| `docs:` | Solo documentación |
| `style:` | Formato sin cambio de lógica |
| `refactor:` | Reescritura sin cambiar comportamiento |
| `test:` | Solo tests |
| `chore:` | Tareas de mantenimiento (deps, CI, lint) |
| `perf:` | Mejora de rendimiento |

Ejemplos:

```
feat: agrega export a PDF con marca de agua visible
fix: scroll sync del preview en vista ambos
docs: documenta el flujo de export a ZIP
```

---

## Licencia

Al contribuir, aceptás que tu aporte se distribuya bajo la
[MIT License](LICENSE) del proyecto.

PurpleMD es open core: el motor es MIT; las features enterprise viven en un
repo privado aparte (ver [README](README.md)).

---

¡Gracias de nuevo por ayudar! Si tenés dudas, abrí un issue y las
resolvemos. 💜
