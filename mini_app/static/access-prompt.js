function materialAccessKey(event){if(event.key==='Enter'||event.key===' '){event.preventDefault();showMaterialAccessPrompt()}}
function showMaterialAccessPrompt(){
 if(document.getElementById('material-access-dialog'))return;
 const dialog=document.createElement('dialog');dialog.id='material-access-dialog';dialog.className='material-access-dialog';
 dialog.setAttribute('aria-labelledby','material-access-title');
 dialog.innerHTML='<span class="mark" aria-hidden="true">✦</span><h2 id="material-access-title">Материал для участников клуба</h2><p>Вы в бесплатном режиме. Чтобы открыть этот материал, вступите в клуб и оплатите участие.</p><button class="button" data-pay>Перейти к оплате</button><button class="button secondary" data-close>Пока не сейчас</button>';
 const previous=document.activeElement;
 document.body.append(dialog);dialog.showModal();
 dialog.querySelector('[data-pay]').onclick=()=>{dialog.close();openMembership()};
 dialog.querySelector('[data-close]').onclick=()=>dialog.close();
 dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close()}});
 dialog.onclose=()=>{dialog.remove();if(previous?.isConnected)previous.focus({preventScroll:true})};
}
