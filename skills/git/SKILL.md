---
version: "0.1.0"
schemaVersion: 1
name: "git"
description: "Higiene Git: commits convencionales, branches, PRs, tags, changelog. El agente sugiere, el humano ejecuta."
tools: [read, write, edit, shell, grep, glob]
permissions: "read-write"
model: "sonnet-4"
tags: [git, vcs, conventional-commits, workflow]
---

# Skill: Git

## Principio inviolable

> **El agente NUNCA hace commits, pushes, merges, borrados ni renombres.**
> **Solo el operador humano ejecuta operaciones de escritura en el historial.**
> El agente **sugiere** mensajes de commit (Conventional Commits) y comandos; el humano decide y ejecuta.

---

## Commits: Conventional Commits 1.0.0

Formato:

```text
<tipo>[ámbito opcional]: <descripción corta>

[cuerpo opcional]

[footer opcional]
```

### Tipos permitidos

| Tipo | Cuándo usarlo |
|------|---------------|
| `feat` | Nueva funcionalidad para el usuario |
| `fix` | Corrección de bug |
| `docs` | Solo documentación (README, comments, etc.) |
| `style` | Formato, punto y coma, sin cambios de lógica |
| `refactor` | Reestructuración sin cambio de comportamiento |
| `perf` | Mejora de performance |
| `test` | Agregar/corregir tests |
| `chore` | Mantenimiento: deps, config, CI, build, tooling |
| `revert` | Revertir commit previo |
| `build` | Cambios en sistema de build/deps externas |
| `ci` | Cambios en CI/CD |

### Reglas de mensaje

- **Descripción corta**: imperativo, minúscula, sin punto final, ≤ 72 chars
- **Cuerpo**: explica *qué* y *por qué* (no *cómo*), wrap 72 chars
- **Footer**: `Closes #123`, `BREAKING CHANGE: ...`, `Co-authored-by: ...`

### Ejemplos

```bash
# Feature
feat(api): add /health endpoint for load balancer probes

# Fix con scope
fix(cors): allow localhost regex for dev origins

# Refactor con cuerpo
refactor(auth): extract token validation to service

- Moves JWT logic to TokenService class
- Enables unit testing without FastAPI test client
- Reduces duplication in middleware

# Breaking change
feat(config)!: require API_KEY in environment

BREAKING CHANGE: API_KEY must be set in .env; no default provided.

# Chore con issue
chore(deps): upgrade ruff to 0.5.0

Closes #456
```

---

## Branches

### Naming

```text
<tipo>/<descripción-corta>
```

| Tipo branch | Prefijo | Ejemplo |
|-------------|---------|---------|
| Feature | `feat/` | `feat/add-health-endpoint` |
| Bugfix | `fix/` | `fix/cors-localhost-regex` |
| Refactor | `refactor/` | `refactor/auth-token-service` |
| Docs | `docs/` | `docs/update-readme-deploy` |
| Chore/Config | `chore/` | `chore/upgrade-ruff-050` |
| Experiment | `exp/` | `exp/try-ty-typecheck` |
| Release | `release/` | `release/v1.2.0` |

### Reglas

- **Una branch = una preocupación** (un feature, un fix, un refactor)
- Branch desde `main` (o `develop` si el proyecto lo usa)
- Nombres en **kebab-case**, solo ASCII, ≤ 50 chars
- Borrar branch remota tras merge (el humano lo hace)

---

## Pull Requests

### Título del PR

= **Commit message principal** (Conventional Commit). Si hay varios commits, el mantenedor hace squash con mensaje único.

### Descripción del PR (plantilla)

```markdown
## Qué cambia
- Breve lista de cambios user-facing

## Por qué
- Contexto / issue relacionado (#123)

## Cómo testear
- Pasos concretos para verificar

## Checklist
- [ ] Tests pasan
- [ ] Lint/typecheck pasan
- [ ] Docs actualizadas (si aplica)
- [ ] CHANGELOG.md actualizado (si user-facing)
- [ ] No hay secretos ni archivos generados
```

### Reglas

- **Draft PR** mientras está en WIP
- **Review obligatorio** antes de merge (mínimo 1 aprobador en Amargos)
- **Squash and merge** preferido (historial limpio)
- **Rebase** sobre `main` antes de merge (no merge commits)

---

## Tags y Releases

### Versionado: SemVer estricto

```text
v<MAJOR>.<MINOR>.<PATCH>
```

| Bump | Cuándo |
|------|--------|
| `PATCH` | Fixes, docs, chore, refactor sin breaking |
| `MINOR` | Features retrocompatibles |
| `MAJOR` | Breaking changes (API, config, schema, behavior) |

### Tagging (solo humano)

```bash
# Desde main, tras merge de release/PR
git tag -a v1.2.0 -m "Release v1.2.0"
git push origin v1.2.0
```

### Changelog

- **Keep a Changelog** format (`CHANGELOG.md`)
- Se actualiza **en el mismo PR** que introduce el cambio user-facing
- Secciones: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`

---

## Flujo de trabajo (agente sugiere, humano ejecuta)

### 1. Agente analiza cambios y sugiere

```text
He detectado 3 archivos modificados:
- src/api/health.py (nuevo endpoint)
- tests/test_health.py (tests nuevos)
- CHANGELOG.md (actualizado)

Sugerencia de commit:
  feat(api): add /health endpoint for load balancer probes

  - Implements GET /health returning 200 + JSON status
  - Adds unit tests with 100% coverage
  - Updates CHANGELOG.md [Added]

¿Ejecutas? git add -A && git commit -m "feat(api): add /health endpoint for load balancer probes

- Implements GET /health returning 200 + JSON status
- Adds unit tests with 100% coverage
- Updates CHANGELOG.md [Added]"
```

### 2. Humano revisa, ajusta si quiere, y ejecuta

### 3. Push y PR (humano)

```bash
git push origin feat/add-health-endpoint
# Abre PR en GitHub/GitLab
```

---

## Comandos de solo lectura (agente SÍ puede ejecutar)

| Comando | Propósito |
|---------|-----------|
| `git status` | Estado working tree |
| `git diff` / `git diff --staged` | Ver cambios |
| `git log --oneline -20` | Historial reciente |
| `git branch -a` | Listar branches |
| `git show <commit>` | Ver commit |
| `git blame <file>` | Autor por línea |
| `git diff <branch1>..<branch2>` | Comparar branches |

> **Nota**: El agente puede leer todo lo que necesite para sugerir. Nunca escribe en `.git/`.

---

## Configuración recomendada (proyecto añade en su AGENTS.md)

```bash
# Git config local (proyecto)
git config commit.template .gitmessage.txt
git config pull.rebase true
git config push.autoSetupRemote true
```

`.gitmessage.txt` (plantilla commit):

```text
# <tipo>[ámbito]: <descripción ≤72c>
#
# Tipos: feat|fix|docs|style|refactor|perf|test|chore|revert|build|ci
# Ámbitos: api|ui|auth|db|config|ci|docs|deps|...
#
# Cuerpo: qué y por qué (wrap 72c)
#
# Footer: Closes #123 | BREAKING CHANGE: ...
```

---

## Checklist pre-push (skill-level)

- [ ] Commits siguen Conventional Commits
- [ ] Branch name sigue convención `tipo/descripción`
- [ ] No hay commits WIP/fixup en historial final (squash antes de PR)
- [ ] `CHANGELOG.md` actualizado si hay cambios user-facing
- [ ] No hay secretos en diff (`git diff --staged` → revisar)
- [ ] PR description completa (qué, por qué, cómo testear)

---

## Integración con `container`

> Commits que tocan `Dockerfile`, `compose.yaml`, `.dockerignore` → tipo `build` o `ci` según alcance.

---

> **Nota**: Esta skill define **higiene Git universal**. Proyectos pueden extenderla en su `AGENTS.md` local
> (ej: añadir `git-crypt`, `husky`, `commitlint` config, reglas de monorepo, etc.).
