(() => {
  const config=JSON.parse(document.getElementById('track-config').textContent);
  const steps=config.selected, list=document.getElementById('track-steps'), form=document.getElementById('track-form');
  const picker=document.getElementById('track-picker'); let dragging=null, dirty=false;
  const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const key=s=>`${s.kind}:${s.id}`;
  const status=document.getElementById('track-save-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const draftKey=`nastaunik:track-draft:${form.elements.track_id.value||'new'}`;
  const fields=()=>[...form.elements].filter(f=>f.name&&!['file','submit','button'].includes(f.type));
  function markDirty(){
    dirty=true;document.getElementById('track-steps-value').value=JSON.stringify(steps);
    const values={};fields().forEach(f=>values[f.name]=f.type==='checkbox'?f.checked:f.value);
    try{localStorage.setItem(draftKey,JSON.stringify(values));}catch(_){}
    status.textContent='Есть несохранённые изменения. Черновик сохранён в этом браузере; нажмите «Сохранить трек». Файлы нужно выбрать заново после обновления.';
  }
  try{
    const saved=JSON.parse(localStorage.getItem(draftKey)||'null');
    if(new URLSearchParams(location.search).get('saved')==='1')localStorage.removeItem(draftKey);
    else if(saved&&saved.version===form.elements.version.value){
      fields().forEach(f=>{if(f.name in saved){if(f.type==='checkbox')f.checked=saved[f.name];else f.value=saved[f.name];}});
      const restored=JSON.parse(saved.steps||'[]');steps.splice(0,steps.length,...restored);dirty=true;
      status.textContent='Восстановлен несохранённый черновик. Нажмите «Сохранить трек».';
    }else if(saved){status.textContent='Серверная версия трека изменилась. Старый черновик не применён.';}
  }catch(_){}
  function render(){
    document.getElementById('track-steps-value').value=JSON.stringify(steps);
    list.innerHTML=steps.length?steps.map((s,i)=>{const item=config.items.find(x=>key(x)===key(s));return `<div class="track-step" draggable="true" data-index="${i}"><span aria-hidden="true">⠿ ${i+1}</span><b>${escape(item?.title||'Шаг скрыт или удалён')}<small class="hint"> · ${s.kind==='course'?'Курс':'Материал'}</small></b><button type="button" class="secondary" data-move="-1" aria-label="Выше" ${i===0?'disabled':''}>↑</button><button type="button" class="secondary" data-move="1" aria-label="Ниже" ${i===steps.length-1?'disabled':''}>↓</button><button type="button" class="danger" data-remove aria-label="Убрать шаг">×</button></div>`}).join(''):'<p class="empty">Добавьте первый шаг маршрута.</p>';
  }
  function options(){const query=document.getElementById('track-search').value.toLowerCase();const items=config.items.filter(s=>!steps.some(x=>key(x)===key(s))&&s.title.toLowerCase().includes(query));document.getElementById('track-options').innerHTML=items.map(s=>`<button type="button" class="track-option" data-kind="${s.kind}" data-id="${s.id}">${s.kind==='course'?'Курс':'Материал'} · ${escape(s.title)}</button>`).join('')||'<p>Больше ничего не найдено.</p>'}
  document.getElementById('track-add').onclick=()=>{options();picker.showModal()};
  document.getElementById('track-close').onclick=()=>picker.close();
  document.getElementById('track-search').oninput=options;
  document.getElementById('track-options').onclick=e=>{const b=e.target.closest('[data-id]');if(!b)return;steps.push({kind:b.dataset.kind,id:Number(b.dataset.id)});markDirty();render();options()};
  list.onclick=e=>{const b=e.target.closest('button'),row=b?.closest('[data-index]');if(!row)return;const i=Number(row.dataset.index);if(b.hasAttribute('data-remove'))steps.splice(i,1);else{const j=i+Number(b.dataset.move);if(j<0||j>=steps.length)return;[steps[i],steps[j]]=[steps[j],steps[i]]}markDirty();render()};
  list.ondragstart=e=>{dragging=Number(e.target.closest('[data-index]')?.dataset.index);e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',String(dragging))};
  list.ondragover=e=>e.preventDefault();list.ondrop=e=>{e.preventDefault();const row=e.target.closest('[data-index]');if(!row||dragging===null)return;const to=Number(row.dataset.index);steps.splice(to,0,steps.splice(dragging,1)[0]);dragging=null;markDirty();render()};list.ondragend=()=>dragging=null;
  form.addEventListener('input',markDirty);
  form.addEventListener('change',markDirty);
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});
  form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('[type=submit]'),status=document.getElementById('track-save-status');button.disabled=true;status.textContent='Сохраняем…';
    form.inert=true;const xhr=new XMLHttpRequest();xhr.open('POST',form.getAttribute('action'));xhr.upload.onprogress=e=>{if(e.lengthComputable)status.textContent=`Загружаем: ${Math.round(e.loaded/e.total*100)}%`};xhr.onload=()=>{form.inert=false;if(xhr.status>=200&&xhr.status<300){dirty=false;location.href=xhr.responseURL}else{status.textContent=xhr.responseText||'Не удалось сохранить';button.disabled=false}};xhr.onerror=()=>{form.inert=false;status.textContent='Нет связи. Изменения остались в редакторе — повторите сохранение.';button.disabled=false};xhr.send(new FormData(form));};render();
})();
