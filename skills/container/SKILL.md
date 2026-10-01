---
version: "0.1.0"
schemaVersion: 1
name: "container"
description: "Contenedores: multi-stage, security, rootless, buildah, compose. Compatible Podman/Docker."
tools: [read, write, edit, shell, grep, glob]
permissions: "read-write"
model: "sonnet-4"
tags: [container, podman, docker, buildah, oci, security]
maxLinesOverride: 350
overrideReason: "Coverage completa: Dockerfile template, Buildah/Podman/Docker commands, compose, pods, security hardening, registry auth, CI, tools cheatsheet. Dividir rompe referencia unificada."
---

# Skill: Container (Podman/Docker)

## Principio: OCI-first, rootless-by-default

> **Escribí una vez, corré en Podman y Docker.** Sintaxis Dockerfile = estándar OCI.
> **Preferí Podman rootless** (sin daemon, sin root, mejor seguridad).
> **Buildah** para builds avanzados sin daemon ni privilegios.

---

## Archivo de definición

**Archivo único**: `Dockerfile` (estándar de facto, leído por Podman, Buildah, Docker, toda herramienta OCI).
**Runtime preferido**: Podman rootless. Docker compatible sin cambios.

---

## Dockerfile: Multi-stage, seguro, reproducible

### Plantilla base (Python example, adaptable)

```dockerfile
# syntax=docker/dockerfile:1.7
# ^ Habilita features modernas (BuildKit/podman build --format=docker)

# --- BASE COMÚN ---
FROM python:3.12-slim AS base
# Seguridad: usuario no-root, sin package manager en runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Usuario no-root (UID 1000 = estándar contenedores)
RUN groupadd -r -g 1000 appgroup && \
    useradd -r -u 1000 -g appgroup -d /app -s /sbin/nologin appuser && \
    chown -R appuser:appgroup /app

# --- BUILDER: compila deps, instala en venv ---
FROM base AS builder
# Instalar build deps solo aquí
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
# uv: rápido, reproducible, cacheable
RUN uv sync --frozen --no-install-project --no-dev --compile-bytecode

# --- RUNTIME: solo lo necesario ---
FROM base AS runtime
# Copiar venv compilado (layer cacheable)
COPY --from=builder --chown=appuser:appgroup /app/.venv .venv
# Copiar código fuente
COPY --chown=appuser:appgroup src/ ./src

# Usuario no-root OBLIGATORIO
USER appuser

# Healthcheck (estándar OCI)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=2)"

# Entrypoint por defecto (proyecto override en compose/CLI)
ENTRYPOINT ["python", "-m", "package_name"]
```

### Reglas de oro

1. **`syntax=docker/dockerfile:1.7`** — habilita `--mount=cache`, `--mount=ssh`, heredoc, etc.
2. **Base slim/alpine + non-root user** — siempre
3. **Multi-stage: builder → runtime** — separa build deps de runtime
4. **`uv sync --frozen --compile-bytecode`** — reproducible, rápido
5. **`COPY --chown=user:group`** — evita `chown` extra layer
6. **`HEALTHCHECK`** — estándar, no custom scripts
7. **No secretos en imagen** — `--mount=type=secret` en builder si hace falta
8. **Pin base image digest** en producción: `FROM python:3.12-slim@sha256:...`

---

## Build: Buildah (recomendado) / Podman / Docker

### Buildah (sin daemon, rootless, máximo control)

```bash
# Build simple
buildah bud -t mi-app:1.2.0 -f Dockerfile .

# Build con cache mount (requiere buildah 1.30+)
buildah bud --build-arg BUILDKIT_INLINE_CACHE=1 \
  --layers --format=oci -t mi-app:1.2.0 .

# Push a registry (usa auth de containers-auth.json)
buildah push mi-app:1.2.0 docker://registry.example.com/mi-app:1.2.0
```

### Podman (CLI compatible Docker)

```bash
# Build
podman build -t mi-app:1.2.0 -f Dockerfile .

# Build con BuildKit features (Podman 4.5+)
podman build --format=docker -t mi-app:1.2.0 .

# Rootless: funciona out of the box
```

### Docker (si el entorno lo requiere)

```bash
# Build estándar
docker build -t mi-app:1.2.0 -f Dockerfile .

# BuildKit (Docker 23+)
DOCKER_BUILDKIT=1 docker build -t mi-app:1.2.0 .
```

> **Regla**: CI usa **Buildah** (sin daemon, rápido, rootless). Local: lo que tengas (`podman` / `docker` / `buildah`).

---

## Compose / Pods: Desarrollo y CI

### `compose.yaml` (v2, compatible Podman/Docker)

```yaml
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
    image: mi-app:dev
    environment:
      - PYTHONPATH=/app/src
      - API_KEY=${API_KEY}  # desde .env (no commiteado)
    ports:
      - "8000:8000"
    volumes:
      - ./src:/app/src:ro  # hot-reload dev
    user: "1000:1000"      # refuerza non-root
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:8000/health')"]
      interval: 10s
      timeout: 3s
      retries: 3

  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_DB=miapp
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
      retries: 5

secrets:
  db_password:
    file: .secrets/db_password.txt  # gitignored

volumes:
  pgdata:
```

### Podman Compose (v2+)

```bash
# Levantar stack
podman compose -f compose.yaml up -d

# Logs
podman compose logs -f app

# Bajar
podman compose down -v
```

### Podman Pods (K8s-like, sin Compose)

```bash
# Crear pod con red compartida
podman pod create --name miapp-pod -p 8000:8000

# Correr contenedores en el pod
podman run -d --pod miapp-pod --name app \
  -e API_KEY=${API_KEY} mi-app:1.2.0
podman run -d --pod miapp-pod --name db \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/db_password \
  postgres:16-alpine

# Generar K8s YAML para deploy
podman generate kube miapp-pod > miapp-pod.yaml
```

---

## Seguridad: Hardening checklist

- [ ] **Non-root user** (UID ≥ 1000) en runtime
- [ ] **Read-only rootfs** (`--read-only` / `security_opt: ["no-new-privileges:true"]`)
- [ ] **Drop capabilities** (`--cap-drop=ALL` + `--cap-add` solo lo necesario)
- [ ] **No secretos en imagen** — secrets via `--mount=type=secret` (build) / `secrets:` (compose) / vars de entorno (runtime)
- [ ] **Base image digest pinned** en producción
- [ ] **Scan vulnerabilidades** — `grype` / `trivy` / `podman scout` en CI
- [ ] **SBOM** — `syft` o `podman sbom` generado en build
- [ ] **Firma de imágenes** — `cosign` / `skopeo` para supply chain

---

## Registry auth: `containers-auth.json` (portable)

```json
{
  "auths": {
    "registry.example.com": {
      "auth": "base64(user:pass)",
      "identitytoken": "..."
    },
    "ghcr.io": {
      "auth": "base64(user:token)"
    }
  }
}
```

Ubicación: `${XDG_RUNTIME_DIR}/containers/auth.json` (Podman) / `~/.docker/config.json` (Docker).
**Compartible**: `export REGISTRY_AUTH_FILE=/ruta/compartida/auth.json`

---

## CI: Buildah en GitHub Actions (rootless, rápido)

```yaml
name: Container
on: [push, pull_request]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Buildah
        uses: redhat-actions/buildah-build@v2
        with:
          image: mi-app
          tags: ${{ github.sha }} latest
          dockerfile: Dockerfile
          args: BUILDKIT_INLINE_CACHE=1
      - name: Scan vulnerabilities
        run: |
          grype mi-app:${{ github.sha }} --fail high
      - name: Generate SBOM
        run: syft mi-app:${{ github.sha }} -o spdx-json > sbom.spdx.json
      - name: Push to registry (solo main/tags)
        if: github.ref_type == 'tag' || github.ref == 'refs/heads/main'
        run: |
          buildah login -u ${{ secrets.REGISTRY_USER }} -p ${{ secrets.REGISTRY_PASS }} registry.example.com
          buildah push mi-app:${{ github.sha }} docker://registry.example.com/mi-app:${{ github.sha }}
```

---

## Checklist pre-push (skill-level)

- [ ] `Dockerfile` pasa `hadolint` (o `dockerfile_lint`)
- [ ] Multi-stage: builder → runtime (sin build deps en final)
- [ ] Non-root user (UID 1000) + `USER` en runtime
- [ ] `HEALTHCHECK` definido
- [ ] `compose.yaml` válido (`podman compose config` / `docker compose config`)
- [ ] `podman compose up -d` → healthchecks pasan
- [ ] `grype` / `trivy` → 0 HIGH/CRITICAL
- [ ] Imagen firmada si release tag
- [ ] No secretos en `.dockerignore` ni Dockerfile

---

## Herramientas recomendadas

| Herramienta | Propósito |
|-------------|-----------|
| `buildah` | Build rootless, sin daemon, OCI-native |
| `podman` | Runtime, compose, pods, kube generate |
| `skopeo` | Copy, inspect, sign entre registries |
| `cosign` | Firmar/verificar imágenes (keyless) |
| `grype` / `trivy` | Vulnerability scanning |
| `syft` | SBOM generation |
| `hadolint` | Dockerfile lint |
| `dive` | Analizar layers de imagen |

---

## Diferencias Podman vs Docker (cheat sheet)

| Acción | Podman | Docker |
|--------|--------|--------|
| Build | `podman build` / `buildah bud` | `docker build` |
| Run | `podman run` | `docker run` |
| Compose | `podman compose` (v2+) | `docker compose` |
| Login | `podman login` | `docker login` |
| Push | `podman push` / `buildah push` | `docker push` |
| Pods | `podman pod create` | ❌ (use K8s) |
| K8s YAML | `podman generate kube` | `kompose` |
| Systemd units | `podman generate systemd` | ❌ |
| Rootless | **Default** | Config extra |

---

> **Nota**: Esta skill cubre **contenedores OCI genéricos**. Proyectos Python usan `skills/python` +
> `skills/container` juntas. Proyectos Go/Node/Rust adaptan el `Dockerfile` base pero siguen los mismos
> principios de seguridad y multi-stage.
