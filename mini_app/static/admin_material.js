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
  `;
  document.head.appendChild(style);

  const cleanSync = () => {
    const clone = editor.cloneNode(true);
    clone.querySelectorAll('.media-remove').forEach((button) => button.remove());
    source.value = clone.innerHTML;
  };
  window.sync = cleanSync;

  function addRemoveButton(figure) {
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
});
