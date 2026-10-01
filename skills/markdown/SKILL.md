---
version: "0.1.0"
schemaVersion: 1
name: "markdown"
description: "Calidad Markdown: lint, front-matter, formato, links, límite 300 líneas. Base para AGENTS.md y SKILL.md."
tools: [read, write, edit, shell, grep, glob]
permissions: "read-write"
model: "sonnet-4"
tags: [markdown, lint, formatting, front-matter, validation]
---

# Skill: Markdown

## Principio rector

> **Todos los archivos `.md` del repo (AGENTS.md, SKILL.md, CHANGELOG.md, docs/*) deben pasar validación automática.**
> Lint + schema + límite de líneas = calidad consistente y parsable por máquinas.

---

## Lint: markdownlint (estándar de facto)

### Configuración `.markdownlint.jsonc` (proyecto adopta en raíz)

```jsonc
{
  "default": true,
  "MD013": { "line_length": 120, "code_blocks": false, "tables": false },
  "MD024": { "siblings_only": true },
  "MD033": false,
  "MD041": false,
  "MD028": false,
  "MD059": false,
  "MD012": { "maximum": 2 },
  "MD009": { "br_spaces": 2 },
  "MD031": true,
  "MD032": true,
  "MD040": true,
  "MD046": { "style": "fenced" },
  "MD050": true,
  "MD051": true,
  "MD052": true,
  "MD053": true,
  "MD054": true,
  "MD055": true,
  "MD056": true,
  "MD058": true
}
```

### Ejecución (proyecto adapta en su AGENTS.md)

```bash
# Lint all .md files
npx markdownlint-cli2 "**/*.md" --config .markdownlint.jsonc

# Fix auto-fixable
npx markdownlint-cli2 "**/*.md" --config .markdownlint.jsonc --fix
```

---

## Front-matter YAML (obligatorio en AGENTS.md y SKILL.md)

### Estructura requerida

```yaml
---
version: "0.1.0"           # SemVer string (schema lo valida)
schemaVersion: 1           # Versión del schema JSON (entero)
name: "nombre-unico"       # slug, lowercase, kebab-case
extends: "base" | null     # Solo AGENTS.md: de qué base hereda
skills: [skill1, skill2]   # Solo AGENTS.md: array de skills (min 1)
model: "sonnet-4"          # Modelo por defecto (enum en schema)
description: "Una línea"   # Resumen para catálogos
tools: [read, write]       # Solo SKILL.md: herramientas permitidas
permissions: "read-write"  # Solo SKILL.md: read-only | read-write
tags: [tag1, tag2]         # Array strings, lowercase, kebab-case
language: "es"             # Opcional: idioma instrucciones
project: "mi-proyecto"     # Opcional: AGENTS.md proyecto-específico
---
```

### Reglas

- **Siempre al inicio del archivo** (línea 1 = `---`)
- **YAML válido** (comillas en strings con `:`, `#`, `[`, `]`, etc.)
- **Sin campos extra no definidos en schema** (`additionalProperties: false`)
- **Orden recomendado**: version → schemaVersion → name → extends/skills → model → description →
  tools/permissions → tags → extras

---

## Límite de 300 líneas (HARD RULE)

> **Archivos `.md` no superan 300 líneas totales (front-matter + cuerpo).**

### Por qué

- Contexto LLM acotado → respuestas precisas
- Forza modularidad → skills pequeñas, componibles
- Diffs legibles en PRs
- Parsing rápido en CI

### Qué hacer si crece

| Situación | Solución |
|-----------|----------|
| Skill muy grande | Dividir en sub-skills (`python-lint`, `python-test`, `python-docker`) |
| AGENTS.md grande | Mover reglas a skills; AGENTS.md solo coordina |
| Docs extensas | `docs/` con múltiples archivos + `index.md` que linkea |

### Excepción documentada

Si **excepcionalmente** supera 300 líneas, añadir en front-matter:

```yaml
maxLinesOverride: 450
overrideReason: "Documentación de referencia completa de API; dividir rompe navegación"
```

CI avisa (warning) pero no falla. Revisar en próximo release.

---

## Estructura de headers (jerarquía obligatoria)

```markdown
# Título principal (H1) - UNA sola vez, tras front-matter
## Sección mayor (H2)
### Subsección (H3)
#### Detalle (H4) - máx profundidad
```

### Reglas

- **Un solo H1** por archivo (el título principal)
- **No saltar niveles** (H2 → H4 sin H3 = ❌)
- **H2 = secciones navegables** (aparecen en TOC/outline)
- **Lista con `-`** (no `*` ni `+`) para consistencia
- **Code blocks con language** (```python,```yaml, ```bash,```text)

---

## Links y referencias

### Links internos (repo)

```markdown
# Relativos desde raíz del repo
[Skill Python](../skills/python/SKILL.md)
[Schema agent](../schemas/agent.schema.json)

# Anchors en mismo archivo
[Commits convencionales](#commits-conventional-commits-100)
```

### Links externos

```markdown
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)
[SemVer](https://semver.org/lang/es/)
```

### Reglas

- **Links internos: siempre relativos** (funcionan en GitHub, GitLab, local, Obsidian)
- **Validar en CI**: `markdown-link-check` o `lychee` (no broken links)
- **No URLs crudas** — siempre con texto descriptivo

---

## Tablas (formato consistente)

```markdown
| Columna 1 | Columna 2 | Columna 3 |
|-----------|-----------|-----------|
| Valor A   | Valor B   | Valor C   |
| Valor D   | Valor E   | Valor F   |
```

- Pipes alineados (markdownlint MD055)
- Header row obligatorio
- Sin celdas vacías en header

---

## Code blocks

````markdown
```python
def hello():
    print("Hola")
```

```yaml
version: "0.1.0"
name: "example"
```

```bash
git commit -m "feat: add hello"
```

````

- **Siempre language tag** (markdownlint MD040)
- **Fenced blocks** (```) no indented (markdownlint MD046)
- **Blank line antes y después** (markdownlint MD031)

---

## Callouts / Admonitions (GitHub/Markdown-it compatible)

```markdown
> **Nota**: Información complementaria.

> **⚠️ Advertencia**: Cuidado con esto.

> **✅ Tip**: Buena práctica.

> **🚫 No hacer**: Anti-patrón.
```

- Usar `> **` + emoji opcional + `**:` + texto
- Una línea por párrafo (wrap natural)

---

## Checklist pre-push (skill-level)

- [ ] `npx markdownlint-cli2 "**/*.md" --config .markdownlint.jsonc` → OK
- [ ] Front-matter válido contra schema (`agent.schema.json` / `skill.schema.json`)
- [ ] Archivo ≤ 300 líneas (o `maxLinesOverride` justificado)
- [ ] Un solo H1, jerarquía correcta H2→H3→H4
- [ ] Links internos relativos y válidos
- [ ] Code blocks con language tag
- [ ] Tablas con pipes alineados
- [ ] Sin trailing spaces innecesarios (MD009)

---

## Integración con CI (proyecto configura)

```yaml
# .github/workflows/validate.yml (extracto)
- name: Markdown lint
  run: npx markdownlint-cli2 "**/*.md" --config .markdownlint.jsonc

- name: Validate front-matter schemas
  run: |
    python scripts/validate_frontmatter.py \
      --agent-schema schemas/agent.schema.json \
      --skill-schema schemas/skill.schema.json \
      --files "AGENTS*.md" "skills/*/SKILL.md"

- name: Check line limits
  run: |
    python scripts/check_line_limits.py --max 300 --allow-override
```

---

## Herramientas recomendadas (proyecto instala)

| Herramienta | Propósito |
|-------------|-----------|
| `markdownlint-cli2` | Lint rápido, fix auto, config JSONC |
| `lychee` / `markdown-link-check` | Validar links (interno + externo) |
| `yaml-language-server` | Validación YAML en editor (VS Code, Obsidian) |
| `prettier` + `prettier-plugin-markdown` | Formateo opcional (si el equipo lo usa) |

---

> **Nota**: Esta skill es **auto-aplicable**: valida su propio archivo `SKILL.md` y todos los `.md` del repo.
> Proyectos que la adopten copian `.markdownlint.jsonc` y añaden los pasos de CI a su pipeline.
