---
version: "0.1.0"
schemaVersion: 1
name: "frontend"
description: "Frontend mobile-first: HTML semántico, CSS moderno, ES modules, a11y WCAG AAA, Vite/Astro, performance."
tools: [read, write, edit, shell, grep, glob]
permissions: "read-write"
model: "sonnet-4"
tags: [frontend, html, css, javascript, a11y, mobile-first, vite, astro]
maxLinesOverride: 400
overrideReason: "Coverage completa: HTML semántico, CSS tokens + breakpoints, JS ES Modules + Vite config, WCAG AAA checklist, performance (CWV), testing matrix. Referencia unificada para implementación."
---

# Skill: Frontend

## Principio rector

> **Mobile-first siempre.** CSS base = viewport angosto. Media queries **solo añaden** (min-width).
> **Accesibilidad no negociable**: WCAG AAA 7:1 contraste, semántica HTML, focus visible, ARIA solo cuando HTML no alcanza.
> **ES modules nativos** + **Vite/Astro** para build. Sin bundlers legacy.

---

## HTML: Semántico, accesible, mobile-first

### Estructura base

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="Descripción única por página (≤160 chars)">
  <title>Título página | Nombre Sitio</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="stylesheet" href="css/style.css">
  <script type="module" src="js/app.js" defer></script>
</head>
<body>
  <a href="#main" class="skip-link">Saltar al contenido principal</a>
  <header class="site-header">…</header>
  <nav class="main-nav" aria-label="Navegación principal">…</nav>
  <main id="main" class="main-content">…</main>
  <footer class="site-footer">…</footer>
</body>
</html>
```

### Reglas HTML

- **Un solo `<h1>`** por página (coincide con `<title>`)
- **Landmarks**: `<header>`, `<nav>`, `<main>`, `<aside>`, `<footer>`
- **Skip link** obligatorio (primer elemento enfocable)
- **Idioma** en `<html lang="">` y cambios con `lang=""` en elementos
- **Imágenes**: `alt` descriptivo (vacío `alt=""` solo si decorativo + `role="presentation"`)
- **Formularios**: `<label for="id">` + `<input id="id">`, `required`, `autocomplete`, `aria-describedby` para errores
- **Tablas**: `<caption>`, `<th scope="col|row">`, no layout

---

## CSS: Moderno, escalable, mobile-first

### Custom properties (design tokens)

```css
:root {
  /* Color */
  --color-bg: #ffffff;
  --color-bg-subtle: #f8f9fa;
  --color-text: #1a1a2e;
  --color-text-muted: #4a4a6a;
  --color-primary: #2563eb;
  --color-primary-hover: #1d4ed8;
  --color-focus: #fbbf24;
  --color-error: #dc2626;
  --color-success: #16a34a;

  /* Espacio (escala 4px) */
  --space-1: 0.25rem;  /* 4px */
  --space-2: 0.5rem;   /* 8px */
  --space-3: 1rem;     /* 16px */
  --space-4: 1.5rem;   /* 24px */
  --space-5: 2rem;     /* 32px */
  --space-6: 3rem;     /* 48px */

  /* Tipografía */
  --font-sans: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "JetBrains Mono", "Fira Code", monospace;
  --text-base: 1rem;       /* 16px */
  --text-sm: 0.875rem;     /* 14px */
  --text-lg: 1.125rem;     /* 18px */
  --text-xl: 1.5rem;       /* 24px */
  --leading-tight: 1.2;
  --leading-normal: 1.5;
  --leading-relaxed: 1.75;

  /* Layout */
  --container-max: 72rem;   /* 1152px */
  --header-height: 4rem;
  --radius-sm: 0.25rem;
  --radius-md: 0.5rem;
  --radius-lg: 1rem;

  /* Sombras */
  --shadow-sm: 0 1px 2px rgb(0 0 0 / 0.05);
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1);

  /* Transiciones */
  --transition-fast: 150ms ease;
  --transition-normal: 250ms ease;

  /* Z-index */
  --z-dropdown: 100;
  --z-sticky: 200;
  --z-modal: 300;
  --z-toast: 400;
  --z-tooltip: 500;
}

/* Dark mode (prefers-color-scheme) */
@media (prefers-color-scheme: dark) {
  :root {
    --color-bg: #0f172a;
    --color-bg-subtle: #1e293b;
    --color-text: #f1f5f9;
    --color-text-muted: #94a3b8;
    --color-primary: #3b82f6;
    --color-primary-hover: #60a5fa;
    --color-focus: #fde047;
  }
}
```

### Mobile-first breakpoints (solo `min-width`)

```css
/* BASE = móvil (≤640px) */
/* Sin media query: estilos base aquí */

/* Tablet (≥641px) */
@media (min-width: 40.0625rem) { /* 641px */
  :root { --text-base: 1.125rem; }
  .grid { grid-template-columns: repeat(2, 1fr); }
}

/* Desktop (≥1024px) */
@media (min-width: 64rem) { /* 1024px */
  .grid { grid-template-columns: repeat(3, 1fr); }
  .sidebar { display: block; }
}

/* Wide (≥1280px) */
@media (min-width: 80rem) { /* 1280px */
  .container { max-width: var(--container-max); }
}
```

### Reglas CSS

- **Unidades relativas**: `rem` (tipografía, espacio), `em` (componentes), `%`/`fr` (layout), `px` solo borders/media queries
- **Container queries** sobre media queries cuando el componente decide: `@container (min-width: 30rem)`
- **Cascade layers** para organización: `@layer reset, base, components, utilities;`
- **No `!important`** (excepto utilities tipo `.visually-hidden`)
- **Focus visible obligatorio**:

```css
:focus-visible {
  outline: 3px solid var(--color-focus);
  outline-offset: 2px;
}
```

- **Reduced motion**:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## JavaScript: ES Modules, Vite, progresivo

### Estructura `js/`

```text
js/
├── app.js              # Entry point
├── config.js           # Config por ambiente (solo archivo que cambia dev/prod)
├── utils/
│   ├── dom.js          # Helpers DOM
│   ├── api.js          # Fetch wrapper
│   └── a11y.js         # Helpers accesibilidad
├── components/
│   ├── Dropdown.js     # Web Component o módulo
│   ├── Modal.js
│   └── Toast.js
└── pages/
    ├── home.js
    └── dashboard.js
```

### `config.js` (único punto de cambio dev/prod)

```js
// js/config.js
export const CONFIG = {
  API_URL: import.meta.env.DEV
    ? "http://localhost:9000"
    : "https://api.midominio.com",
  ENV: import.meta.env.MODE,
  FEATURE_FLAGS: {
    NEW_DASHBOARD: import.meta.env.VITE_NEW_DASHBOARD === "true",
  },
};
```

### `app.js` (entry)

```js
// js/app.js
import { CONFIG } from "./config.js";
import { initNavigation } from "./components/Navigation.js";
import { initDropdowns } from "./components/Dropdown.js";

// Init global
document.addEventListener("DOMContentLoaded", () => {
  initNavigation();
  initDropdowns();
  // Page-specific init via data-page attribute
  const page = document.body.dataset.page;
  if (page) import(`./pages/${page}.js`);
});
```

### Reglas JS

- **ES Modules** (`type="module"` en HTML, `import`/`export`)
- **Sin globals** (todo en módulos, `window` solo para debugging)
- **Fetch wrapper** con timeout, retry, error typing
- **Event delegation** sobre listeners individuales
- **Web Components** (lit / vanilla) para UI reusable
- **Progressive enhancement**: HTML funcional sin JS, JS mejora

---

## Accesibilidad (WCAG 2.2 AAA)

### Checklist obligatorio por componente

| Criterio | Implementación |
|----------|----------------|
| **Contraste 7:1** | Tokens `--color-text` vs `--color-bg` validados en CI |
| **Focus visible** | `:focus-visible` con outline 3px + offset |
| **Semántica** | HTML5 landmarks, headings jerárquicos, listas reales |
| **Navegación teclado** | Tab order lógico, skip links, focus trap en modales |
| **ARIA** | Solo cuando HTML nativo no cubre (ej: `aria-expanded`, `aria-live`) |
| **Reduced motion** | `@media (prefers-reduced-motion)` desactiva animaciones |
| **Zoom 200%** | Layout no rompe, no scroll horizontal |
| **Formularios** | Labels asociados, errores anunciados (`aria-live="polite"`), autocomplete |

### Testing a11y en CI

```bash
# Lighthouse CI (performance + a11y + best practices)
npx lhci autorun

# axe-core en tests
npm test -- --grep "a11y"

# Contraste automatizado (custom script)
node scripts/check-contrast.js
```

---

## Build: Vite (SPA/MPA) / Astro (content-first)

### `vite.config.ts` base

```ts
import { defineConfig } from "vite";
import { resolve } from "path";

export default defineConfig({
  root: "docs",           // GitHub Pages deploy desde /docs
  publicDir: "public",    // assets estáticos copiados tal cual
  build: {
    outDir: "../dist",    // fuera de root para deploy limpio
    minify: "esbuild",
    cssCodeSplit: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, "docs/index.html"),
      },
    },
  },
  server: { port: 3000, open: true },
  css: { postcss: "./postcss.config.js" },
});
```

### PostCSS (autoprefixer + cssnano + postcss-nesting)

```js
// postcss.config.js
export default {
  plugins: {
    "postcss-nesting": {},      // Nesting nativo (estándar)
    "autoprefixer": {},         // Vendor prefixes
    "cssnano": { preset: "default" }, // Minify prod
  },
};
```

---

## Performance (Core Web Vitals)

| Métrica | Target | Técnica |
|---------|--------|---------|
| **LCP** | ≤ 2.5s | Preload hero image, font-display: swap, critical CSS inline |
| **INP** | ≤ 200ms | Code splitting, web workers, evita main thread blocking |
| **CLS** | ≤ 0.1 | Aspect-ratio en imágenes, font-size-adjust, reservar espacio ads |
| **TTFB** | ≤ 800ms | Edge caching, streaming (Astro), DB query optimization |

### Critical CSS inline (Vite plugin)

```ts
// vite.config.ts
import { vitePluginCriticalCss } from "vite-plugin-critical-css";
plugins: [
  vitePluginCriticalCss({
    pages: [
      { path: "/", template: "docs/index.html" },
    ],
  }),
],
```

---

## Testing

| Tipo | Herramienta | Qué testa |
|------|-------------|-----------|
| **Unit** | Vitest | Utils, hooks, logic pura |
| **Component** | Vitest + @testing-library/dom | Web Components, interacción |
| **E2E** | Playwright | Flujos críticos, a11y, visual regression |
| **Visual** | Playwright + pixelmatch | Diff screenshots cross-browser |
| **A11y** | axe-core + lighthouse | WCAG automatizado |

---

## Checklist pre-push (skill-level)

- [ ] `npm run lint` (ESLint + stylelint) → OK
- [ ] `npm run typecheck` (tsc --noEmit) → OK
- [ ] `npm run test` (Vitest + Playwright) → OK
- [ ] `npm run a11y` (axe + lighthouse) → OK
- [ ] `npm run build` → output en `dist/` sin errores
- [ ] Contraste 7:1 verificado (tokens + runtime)
- [ ] No `console.log` / `debugger` en build
- [ ] `config.js` único punto de cambio dev/prod

---

## Integración con `uiux`

> **`frontend` implementa lo que `uiux` decide.**
>
> - `uiux` define: tokens de diseño, patrones de interacción, flujos, jerarquía visual
> - `frontend` codifica: CSS tokens, Web Components, semántica HTML, estado UI
> - **Cambio en uno = revisión en el otro** (mismo PR o PRs coordinados)

---

> **Nota**: Esta skill cubre **implementación frontend**. Decisiones de UX, flujos, design system tokens → `skills/uiux/SKILL.md`.
