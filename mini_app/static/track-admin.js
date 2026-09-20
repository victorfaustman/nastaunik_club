(() => {
  const config=JSON.parse(document.getElementById('track-config').textContent);
  const steps=config.selected, list=document.getElementById('track-steps'), form=document.getElementById('track-form');
  const picker=document.getElementById('track-picker'); let dragging=null, dirty=false;
  const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const key=s=>`${s.kind}:${s.id}`;
  function render(){
    document.getElementById('track-steps-value').value=JSON.stringify(steps);
    list.innerHTML=steps.length?steps.map((s,i)=>{const item=config.items.find(x=>key(x)===key(s));return `<div class="track-step" draggable="true" data-index="${i}"><span aria-hidden="true">⠿ ${i+1}</span><b>${escape(item?.title||'Шаг скрыт или удалён')}<small class="hint"> · ${s.kind==='course'?'Курс':'Материал'}</small></b><button type="button" class="secondary" data-move="-1" aria-label="Выше" ${i===0?'disabled':''}>↑</button><button type="button" class="secondary" data-move="1" aria-label="Ниже" ${i===steps.length-1?'disabled':''}>↓</button><button type="button" class="danger" data-remove aria-label="Убрать шаг">×</button></div>`}).join(''):'<p class="empty">Добавьте первый шаг маршрута.</p>';
  }
  function options(){const query=document.getElementById('track-search').value.toLowerCase();const items=config.items.filter(s=>!steps.some(x=>key(x)===key(s))&&s.title.toLowerCase().includes(query));document.getElementById('track-options').innerHTML=items.map(s=>`<button type="button" class="track-option" data-kind="${s.kind}" data-id="${s.id}">${s.kind==='course'?'Курс':'Материал'} · ${escape(s.title)}</button>`).join('')||'<p>Больше ничего не найдено.</p>'}
  document.getElementById('track-add').onclick=()=>{options();picker.showModal()};
  document.getElementById('track-close').onclick=()=>picker.close();
  document.getElementById('track-search').oninput=options;
  document.getElementById('track-options').onclick=e=>{const b=e.target.closest('[data-id]');if(!b)return;steps.push({kind:b.dataset.kind,id:Number(b.dataset.id)});dirty=true;render();options()};
  list.onclick=e=>{const b=e.target.closest('button'),row=b?.closest('[data-index]');if(!row)return;const i=Number(row.dataset.index);if(b.hasAttribute('data-remove'))steps.splice(i,1);else{const j=i+Number(b.dataset.move);if(j<0||j>=steps.length)return;[steps[i],steps[j]]=[steps[j],steps[i]]}dirty=true;render()};
  list.ondragstart=e=>{dragging=Number(e.target.closest('[data-index]')?.dataset.index);e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',String(dragging))};
  list.ondragover=e=>e.preventDefault();list.ondrop=e=>{e.preventDefault();const row=e.target.closest('[data-index]');if(!row||dragging===null)return;const to=Number(row.dataset.index);steps.splice(to,0,steps.splice(dragging,1)[0]);dragging=null;dirty=true;render()};list.ondragend=()=>dragging=null;
  form.addEventListener('input',()=>dirty=true);
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});
  form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('[type=submit]'),status=document.getElementById('track-save-status');button.disabled=true;status.textContent='Сохраняем…';
    const xhr=new XMLHttpRequest();xhr.open('POST',form.getAttribute('action'));xhr.upload.onprogress=e=>{if(e.lengthComputable)status.textContent=`Загружаем: ${Math.round(e.loaded/e.total*100)}%`};xhr.onload=()=>{if(xhr.status>=200&&xhr.status<300){dirty=false;location.href=xhr.responseURL}else{status.textContent=xhr.responseText||'Не удалось сохранить';button.disabled=false}};xhr.onerror=()=>{status.textContent='Нет связи. Изменения остались в редакторе — повторите сохранение.';button.disabled=false};xhr.send(new FormData(form));};render();
})();
