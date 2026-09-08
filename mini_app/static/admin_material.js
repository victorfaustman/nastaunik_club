document.addEventListener('DOMContentLoaded', () => {
  const editor = document.getElementById('content-editor');
  const source = document.getElementById('content-source');
  if (!editor || !source) return;

  const style = document.createElement('style');
  style.textContent = `
    .editor figure.inline-media .media-remove {
      position: absolute; top: 10px; right: 10px; z-index: 2;
      width: 34px; height: 34px; padding: 0; border-radius: 50%;
      background: #fff; color: #a44439; box-shadow: 0 3px 14px #0003;
      font-size: 22px; line-height: 1;
    }
    .editor figure.inline-media .media-remove:hover { background: #fff0ed; }
    .video-status-panel {
      margin: 0 0 14px; padding: 14px 16px; border: 1px solid #e7e0da;
      border-radius: 14px; background: #fff; color: #292421;
    }
    .video-status-row { display: flex; gap: 11px; align-items: center; }
    .video-status-row + .video-status-row { margin-top: 10px; }
    .video-status-icon {
      width: 30px; height: 30px; flex: 0 0 30px; border-radius: 50%;
      display: grid; place-items: center; background: #f3ece7; color: #c56349;
    }
    .video-status-row.is-busy .video-status-icon {
      border: 3px solid #eaded7; border-top-color: #c56349; background: transparent;
      animation: video-status-spin .85s linear infinite; color: transparent;
    }
    .video-status-copy { min-width: 0; flex: 1; }
    .video-status-copy b, .video-status-copy small { display: block; }
    .video-status-copy small { color: #817873; margin-top: 1px; }
    .video-status-row.is-failed .video-status-icon { background: #fff0ed; color: #a44439; }
    @keyframes video-status-spin { to { transform: rotate(360deg); } }
  `;
  document.head.appendChild(style);

  const cleanSync = () => {
    const clone = editor.cloneNode(true);
    clone.querySelectorAll('.media-remove').forEach((button) => button.remove());
    source.value = clone.innerHTML;
  };
  window.sync = cleanSync;

  function addRemoveButton(figure) {
    figure.draggable = true;
    const caption = figure.querySelector(':scope > figcaption');
    if (caption) caption.contentEditable = 'true';
    figure.querySelectorAll('video').forEach((video) => {
      video.preload = 'metadata';
      video.playsInline = true;
    });
    if (figure.querySelector(':scope > .media-remove')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'media-remove';
    button.contentEditable = 'false';
    button.title = 'Удалить изображение или видео';
    button.setAttribute('aria-label', 'Удалить медиа');
    button.textContent = '×';
    button.addEventListener('mousedown', (event) => event.stopPropagation());
    button.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      figure.remove();
      cleanSync();
      if (typeof window.autosave === 'function') window.autosave();
    });
    figure.appendChild(button);
  }

  const installButtons = () => {
    editor.querySelectorAll('figure.inline-media').forEach(addRemoveButton);
  };
  installButtons();
  new MutationObserver(installButtons).observe(editor, { childList: true, subtree: true });

  document.getElementById('add-divider')?.addEventListener('click', () => {
    editor.focus();
    document.execCommand('insertHorizontalRule');
    cleanSync();
  });

  editor.addEventListener('paste', (event) => {
    const clipboard = event.clipboardData;
    const pastedHtml = clipboard?.getData('text/html');
    if (!pastedHtml) return;
    event.preventDefault();
    const template = document.createElement('template');
    template.innerHTML = pastedHtml;
    template.content.querySelectorAll('script,style,iframe,object,embed,form,input,button,meta,link').forEach((node) => node.remove());
    template.content.querySelectorAll('span,font').forEach((node) => node.replaceWith(...node.childNodes));
    template.content.querySelectorAll('*').forEach((node) => {
      [...node.attributes].forEach((attribute) => {
        const name = attribute.name.toLowerCase();
        if (name.startsWith('on') || ['style', 'id'].includes(name)) node.removeAttribute(attribute.name);
        if (['href', 'src', 'poster'].includes(name) && !/^(https?:|\/|#)/i.test(attribute.value)) node.removeAttribute(attribute.name);
      });
    });
    document.execCommand('insertHTML', false, template.innerHTML);
    cleanSync();
  });

  const form = document.getElementById('article-form');
  const removeCover = document.getElementById('remove-cover');
  const removeCoverButton = document.getElementById('remove-cover-button');
  const coverCurrent = document.getElementById('cover-current');
  const coverInput = document.getElementById('cover-input');
  const coverLabel = document.getElementById('cover-label');
  removeCoverButton?.addEventListener('click', () => {
    removeCover.value = '1';
    coverInput.value = '';
    coverCurrent.hidden = true;
    coverLabel.textContent = '＋ Загрузить другую обложку';
    document.getElementById('save-state').textContent = 'Обложка будет удалена после сохранения';
  });
  coverInput?.addEventListener('change', () => {
    if (!coverInput.files[0]) return;
    removeCover.value = '0';
    coverCurrent.hidden = false;
  });

  const materialId = form?.dataset.id;
  if (!form || !materialId) return;

  const statusPanel = document.createElement('div');
  statusPanel.id = 'video-status-panel';
  statusPanel.className = 'video-status-panel';
  statusPanel.hidden = true;
  form.querySelector('.topbar')?.after(statusPanel);

  const statusCopy = {
    waiting_save: ['○', 'Видео загружено', 'Нажмите «Сохранить», чтобы начать обработку.'],
    queued: ['…', 'Видео в очереди', 'Страницу уже можно закрыть — сервер продолжит работу.'],
    processing: ['', 'Адаптируем видео', 'Подготавливаем быструю версию для Mini App. Можно уйти со страницы.'],
    ready: ['✓', 'Видео готово', 'Оптимизированная версия доступна в Mini App.'],
    failed: ['!', 'Не удалось адаптировать видео', 'Исходный файл сохранён и остаётся доступен.'],
  };
  let pollTimer;

  function renderVideoJobs(jobs) {
    if (!jobs.length) {
      statusPanel.hidden = true;
      statusPanel.replaceChildren();
      return false;
    }
    statusPanel.hidden = false;
    statusPanel.replaceChildren(...jobs.map((job) => {
      const [icon, title, detail] = statusCopy[job.status] || ['•', 'Видео', job.status];
      const row = document.createElement('div');
      row.className = `video-status-row ${['queued', 'processing'].includes(job.status) ? 'is-busy' : ''} ${job.status === 'failed' ? 'is-failed' : ''}`;
      const iconNode = document.createElement('span');
      iconNode.className = 'video-status-icon';
      iconNode.textContent = icon;
      const copy = document.createElement('span');
      copy.className = 'video-status-copy';
      const strong = document.createElement('b');
      strong.textContent = title;
      const small = document.createElement('small');
      small.textContent = detail;
      copy.append(strong, small);
      row.append(iconNode, copy);
      return row;
    }));
    return jobs.some((job) => ['waiting_save', 'queued', 'processing'].includes(job.status));
  }

  async function pollVideoJobs() {
    clearTimeout(pollTimer);
    const data = new FormData();
    data.append('action', 'video_status');
    data.append('material_id', materialId);
    try {
      const response = await fetch(form.action, { method: 'POST', body: data });
      if (!response.ok) throw new Error('status request failed');
      const payload = await response.json();
      const busy = renderVideoJobs(payload.jobs || []);
      pollTimer = setTimeout(pollVideoJobs, busy ? 1800 : 10000);
    } catch (_) {
      pollTimer = setTimeout(pollVideoJobs, 5000);
    }
  }

  pollVideoJobs();
});
