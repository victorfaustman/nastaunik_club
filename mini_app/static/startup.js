(() => {
  let pending = true;
  let timer;
  function fail(reason) {
    if (!pending) return;
    clearTimeout(timer);
    const app = document.getElementById('app');
    const section = document.createElement('section');
    section.className = 'status';
    section.style.cssText = 'max-width:440px;margin:48px auto;padding:24px;text-align:center;font:16px/1.5 sans-serif;color:#24362e';
    const title = document.createElement('h1');
    title.textContent = 'Не удалось открыть клуб';
    const message = document.createElement('p');
    message.textContent = reason || 'Загрузка задержалась. Проверьте соединение и попробуйте ещё раз.';
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'button';
    retry.textContent = 'Повторить загрузку';
    retry.onclick = () => location.reload();
    retry.style.cssText = 'padding:12px 20px;background:#176847;color:white;border:0;border-radius:10px;font:inherit;cursor:pointer';
    const back = document.createElement('a');
    back.href = 'https://t.me/nastaunik_club_bot?start=restart';
    back.textContent = 'Вернуться в бот';
    back.style.cssText = 'display:block;margin-top:18px;color:#176847';
    section.append(title, message, retry, back);
    app.replaceChildren(section);
  }
  window.NastaunikStartup = {
    ready() { pending = false; clearTimeout(timer); },
    fail
  };
  window.addEventListener('error', event => {
    const source = event.target?.src || event.filename || '';
    if (source.includes('/mini-app/static/app.js')) fail('Не удалось загрузить приложение. Попробуйте открыть клуб ещё раз.');
  }, true);
  timer = setTimeout(() => fail(), 15000);
})();
