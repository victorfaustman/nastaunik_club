(() => {
  'use strict';
  const toast = text => {
    const node = document.getElementById('toast');
    node.textContent = text;
    setTimeout(() => { node.textContent = ''; }, 3500);
  };
  const toggle = document.querySelector('.menu-toggle');
  toggle?.addEventListener('click', () => {
    const open = document.querySelector('.sidebar').classList.toggle('nav-open');
    toggle.setAttribute('aria-expanded', String(open));
  });
  const panels = [...document.querySelectorAll('.tab-panel')];
  const showTab = () => {
    const id = panels.some(p => '#' + p.id === location.hash) ? location.hash.slice(1) : 'overview';
    panels.forEach(p => { p.hidden = p.id !== id; });
    document.querySelectorAll('.tabs a').forEach(a => a.setAttribute('aria-current', String(a.hash === '#' + id)));
  };
  if (panels.length) { showTab(); window.addEventListener('hashchange', showTab); }
  document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(button.dataset.copy); toast('ID скопирован'); }
    catch { toast('Не удалось скопировать. ID указан на кнопке.'); }
  }));
  document.querySelectorAll('[data-back]').forEach(button => button.addEventListener('click', () => history.back()));
  document.querySelectorAll('form').forEach(form => form.addEventListener('submit', event => {
    const question = event.submitter?.dataset.confirm || form.dataset.confirm;
    if (question && !window.confirm(question)) { event.preventDefault(); return; }
    if (form.dataset.submitting) { event.preventDefault(); return; }
    form.dataset.submitting = '1';
    document.body.setAttribute('aria-busy', 'true');
    // Do not disable the submitter: its name and formaction must reach the server.
    if (event.submitter) event.submitter.textContent = 'Обрабатываем…';
  }));
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  const form = document.getElementById('broadcast-form');
  if (!form) return;
  const message = document.getElementById('broadcast-message');
  const count = document.getElementById('message-count');
  const updateLength = () => { count.textContent = `${message.value.length} / 4096`; };
  message.addEventListener('input', updateLength);
  document.querySelectorAll('[data-template]').forEach(button => button.addEventListener('click', () => {
    if (message.value && !confirm('Заменить текущий текст выбранным шаблоном?')) return;
    message.value = button.dataset.template;
    updateLength(); message.focus();
  }));
  let controller;
  const updateAudience = async () => {
    controller?.abort(); controller = new AbortController();
    const output = document.getElementById('audience-count');
    const submit = document.getElementById('preview-submit');
    output.textContent = 'Проверяем аудиторию…'; submit.disabled = true;
    const params = new URLSearchParams({status_filter: form.elements.status_filter.value, type_filter: form.elements.type_filter.value});
    try {
      const response = await fetch(form.dataset.audienceUrl + '?' + params, {signal: controller.signal, cache: 'no-store'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Не удалось проверить аудиторию.');
      output.textContent = data.count ? `Получателей: ${data.count}` : 'По этим условиям получателей нет. Измените фильтры.';
      submit.disabled = !data.count;
    } catch (error) {
      if (error.name === 'AbortError') return;
      output.textContent = error.message + ' Повторите выбор фильтра.';
    }
  };
  form.querySelectorAll('select').forEach(select => select.addEventListener('change', updateAudience));
  updateAudience(); updateLength();
})();
