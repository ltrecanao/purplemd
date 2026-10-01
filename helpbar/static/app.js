// PurpleMD Helpbar - Interacciones

document.addEventListener('DOMContentLoaded', () => {
  // Formatos Markdown
  const formatos = {
    heading1: { prefix: '# ', suffix: '', example: 'Encabezado 1' },
    heading2: { prefix: '## ', suffix: '', example: 'Encabezado 2' },
    heading3: { prefix: '### ', suffix: '', example: 'Encabezado 3' },
    bold: { prefix: '**', suffix: '**', example: 'texto en negrita' },
    italic: { prefix: '*', suffix: '*', example: 'texto en cursiva' },
    strikethrough: { prefix: '~~', suffix: '~~', example: 'texto tachado' },
    code: { prefix: '`', suffix: '`', example: 'código' },
    codeblock: { prefix: '```\n', suffix: '\n```', example: 'código\nmultilínea' },
    quote: { prefix: '> ', suffix: '', example: 'cita', multiline: true },
    ul: { prefix: '- ', suffix: '', example: 'item', multiline: true },
    ol: { prefix: '1. ', suffix: '', example: 'item', multiline: true },
    task: { prefix: '- [ ] ', suffix: '', example: 'tarea', multiline: true },
    link: { prefix: '[', suffix: '](url)', example: 'texto del enlace' },
    image: { prefix: '![', suffix: '](url)', example: 'texto alternativo' },
    table: { prefix: '| Col1 | Col2 |\n|------|------|\n| ', suffix: ' | |\n|  |  |', example: '' },
    hr: { prefix: '\n---\n', suffix: '', example: '' },
    math: { prefix: '$$', suffix: '$$', example: 'fórmula' }
  };

  // Toast
  const toast = document.createElement('div');
  toast.className = 'toast hidden';
  toast.innerHTML = '<span class="toast-text"></span>';
  document.body.appendChild(toast);

  function showToast(msg) {
    toast.querySelector('.toast-text').textContent = msg;
    toast.classList.remove('hidden');
    setTimeout(() => toast.classList.add('hidden'), 2000);
  }

  // Click en botones de toolbar
  document.querySelectorAll('.tool-btn[data-format]').forEach(btn => {
    btn.addEventListener('click', () => {
      const fmt = btn.dataset.format;
      const f = formatos[fmt];
      if (!f) return;

      const texto = f.example || 'texto';
      const resultado = f.prefix + texto + f.suffix;
      copyToClipboard(resultado);
      showToast(`Copiado: ${fmt}`);
    });
  });

  async function copyToClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      // Fallback
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
  }

  // Copiar bloques de código de referencia
  document.querySelectorAll('.ref-card pre').forEach(pre => {
    pre.style.cursor = 'copy';
    pre.title = 'Click para copiar';
    pre.addEventListener('click', () => {
      const code = pre.querySelector('code').textContent;
      copyToClipboard(code);
      showToast('Ejemplo copiado');
    });
  });

  // Atajos de teclado
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      const linkBtn = document.querySelector('[data-format="link"]');
      if (linkBtn) linkBtn.click();
    }
  });
});