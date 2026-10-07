(() => {
  document.addEventListener('DOMContentLoaded', () => {
    // Keep one real editor and its upload/history behavior, within lesson context.
    const outline = document.querySelector('.course-outline');
    if (outline) {
      const toggle = document.createElement('button');
      toggle.type = 'button'; toggle.className = 'outline-toggle';
      toggle.textContent = 'Структура курса · выбрать урок';
      toggle.setAttribute('aria-expanded', 'false');
      outline.id = 'course-outline'; toggle.setAttribute('aria-controls', outline.id);
      outline.before(toggle);
      toggle.onclick = () => { const open = outline.classList.toggle('outline-open'); toggle.setAttribute('aria-expanded', String(open)); };
    }
    const names = {'×':'Удалить', '✎':'Редактировать', '↶':'Отменить изменение', '↷':'Повторить изменение', '↑':'Переместить выше', '↓':'Переместить ниже', 'Ж':'Полужирный текст', 'К':'Курсив'};
    const labelButtons = () => document.querySelectorAll('button').forEach(button => {
      const name = button.title || names[button.textContent.trim()];
      if (name && !button.hasAttribute('aria-label')) button.setAttribute('aria-label', name);
    });
    labelButtons();
    document.querySelectorAll('.analytics-table table').forEach(table => {
      const headings = [...table.querySelectorAll('thead th')].map(cell => cell.textContent.trim());
      table.querySelectorAll('tbody tr').forEach(row => [...row.cells].forEach((cell,index) => {if(index && headings[index])cell.dataset.label=headings[index];}));
    });
    new MutationObserver(labelButtons).observe(document.body, {childList:true, subtree:true});
    document.querySelectorAll('a').forEach(link => {
      if (link.textContent.trim() !== 'Открыть редактор лонгрида') return;
      link.addEventListener('click', event => {
        if (event.ctrlKey || event.metaKey || event.shiftKey) return;
        event.preventDefault();
        const dialog = document.createElement('dialog'); dialog.className = 'longread-dialog';
        const close = document.createElement('button'); close.type = 'button'; close.textContent = '← Вернуться к уроку';
        const frame = document.createElement('iframe'); frame.title = 'Редактор статьи урока'; frame.src = link.href;
        const heading = document.createElement('div'); heading.className = 'longread-heading'; heading.append(close);
        dialog.setAttribute('aria-label', 'Статья урока');
        dialog.append(heading, frame); document.body.append(dialog); dialog.showModal();
        frame.addEventListener('load', () => {
          const doc = frame.contentDocument;
          if (!doc) return;
          doc.querySelector('nav[aria-label="Разделы админки"]')?.remove();
          const back = doc.querySelector('main > a');
          if (back?.textContent.includes('Вернуться к уроку')) back.remove();
        });
        close.onclick = () => {
          // Do not silently discard unsaved content in the embedded editor.
          if (!confirm('Вернуться к уроку? Убедитесь, что статья сохранена.')) return;
          dialog.close(); location.reload();
        };
        dialog.addEventListener('cancel', event => {event.preventDefault(); close.click();});
      });
    });
  });
})();
