document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-add-kind]').forEach((button) => {
    button.addEventListener('click', () => {
      const container = button.closest('.add-block');
      container.querySelectorAll('[data-add-kind]').forEach((item) => item.classList.toggle('active', item === button));
      container.querySelectorAll('[data-add-form]').forEach((form) => form.classList.toggle('active', form.dataset.addForm === button.dataset.addKind));
    });
  });

  function sanitizePastedHtml(value) {
    const template = document.createElement('template');
    template.innerHTML = value;
    template.content.querySelectorAll('script,style,iframe,object,embed,form,input,button,meta,link').forEach((node) => node.remove());
    template.content.querySelectorAll('span,font').forEach((node) => node.replaceWith(...node.childNodes));
    template.content.querySelectorAll('*').forEach((node) => {
      [...node.attributes].forEach((attribute) => {
        const name = attribute.name.toLowerCase();
        if (name.startsWith('on') || ['style', 'id'].includes(name)) node.removeAttribute(attribute.name);
        if (['href', 'src', 'poster'].includes(name) && !/^(https?:|\/|#)/i.test(attribute.value)) node.removeAttribute(attribute.name);
      });
    });
    return template.innerHTML;
  }

  document.querySelectorAll('.course-longread').forEach((root) => {
    const form = root.closest('.course-block-form');
    const editor = root.querySelector('.course-editor');
    const source = root.querySelector('.course-editor-source');
    const status = root.querySelector('.editor-status');
    const picker = root.querySelector('.inline-media-file');
    let savedRange = null;
    let draggedMedia = null;
    let saveTimer = null;

    function sync() {
      const clean = editor.cloneNode(true);
      clean.querySelectorAll('.media-remove').forEach((button) => button.remove());
      source.value = clean.innerHTML;
    }

    function autosave() {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(async () => {
        sync();
        status.textContent = 'Сохраняем…';
        const data = new FormData(form);
        data.set('ajax', '1');
        try {
          const response = await fetch(form.getAttribute('action') || window.location.href, { method: 'POST', body: data });
          if (!response.ok) throw new Error('save failed');
          status.textContent = 'Сохранено';
        } catch (_) {
          status.textContent = 'Не удалось сохранить';
        }
      }, 900);
    }

    function rememberRange() {
      const selection = getSelection();
      if (selection.rangeCount && editor.contains(selection.anchorNode)) savedRange = selection.getRangeAt(0).cloneRange();
    }

    function wireFigure(figure) {
      if (figure.dataset.courseWired === '1') return;
      figure.dataset.courseWired = '1';
      figure.draggable = true;
      figure.querySelectorAll('figcaption').forEach((caption) => caption.remove());
      figure.querySelectorAll('video').forEach((video) => {
        video.preload = 'metadata';
        video.playsInline = true;
      });
      if (!figure.querySelector(':scope > .media-remove')) {
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'media-remove';
        remove.contentEditable = 'false';
        remove.title = 'Удалить изображение или видео';
        remove.textContent = '×';
        remove.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
          figure.remove();
          sync();
          autosave();
        });
        figure.appendChild(remove);
      }
      figure.addEventListener('dragstart', () => { draggedMedia = figure; });
    }

    editor.querySelectorAll('figure.inline-media').forEach(wireFigure);
    new MutationObserver(() => editor.querySelectorAll('figure.inline-media').forEach(wireFigure))
      .observe(editor, { childList: true, subtree: true });
    editor.addEventListener('mouseup', rememberRange);
    editor.addEventListener('keyup', rememberRange);
    editor.addEventListener('input', () => {
      sync();
      autosave();
    });
    editor.addEventListener('paste', (event) => {
      const pastedHtml = event.clipboardData?.getData('text/html');
      if (!pastedHtml) return;
      event.preventDefault();
      document.execCommand('insertHTML', false, sanitizePastedHtml(pastedHtml));
      sync();
      autosave();
    });
    editor.addEventListener('dragover', (event) => event.preventDefault());
    editor.addEventListener('drop', (event) => {
      if (!draggedMedia) return;
      event.preventDefault();
      const range = document.caretRangeFromPoint?.(event.clientX, event.clientY);
      if (range) range.insertNode(draggedMedia);
      else editor.appendChild(draggedMedia);
      draggedMedia = null;
      sync();
      autosave();
    });

    root.querySelectorAll('[data-cmd]').forEach((button) => {
      button.addEventListener('click', () => {
        editor.focus();
        document.execCommand(button.dataset.cmd, false, button.dataset.value || null);
        sync();
        autosave();
      });
    });
    root.querySelector('[data-divider]').addEventListener('click', () => {
      editor.focus();
      document.execCommand('insertHorizontalRule');
      sync();
      autosave();
    });
    root.querySelector('[data-link]').addEventListener('click', () => {
      const url = prompt('Вставьте ссылку');
      if (!url) return;
      editor.focus();
      document.execCommand('createLink', false, url);
      sync();
      autosave();
    });
    root.querySelector('[data-media]').addEventListener('click', () => {
      rememberRange();
      picker.click();
    });
    picker.addEventListener('change', () => {
      const file = picker.files[0];
      if (!file) return;
      const data = new FormData();
      data.set('action', 'course_inline_upload');
      data.set('course_id', form.elements.course_id.value);
      data.set('lesson_id', form.elements.lesson_id.value);
      data.set('inline_file', file);
      const xhr = new XMLHttpRequest();
      xhr.open('POST', form.getAttribute('action') || window.location.href);
      status.textContent = 'Загружаем медиа…';
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) status.textContent = `Загружаем медиа… ${Math.round(event.loaded / event.total * 100)}%`;
      };
      xhr.onload = () => {
        if (xhr.status < 200 || xhr.status >= 300) {
          status.textContent = 'Не удалось загрузить медиа';
          return;
        }
        const item = JSON.parse(xhr.responseText);
        const figure = document.createElement('figure');
        const media = document.createElement(item.kind === 'video' ? 'video' : 'img');
        figure.className = 'inline-media';
        media.src = item.url;
        if (item.kind === 'video') {
          media.controls = true;
          media.preload = 'metadata';
          media.playsInline = true;
        }
        figure.appendChild(media);
        if (savedRange) {
          savedRange.deleteContents();
          savedRange.insertNode(figure);
        } else {
          editor.appendChild(figure);
        }
        const paragraph = document.createElement('p');
        paragraph.innerHTML = '<br>';
        figure.after(paragraph);
        wireFigure(figure);
        picker.value = '';
        sync();
        status.textContent = 'Медиа добавлено';
        autosave();
      };
      xhr.onerror = () => { status.textContent = 'Не удалось загрузить медиа'; };
      xhr.send(data);
    });

    form.addEventListener('submit', sync);
    sync();
  });

  document.querySelectorAll('.course-file-form input[type="file"]').forEach((input) => {
    input.addEventListener('change', () => {
      const label = input.closest('.file-drop')?.querySelector('b');
      if (label && input.files[0]) label.textContent = `Выбрано: ${input.files[0].name}`;
    });
  });

  const videoStatuses = [...document.querySelectorAll('[data-video-status][data-video-block-id]')];
  if (videoStatuses.length) {
    const labels = { waiting_save: 'Ожидает сохранения', queued: 'В очереди на обработку', processing: 'Обрабатывается', failed: 'Ошибка обработки', ready: 'Готово' };
    const poll = async () => {
      let pending = false;
      for (const status of videoStatuses) {
        const form = status.closest('form');
        if (!form) continue;
        const data = new FormData();
        data.set('action', 'course_video_status');
        data.set('course_id', form.elements.course_id.value);
        data.set('lesson_id', form.elements.lesson_id.value);
        data.set('block_id', status.dataset.videoBlockId);
        data.set('ajax', '1');
        try {
          const response = await fetch(form.action, { method: 'POST', body: data });
          if (!response.ok) continue;
          const value = await response.json();
          const next = value.status || 'ready';
          status.textContent = labels[next] || next;
          status.className = `video-status video-status-${next}`;
          if (next === 'ready') {
            const video = form.querySelector('video');
            if (video) { video.controls = true; if (value.poster_url) video.poster = value.poster_url; video.load(); }
          } else if (next === 'queued' || next === 'processing' || next === 'waiting_save') pending = true;
        } catch (_) { pending = true; }
      }
      if (pending) window.setTimeout(poll, 2500);
    };
    window.setTimeout(poll, 1200);
  }

  const uploadOverlay = document.createElement('div');
  uploadOverlay.className = 'course-upload-overlay';
  uploadOverlay.innerHTML = '<div class="course-upload-box"><b>Загружаем файл…</b><div class="course-upload-track"><i></i></div></div>';
  document.body.appendChild(uploadOverlay);
  const uploadText = uploadOverlay.querySelector('b');
  const uploadProgress = uploadOverlay.querySelector('i');
  document.querySelectorAll('.course-file-form').forEach((form) => {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const xhr = new XMLHttpRequest();
      xhr.open('POST', form.getAttribute('action') || window.location.href);
      uploadText.textContent = form.querySelector('input[type="file"]')?.files.length ? 'Загружаем файл…' : 'Сохраняем…';
      uploadProgress.style.width = '8%';
      uploadOverlay.classList.add('active');
      xhr.upload.onprogress = (progressEvent) => {
        if (!progressEvent.lengthComputable) return;
        const percent = Math.max(8, Math.round(progressEvent.loaded / progressEvent.total * 100));
        uploadProgress.style.width = `${percent}%`;
        uploadText.textContent = `Загружаем файл… ${percent}%`;
      };
      xhr.upload.onload = () => {
        uploadProgress.style.width = '100%';
        uploadText.textContent = 'Сохраняем и запускаем обработку…';
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) window.location.href = xhr.responseURL || window.location.href;
        else {
          uploadOverlay.classList.remove('active');
          alert('Не удалось загрузить файл');
        }
      };
      xhr.onerror = () => {
        uploadOverlay.classList.remove('active');
        alert('Не удалось загрузить файл');
      };
      xhr.send(new FormData(form));
    });
  });
});
