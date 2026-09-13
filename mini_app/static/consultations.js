let consultationData=null, consultationMode=null, consultationLoading=false, consultationDate='';
const goBeforeConsultations=window.go;
window.go=id=>{if(id==='consultations')consultationData=null;goBeforeConsultations(id)};
function consultationLabel(value){return new Date(value).toLocaleDateString('ru-RU',{timeZone:'Europe/Minsk',weekday:'long',day:'numeric',month:'long'})}
function consultations(){
 const mode=state.testMode||'normal';
 if(!consultationData||consultationMode!==mode){queueMicrotask(()=>loadConsultations());return `<div class="brand">Консультации</div><div class="card" id="consultation-loading" role="status">Загружаем расписание…</div>${nav()}`;}
 const data=consultationData;
 const bookings=data.bookings.map(b=>`<section class="card"><h3>${esc(consultationLabel(b.starts_at))} · ${esc(b.starts_at.slice(11,16))}</h3>${b.topic?`<p style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(b.topic)}</p>`:''}<button class="button secondary" onclick="cancelConsultation(${b.id},this)">Отменить запись</button></section>`).join('');
 if(!data.paid_access)return `${accessGate()}${bookings?`<h2>Ваши записи</h2>${bookings}`:''}${nav()}`;
 const dates=[...new Set(data.slots.map(s=>s.starts_at.slice(0,10)))];
 if(!dates.includes(consultationDate))consultationDate=dates[0]||'';
 return `<div class="brand"><span class="mark">✦</span> Консультации</div><section class="hero"><h1>Время для ваших вопросов</h1><p>Вторник и четверг, 30 минут на встречу.<br>Всё время указано по Минску.</p></section>${bookings?`<h2>Ваши записи</h2>${bookings}`:''}<section class="card"><h2>Выберите дату и время</h2>${data.test_mode?'<p class="payment-notice">Тестовый просмотр: настоящая запись отключена.</p>':''}<form onsubmit="bookConsultation(event)"><label style="display:grid;gap:10px">Дата<select style="width:100%;min-width:0;padding:14px;font:inherit" onchange="consultationDate=this.value;document.getElementById('consultation-slots').innerHTML=consultationSlots()">${dates.map(d=>`<option value="${d}" ${d===consultationDate?'selected':''}>${esc(consultationLabel(d+'T12:00:00+03:00'))}</option>`).join('')}</select></label><div id="consultation-slots" style="display:grid;gap:10px;margin:18px 0">${consultationSlots()}</div><label style="display:grid;gap:10px">О чём хотите поговорить? <small>Необязательно</small><textarea name="topic" maxlength="2000" rows="4" style="box-sizing:border-box;width:100%;min-width:0;font:inherit;padding:12px" placeholder="Ваш вопрос или тема консультации"></textarea></label><p class="consultation-status" role="status"></p><button class="button" type="submit" ${data.test_mode?'disabled':''}>Записаться</button></form></section><button class="back" onclick="loadConsultations(true)">Обновить расписание</button>${nav()}`;
}
function consultationSlots(){return consultationData.slots.filter(s=>s.starts_at.startsWith(consultationDate)).map(s=>{const time=s.starts_at.slice(11,16);const end={'19:30':'20:00','20:00':'20:30','20:30':'21:00'}[time];return `<label style="display:flex;align-items:center;gap:10px;padding:12px;border:1px solid var(--line);border-radius:12px;${s.available?'':'opacity:.45'}"><input type="radio" name="starts_at" value="${s.starts_at}" required ${s.available?'':'disabled'}>${time}–${end}${s.available?'':' · занято'}</label>`}).join('')||'<p>Свободных дат пока нет.</p>'}
async function loadConsultations(force=false){
 if(consultationLoading||state.tab!=='consultations')return;
 consultationLoading=true;const mode=state.testMode||'normal';
 try{const data=await api('/consultations');if(mode!==(state.testMode||'normal'))return;consultationData=data;consultationMode=mode;if(state.tab==='consultations')shell(consultations());}
 catch(e){const box=document.getElementById('consultation-loading');if(box){box.textContent='Не удалось загрузить расписание. ';const b=document.createElement('button');b.className='button';b.textContent='Повторить';b.onclick=()=>loadConsultations(true);box.append(b);}else if(force)alert('Не удалось обновить расписание.');}
 finally{consultationLoading=false;}
}
async function bookConsultation(event){
 event.preventDefault();const form=event.currentTarget,button=form.querySelector('button[type=submit]'),status=form.querySelector('.consultation-status');button.disabled=true;
 status.textContent='Сохраняем запись…';
 try{await api('/consultations',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(form)))});status.textContent='Вы записаны!';await loadConsultations(true);}
 catch(e){status.textContent=e.message.includes('<')?'Не удалось записаться. Обновите расписание и попробуйте снова.':e.message;button.disabled=false;}
}
async function cancelConsultation(id,button){
 if(!confirm('Отменить вашу запись на консультацию?'))return;
 button.disabled=true;
 try{await api(`/consultations/${id}/cancel`,{method:'POST'});await loadConsultations(true);}catch(e){button.disabled=false;alert('Не удалось отменить запись. Попробуйте ещё раз.');}
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.tab==='consultations')loadConsultations(true)});
