// Membership and receipt submission stay in the Mini App.
let paymentInfo = null;
let paymentLoading = false;
let receiptBusy = false;
let receiptRequestId = null;
let profileError = '';
let membershipInstructionsOpen = false;
let foreignRequestBusy = false;

function foreignAccessSection(p) {
  if(p.user.is_lifetime_free)return '';
  const request=p.foreign_request;
  if(request?.access_granted)return '<section class="payment-notice"><b>Участие без оплаты для участников не из Беларуси</b><p>Вам предоставлен доступ до подключения международной оплаты. Когда она появится, мы сообщим об условиях продолжения участия. Автоматических списаний не будет.</p></section>';
  if(request?.status==='pending')return '<section class="payment-notice" role="status"><b>Заявка «Я не из Беларуси» на рассмотрении</b><p>Администратор рассмотрит заявку. Решение появится здесь и придёт в боте. Повторно отправлять её не нужно.</p></section>';
  if(request?.status==='rejected')return '<section class="payment-notice"><b>Заявка рассмотрена</b><p>Сейчас мы не можем предоставить доступ по вашей заявке. Если у вас есть вопросы, нажмите «Задать вопрос» ниже.</p></section>';
  if(request?.status==='approved')return '<section class="payment-notice"><b>Заявка «Я не из Беларуси» ранее одобрена</b><p>Текущий статус доступа указан выше. Если доступ изменился и у вас есть вопросы, напишите нам.</p></section>';
  return `<section class="card"><h3>Вы не из Беларуси?</h3><p>Пока мы не принимаем оплату из России и других стран за пределами Беларуси. Вы можете отправить заявку на участие без оплаты до подключения международных платежей. Доступ открывается после одобрения администратором.</p><button class="button secondary" onclick="submitForeignRequest(this)" ${p.test_mode?'disabled':''}>Я не из Беларуси</button><p id="foreign-request-status" role="status">${p.test_mode?'В тестовом режиме настоящие заявки не отправляются.':''}</p></section>`;
}

async function submitForeignRequest(button) {
  if(foreignRequestBusy||paymentInfo?.test_mode||previewMode)return;
  foreignRequestBusy=true;button.disabled=true;
  const status=document.getElementById('foreign-request-status');status.textContent='Отправляем заявку…';
  let sent=false;
  try{await api('/payment/foreign-request',{method:'POST'});sent=true;status.textContent='Заявка зарегистрирована. Ожидайте решения администратора.';}
  catch(_){status.textContent='Не удалось отправить заявку. Попробуйте ещё раз — повторная заявка не создастся.';button.disabled=false;}
  finally{foreignRequestBusy=false;}
  if(sent)await refreshPayment(true);
}

function openMembership() {
  membershipInstructionsOpen = true;
  go('profile');
}

function paymentDate(value) {
  return value ? new Date(value).toLocaleDateString('ru-RU') : '';
}

function profile() {
  const u = state.data.user;
  const p = paymentInfo;
  const mode = state.testMode || (previewMode ? 'preview' : 'normal');
  if (!p || p.mode !== mode) {
    queueMicrotask(() => refreshPayment());
    return `<div class="brand">Профиль</div><section class="hero"><h1>${esc(u.full_name)}</h1></section><div class="card" role="status">${profileError ? `${esc(profileError)}<button class="button" onclick="refreshPayment()">Повторить</button>` : 'Загружаем информацию об участии…'}</div>${nav()}`;
  }
  const user = p.user, latest = p.latest_payment, pending = latest?.status === 'pending';
  const lifetime = user.is_lifetime_free, active = user.state === 'active';
  const foreignGranted = Boolean(p.foreign_request?.access_granted);
  const title = foreignGranted ? 'Доступ предоставлен' : lifetime ? 'Бессрочный доступ' : active ? 'Вы участник клуба' : user.state === 'expired' ? 'Срок участия закончился' : 'Бесплатный доступ';
  const hint = foreignGranted ? 'Все материалы и курсы доступны до подключения международной оплаты.' : lifetime ? 'Все материалы и курсы доступны. Оплата не требуется.' : active ? `Доступ ${user.access_end_at ? 'до ' + paymentDate(user.access_end_at) : 'активен'}.` : 'Вам доступны бесплатные материалы. Вступите в клуб, чтобы открыть курсы и всю библиотеку.';
  const action = active ? 'Продлить участие' : user.state === 'expired' ? 'Возобновить доступ' : 'Вступить в клуб';
  const paymentStatus = foreignGranted || !latest ? '' : pending ? '<div class="payment-notice" role="status"><b>Чек отправлен на проверку</b><p>Повторно отправлять чек не нужно. После подтверждения доступ обновится автоматически.</p></div>' : latest.status === 'rejected' ? `<div class="payment-notice payment-error"><b>Оплата пока не подтверждена</b><p>${esc(latest.reason)}</p><p>Ниже можно прикрепить новый чек.</p></div>` : `<div class="payment-notice"><b>Оплата подтверждена</b><p>${paymentDate(latest.confirmed_at)}</p></div>`;
  return `<div class="brand"><span class="mark">✦</span> Профиль</div><section class="hero"><span class="eyebrow">Ваше участие</span><h1>${esc(user.full_name)}</h1></section><section class="card membership-card"><h2>${title}</h2><p>${esc(hint)}</p>${!lifetime && !foreignGranted ? `<div class="membership-price">${esc(p.amount_label)}</div>` : ''}</section>${paymentStatus}${foreignAccessSection(p)}${!lifetime && !foreignGranted && !pending ? `<details class="card payment-details" ${membershipInstructionsOpen || latest?.status === 'rejected' ? 'open' : ''}><summary class="button">${action}</summary><div class="payment-body"><h2>Как оплатить участие</h2><p>Переведите <b>${esc(p.amount_label)}</b> удобным способом, затем прикрепите чек здесь.</p><div class="payment-requisite"><span>Перевод на карту</span><strong>${esc(p.card)}</strong><button type="button" class="button secondary" data-copy="${esc(p.card)}" onclick="copyPaymentValue(this)">Скопировать номер карты</button></div><div class="payment-requisite"><span>Альфа-Банк Беларусь · по номеру телефона</span><strong>${esc(p.phone)}</strong><button type="button" class="button secondary" data-copy="${esc(p.phone)}" onclick="copyPaymentValue(this)">Скопировать телефон</button></div><h3>Уже оплатили?</h3><p>Прикрепите фото, скриншот или PDF чека. После проверки доступ появится здесь.</p>${p.test_mode ? '<p class="payment-notice">Это тестовый режим. Отправка настоящих чеков отключена.</p>' : ''}<form id="receipt-form" onsubmit="sendProfileReceipt(event)"><label class="receipt-picker"><span>＋ Прикрепить чек</span><input type="file" name="receipt" accept="image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf" onchange="receiptSelected(this)" ${p.test_mode ? 'disabled' : ''} required></label><small>JPG, PNG, WEBP или PDF · до 10 МБ</small><div id="receipt-preview"></div><div id="receipt-progress" hidden><progress max="100" value="0"></progress></div><p id="receipt-status" role="status" aria-live="polite"></p><button class="button" type="submit" ${p.test_mode ? 'disabled' : ''}>Отправить на проверку</button></form></div></details>` : ''}<p class="profile-refresh-note">Статус обновляется автоматически, пока открыт профиль.</p><button class="back" onclick="refreshPayment(true)">Обновить статус</button><section class="card profile-help"><h3>Нужна помощь?</h3><p>Если возник вопрос об оплате или доступе, напишите нам.</p><a class="button secondary" href="${esc(p.contact_url)}" target="_blank" rel="noopener">Задать вопрос</a></section>${nav()}`;
}

async function refreshPayment(force = false) {
  if (paymentLoading || receiptBusy || foreignRequestBusy || state.tab !== 'profile') return;
  paymentLoading = true;
  const mode = state.testMode || (previewMode ? 'preview' : 'normal');
  try {
    const next = previewMode ? {user:state.data.user, amount_label:'10 BYN / месяц', card:'5208130008671731', phone:'+375 25 91 29 014', contact_url:'https://t.me/kopytov_v_a', latest_payment:null, test_mode:true} : await api('/payment');
    if (mode !== (state.testMode || (previewMode ? 'preview' : 'normal'))) return;
    next.mode = mode;
    const changed = !paymentInfo || JSON.stringify(next) !== JSON.stringify(paymentInfo);
    const accessChanged = state.data.user.state !== next.user.state;
    paymentInfo = next;
    profileError = '';
    Object.assign(state.data.user, next.user);
    if (accessChanged && !previewMode) state.data = await api('/bootstrap');
    if (state.tab === 'profile' && (changed || force)) shell(profile());
  } catch (_) {
    profileError = 'Не удалось обновить статус. Проверьте соединение и попробуйте ещё раз.';
    if (state.tab === 'profile' && !paymentInfo) {
      // Render once, without triggering an endless retry loop.
      document.querySelector('.card')?.replaceChildren(Object.assign(document.createElement('p'), {textContent:profileError}), Object.assign(document.createElement('button'), {className:'button',textContent:'Повторить',onclick:()=>refreshPayment(true)}));
    }
  } finally { paymentLoading = false; }
}

window.copyPaymentValue = async button => {
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    const text = button.textContent;
    button.textContent = 'Скопировано ✓';
    setTimeout(() => { button.textContent = text; }, 1800);
  } catch (_) {
    const input = document.createElement('input');
    input.value = button.dataset.copy;
    button.after(input); input.focus(); input.select();
    button.textContent = 'Выделено — скопируйте номер';
  }
};

let receiptPreviewUrl;
window.receiptSelected = input => {
  const file = input.files[0], box = document.getElementById('receipt-preview');
  if (receiptPreviewUrl) URL.revokeObjectURL(receiptPreviewUrl);
  box.replaceChildren();
  document.getElementById('receipt-status').textContent = '';
  receiptRequestId = null;
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    input.value = '';
    document.getElementById('receipt-status').textContent = 'Файл слишком большой. Максимум — 10 МБ.';
    return;
  }
  const name = document.createElement('p'); name.textContent = file.name; box.append(name);
  if (file.type.startsWith('image/')) {
    receiptPreviewUrl = URL.createObjectURL(file);
    const img = document.createElement('img'); img.src = receiptPreviewUrl; img.alt = 'Выбранный чек'; box.append(img);
  }
};

window.sendProfileReceipt = event => {
  event.preventDefault();
  if (receiptBusy || paymentInfo?.test_mode || previewMode) return;
  const form = event.currentTarget, status = document.getElementById('receipt-status');
  const data = new FormData(form);
  if (!data.get('receipt')?.size) { status.textContent = 'Выберите чек.'; return; }
  receiptRequestId ||= crypto.randomUUID();
  receiptBusy = true;
  form.querySelectorAll('button,input').forEach(x => x.disabled = true);
  const progress = document.querySelector('#receipt-progress progress');
  progress.parentElement.hidden = false; progress.value = 0;
  status.textContent = 'Загружаем чек… Оставьте приложение открытым до подтверждения отправки.';
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/mini-app/api/payment/receipt');
  xhr.timeout = 120000;
  xhr.setRequestHeader('X-Telegram-Init-Data', initData());
  xhr.setRequestHeader('X-Payment-Request', receiptRequestId);
  if (state.testMode) xhr.setRequestHeader('X-Nastaunik-Test-Mode', state.testMode);
  xhr.upload.onprogress = e => { if (e.lengthComputable) progress.value = Math.round(e.loaded/e.total*100); };
  xhr.upload.onload = () => { status.textContent = 'Чек загружен. Сохраняем заявку…'; };
  const finish = () => { receiptBusy = false; form.querySelectorAll('button,input').forEach(x=>x.disabled=false); };
  xhr.onload = () => {
    finish();
    if (xhr.status >= 200 && xhr.status < 300) {
      status.textContent = 'Чек принят. Ожидайте проверки.';
      form.querySelector('button[type=submit]').disabled = true;
      refreshPayment(true);
    } else status.textContent = xhr.responseText && !xhr.responseText.includes('<') ? xhr.responseText : 'Не удалось отправить чек. Попробуйте ещё раз.';
  };
  xhr.onerror = xhr.ontimeout = () => { finish(); status.textContent = 'Связь прервалась. Повторите отправку — повторная заявка не создастся.'; };
  xhr.send(data);
};

setInterval(() => { if (!document.hidden && state.tab === 'profile') refreshPayment(); }, 15000);
document.addEventListener('visibilitychange', () => { if (!document.hidden && state.tab === 'profile') refreshPayment(); });
