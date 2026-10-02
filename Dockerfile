# syntax=docker/dockerfile:1
#
# Imagen de purplemd en tres etapas:
#
#   deps   -> solo pyproject.toml + uv.lock. La capa se cachea mientras no
#             cambien las dependencias.
#   build  -> agrega el código (módulos de la raíz, purplemd_storage/ y
#             static/, el frontend) e instala el proyecto (install editable
#             con rutas absolutas, por eso WORKDIR es /app en todas las
#             etapas).
#   final  -> Python slim, sin uv ni toolchains, con usuario sin privilegios.
#
# Del sistema solo bajan las libs nativas que WeasyPrint abre en runtime
# (Pango/HarfBuzz/Fontconfig) para el export a PDF: api.py importa
# weasyprint al arrancar, sin esas libs `import api` falla y la imagen no
# levanta. No hay fuentes ni toolchains de build: purplemd es un editor de
# texto, no un generador de imágenes.
#
# Los datos NO viven en la imagen: /app/local/purplemd es el punto de
# montaje del volumen. Al levantar el contenedor:
#
#   podman run -v .../local/purplemd:/app/local/purplemd ...

FROM python:3.13-slim-trixie AS deps

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# uv fijado a la versión con la que se desarrolla el proyecto: el lockfile
# declara version = 1, revision = 3 y el binario del build tiene que poder
# leerlo. --frozen hace que el build falle si el lockfile no está sincronizado.
RUN pip install --no-cache-dir uv==0.12.19

WORKDIR /app

# Primero el manifiesto: si solo cambia el código, esta capa queda entera.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project


FROM deps AS build

# README.md entra porque pyproject.toml lo declara como `readme`. El resto es
# el código que la app importa en runtime: los tres módulos sueltos de la
# raíz y purplemd_storage/ (paquete que api.py y purplemd.py importan), que
# va en su propia COPY —como static/— para quedar como directorio en /app.
COPY README.md api.py purplemd.py renderer.py ./
COPY purplemd_storage/ ./purplemd_storage/
COPY static/ ./static/
# Plantillas: recursos .md servidos por /plantillas y sembrados en la app.
COPY plantillas/ ./plantillas/
RUN uv sync --no-dev --frozen


FROM python:3.13-slim-trixie AS final

# Libs nativas de runtime, según la lista oficial de WeasyPrint para Debian
# con wheels (weasyprint/text/ffi.py dlopena pango, harfbuzz, fontconfig y
# gobject —este último llega como dependencia de pango—). Con --no-install-
# recommends y limpieza de lists/ para no inflar la capa. Sin fijar
# versiones de paquete (hadolint DL3008): Debian retira paquetes de los
# mirrors y fijar rompería el build, mismo tradeoff documentado en la skill.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
        fonts-noto-color-emoji \
        fonts-liberation2 \
    && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios: la app solo lee su /app y escribe en su directorio
# de datos.
RUN useradd --create-home --uid 10001 purplemd

# Misma ruta que en `build`: el install editable apunta a /app por ruta absoluta.
WORKDIR /app

COPY --from=build --chown=purplemd:purplemd /app /app

# Directorio de datos: queda vacío y con ownership del usuario en la imagen;
# al levantar se monta el volumen del host encima, así que los datos reales
# viven fuera de la imagen y sobreviven a `podman restart` y a rebuilds.
RUN mkdir -p /app/local/purplemd \
    && chown purplemd:purplemd /app/local/purplemd

USER purplemd

# .venv/bin primero para resolver uvicorn y python. PURPLEMD_DIR apunta al
# directorio de datos dentro de la imagen (el target del volumen).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PURPLEMD_DIR=/app/local/purplemd

EXPOSE 8000

# Sonda que lee el body de /health: el endpoint responde HTTP 200 siempre y
# el estado real vive en el JSON ("ok" | "degradado"), así que un chequeo solo
# del código HTTP daría verde aunque el directorio de datos no sea escribible.
# Sin curl (la imagen no lo trae): python -c + urllib. Requiere
# `podman build --format docker`: en formato OCI (el default de Podman) se
# descarta con el warning "HEALTHCHECK is not supported for OCI image format".
# PORT lo inyecta Render (10000 por defecto); fuera de Render cae a 8000.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import json, os, urllib.request as u; b = json.load(u.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=4)); assert b.get('estado') == 'ok', b"

# `exec` deja a uvicorn como PID 1 para que reciba SIGTERM y cierre limpio en
# vez de morir con timeout; ${PORT:-8000} porque los hosts inyectan PORT.
CMD ["sh", "-c", "exec uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
