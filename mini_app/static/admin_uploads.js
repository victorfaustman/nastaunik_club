(() => {
  const noticeKey = 'nastaunik-admin-upload-notice';
  const ranges = new WeakMap();
  let activeUploads = 0;
  let panel;
  let list;

  function ensurePanel() {
    if (panel) return panel;
    const style = document.createElement('style');
    style.textContent = `
      .admin-upload-center{position:fixed;z-index:100;right:22px;bottom:22px;width:min(390px,calc(100vw - 28px));padding:14px;border:1px solid #e7e0da;border-radius:18px;background:#fff;box-shadow:0 18px 55px #2b211b2b;color:#292421;font:14px/1.4 system-ui,sans-serif}
      .admin-upload-center[hidden]{display:none}.admin-upload-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:1px 2px 10px}.admin-upload-head b{font-size:14px}.admin-upload-head span{color:#817873;font-size:12px}
      .admin-upload-list{display:grid;gap:9px}.admin-upload-item{display:grid;grid-template-columns:34px minmax(0,1fr) auto;gap:10px;align-items:center;padding:10px;border-radius:13px;background:#f7f3f0}.admin-upload-icon{width:34px;height:34px;display:grid;place-items:center;border-radius:10px;background:#efe4dd;color:#c56349;font-weight:900}.admin-upload-copy{min-width:0}.admin-upload-name,.admin-upload-state{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.admin-upload-name{font-weight:750}.admin-upload-state{margin-top:2px;color:#817873;font-size:11px}.admin-upload-percent{color:#817873;font-size:12px;font-weight:750}
      .admin-upload-track{grid-column:2/4;height:5px;overflow:hidden;border-radius:99px;background:#e7ddd7}.admin-upload-track i{display:block;width:0;height:100%;border-radius:inherit;background:#c56349;transition:width .18s ease}.admin-upload-item.processing .admin-upload-track i{width:100%!important;background:linear-gradient(90deg,#c56349,#efb09e,#c56349);background-size:200% 100%;animation:admin-upload-flow 1.1s linear infinite}.admin-upload-item.done .admin-upload-icon{background:#e2f1e6;color:#2f7147}.admin-upload-item.done .admin-upload-track i{background:#2f7147}.admin-upload-item.failed .admin-upload-icon{background:#fff0ed;color:#a44439}.admin-upload-close{width:25px;height:25px;padding:0;border:0;border-radius:8px;background:transparent;color:#817873;cursor:pointer}.admin-upload-close:hover{background:#fff;color:#a44439}@keyframes admin-upload-flow{to{background-position:-200% 0}}
      @media(max-width:600px){.admin-upload-center{right:14px;bottom:14px;width:calc(100vw - 28px)}}
    `;
    document.head.append(style);
    panel = document.createElement('aside');
    panel.className = 'admin-upload-center';
    panel.hidden = true;
    panel.setAttribute('aria-live', 'polite');
    panel.innerHTML = '<div class="admin-upload-head"><b>Загрузка медиа</b><span>Можно продолжать работу</span></div><div class="admin-upload-list"></div>';
    document.body.append(panel);
    list = panel.querySelector('.admin-upload-list');
    return panel;
  }

  function readableSize(size) {
    if (!size) return '';
    if (size < 1048576) return `${Math.max(1, Math.round(size / 1024))} КБ`;
    return `${(size / 1048576).toFixed(size < 10485760 ? 1 : 0)} МБ`;
  }

  function createItem(file, title) {
    ensurePanel().hidden = false;
    const item = document.createElement('div');
    item.className = 'admin-upload-item';
    const name = file?.name || title || 'Медиафайл';
    const size = readableSize(file?.size || 0);
    item.innerHTML = `<span class="admin-upload-icon">↑</span><span class="admin-upload-copy"><span class="admin-upload-name"></span><span class="admin-upload-state"></span></span><span class="admin-upload-percent">0%</span><span class="admin-upload-track"><i></i></span>`;
    item.querySelector('.admin-upload-name').textContent = name;
    item.querySelector('.admin-upload-state').textContent = [title, size].filter(Boolean).join(' · ') || 'Подготовка к загрузке';
    list.prepend(item);
    return item;
  }

  function setProgress(item, percent, text) {
    const value = Math.max(0, Math.min(100, Math.round(percent)));
    item.querySelector('.admin-upload-track i').style.width = `${value}%`;
    item.querySelector('.admin-upload-percent').textContent = `${value}%`;
    if (text) item.querySelector('.admin-upload-state').textContent = text;
  }

  function finishItem(item, text, failed = false) {
    item.classList.remove('processing');
    item.classList.add(failed ? 'failed' : 'done');
    item.querySelector('.admin-upload-icon').textContent = failed ? '!' : '✓';
    item.querySelector('.admin-upload-state').textContent = text;
    item.querySelector('.admin-upload-percent').replaceWith(Object.assign(document.createElement('button'), {
      type: 'button', className: 'admin-upload-close', textContent: '×', title: 'Закрыть',
      onclick: () => {
        item.remove();
        if (!list.children.length) panel.hidden = true;
      },
    }));
    if (!failed) setTimeout(() => {
      item.remove();
      if (!list.children.length) panel.hidden = true;
    }, 6500);
  }

  function upload(url, data, options = {}) {
    const file = options.file || [...data.values()].find((value) => value instanceof File && value.size);
    const item = createItem(file, options.title || 'Медиафайл');
    activeUploads += 1;
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', url);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) setProgress(item, event.loaded / event.total * 100, 'Загружаем на сервер…');
      };
      xhr.upload.onload = () => {
        setProgress(item, 100, options.processingText || 'Сохраняем файл…');
        item.classList.add('processing');
      };
      xhr.onload = () => {
        activeUploads = Math.max(0, activeUploads - 1);
        if (xhr.status < 200 || xhr.status >= 300) {
          finishItem(item, 'Не удалось загрузить файл', true);
          reject(new Error(xhr.responseText || 'upload failed'));
          return;
        }
        const doneText = options.background ? 'Загружено · обработка продолжится в фоне' : 'Файл загружен';
        finishItem(item, doneText);
        let json = null;
        try { json = JSON.parse(xhr.responseText); } catch (_) {}
        resolve({ xhr, json, responseURL: xhr.responseURL });
      };
      xhr.onerror = () => {
        activeUploads = Math.max(0, activeUploads - 1);
        finishItem(item, 'Соединение прервано — попробуйте ещё раз', true);
        reject(new Error('network error'));
      };
      xhr.send(data);
    });
  }

  function rememberSelection() {
    const selection = window.getSelection();
    if (!selection?.rangeCount) return;
    const editor = selection.anchorNode?.parentElement?.closest?.('#content-editor,.course-editor')
      || (selection.anchorNode?.nodeType === Node.ELEMENT_NODE && selection.anchorNode.matches?.('#content-editor,.course-editor') ? selection.anchorNode : null);
    if (editor) ranges.set(editor, selection.getRangeAt(0).cloneRange());
  }

  function insertInlineMedia(editor, item) {
    const figure = document.createElement('figure');
    figure.className = 'inline-media';
    figure.draggable = true;
    const media = document.createElement(item.kind === 'video' ? 'video' : 'img');
    media.src = item.url;
    if (item.kind === 'video') {
      media.controls = true;
      media.preload = 'metadata';
      media.playsInline = true;
    }
    figure.append(media);
    const range = ranges.get(editor);
    if (range && editor.contains(range.commonAncestorContainer)) {
      range.deleteContents();
      range.insertNode(figure);
    } else {
      editor.append(figure);
    }
    const paragraph = document.createElement('p');
    paragraph.innerHTML = '<br>';
    figure.after(paragraph);
    editor.dispatchEvent(new Event('input', { bubbles: true }));
  }

  document.addEventListener('selectionchange', rememberSelection);
  document.addEventListener('change', (event) => {
    const input = event.target.closest?.('#inline-media-file,.inline-media-file');
    if (!input || !input.files?.[0]) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const file = input.files[0];
    const root = input.closest('.course-longread');
    const editor = root?.querySelector('.course-editor') || document.getElementById('content-editor');
    const form = root?.closest('form') || document.getElementById('article-form');
    if (!editor || !form) return;
    const data = new FormData();
    if (root) {
      data.set('action', 'course_inline_upload');
      data.set('course_id', form.elements.course_id.value);
      data.set('lesson_id', form.elements.lesson_id.value);
    } else {
      data.set('action', 'inline_upload');
    }
    data.set('inline_file', file);
    upload(form.action, data, {
      file,
      title: 'Медиа в тексте',
      processingText: file.type.startsWith('video/') ? 'Сохраняем видео…' : 'Сохраняем изображение…',
      background: file.type.startsWith('video/'),
    }).then(({ json }) => {
      if (!json?.url) throw new Error('empty upload response');
      insertInlineMedia(editor, json);
      input.value = '';
      const status = root?.querySelector('.editor-status') || document.getElementById('save-state');
      if (status) status.textContent = json.waiting_save ? 'Видео загружено — сохраните материал' : 'Медиа добавлено';
    }).catch(() => {
      const status = root?.querySelector('.editor-status') || document.getElementById('save-state');
      if (status) status.textContent = 'Не удалось загрузить медиа';
    });
  }, true);

  document.addEventListener('submit', (event) => {
    const form = event.target.closest?.('form[data-media-upload]');
    if (!form) return;
    const file = [...form.querySelectorAll('input[type="file"]')].map((input) => input.files?.[0]).find(Boolean);
    if (!file) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (activeUploads) {
      ensurePanel().querySelector('.admin-upload-head span').textContent = 'Дождитесь завершения текущей загрузки';
      return;
    }
    if (typeof window.sync === 'function') window.sync();
    upload(form.action, new FormData(form), {
      file,
      title: form.dataset.uploadLabel || 'Медиафайл',
      processingText: file.type.startsWith('video/') ? 'Сохраняем и запускаем обработку…' : 'Сохраняем файл…',
      background: file.type.startsWith('video/'),
    }).then(({ responseURL }) => {
      sessionStorage.setItem(noticeKey, file.type.startsWith('video/') ? 'Видео загружено · обработка идёт в фоне' : 'Файл успешно загружен');
      window.location.href = responseURL || window.location.href;
    }).catch(() => {});
  }, true);

  window.addEventListener('beforeunload', (event) => {
    if (!activeUploads) return;
    event.preventDefault();
    event.returnValue = '';
  });

  window.AdminUploads = { upload };

  window.addEventListener('DOMContentLoaded', () => {
    const notice = sessionStorage.getItem(noticeKey);
    if (!notice) return;
    sessionStorage.removeItem(noticeKey);
    const item = createItem(null, 'Последняя загрузка');
    setProgress(item, 100, notice);
    finishItem(item, notice);
  });
})();
