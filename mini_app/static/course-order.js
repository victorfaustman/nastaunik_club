(()=>{
 const list=document.getElementById('course-order-list');if(!list)return;
 const status=document.getElementById('course-order-status');let dragged=null,busy=false,original=[];
 const cards=()=>[...list.querySelectorAll('[data-course-id]')];
 list.querySelectorAll('[data-course-drag]').forEach(handle=>handle.addEventListener('dragstart',e=>{
  if(busy){e.preventDefault();return}dragged=handle.closest('[data-course-id]');original=cards();e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',dragged.dataset.courseId);
 }));
 list.addEventListener('dragend',()=>dragged=null);
 list.addEventListener('dragover',e=>{if(dragged&&!busy){e.preventDefault();e.dataTransfer.dropEffect='move'}});
 list.addEventListener('drop',async e=>{
  if(!dragged||busy)return;e.preventDefault();const target=e.target.closest('[data-course-id]');if(!target||target===dragged)return;
  const bounds=target.getBoundingClientRect();target[e.clientY<bounds.top+bounds.height/2?'before':'after'](dragged);
  const data=new FormData();data.set('action','course_reorder');data.set('order',JSON.stringify(cards().map(c=>Number(c.dataset.courseId))));data.set('original_order',JSON.stringify(original.map(c=>Number(c.dataset.courseId))));
  busy=true;list.inert=true;status.textContent='Сохраняем порядок…';
  try{const response=await fetch(list.dataset.action,{method:'POST',body:data});if(!response.ok)throw Error(response.status===409?'Список изменился. Обновите страницу.':'Не удалось сохранить. Попробуйте ещё раз.');location.reload();}
  catch(error){original.forEach(card=>list.append(card));status.textContent=error.message;list.inert=false;busy=false;}
 });
})();
