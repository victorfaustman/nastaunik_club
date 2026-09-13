(()=>{
 const style=document.createElement('style');
 style.textContent='.copy-text-block{min-width:0;margin:20px 0;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:var(--paper)}.copy-text-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 14px;border-bottom:1px solid var(--line);font:13px system-ui;color:var(--muted)}.copy-text-bar button{border:1px solid var(--line);border-radius:8px;background:transparent;color:var(--ink);padding:8px 12px;font:600 13px system-ui;cursor:pointer}.copy-text-block pre,.editor pre{font:14px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;word-break:normal;max-width:100%;margin:0;padding:16px;text-align:left}.editor pre{margin:16px 0;border:1px solid var(--line);border-radius:12px;background:var(--soft)}.copy-block-dialog{width:min(620px,90vw);box-sizing:border-box;border:1px solid #ddd;border-radius:18px;padding:22px}.copy-block-dialog textarea{box-sizing:border-box;width:100%;min-height:240px;font:14px/1.6 ui-monospace,Consolas,monospace;white-space:pre-wrap}.copy-block-dialog::backdrop{background:#0006}';
 document.head.append(style);
 document.addEventListener('click',async e=>{
  const button=e.target.closest('[data-copy-text]');if(!button)return;
  const text=button.closest('.copy-text-block')?.querySelector('pre')?.textContent;if(text==null)return;
  try{
   try{await navigator.clipboard.writeText(text)}catch(_){const field=document.createElement('textarea');field.value=text;field.style.cssText='position:fixed;top:0;left:0;opacity:0';document.body.append(field);field.select();const ok=document.execCommand('copy');field.remove();button.focus({preventScroll:true});if(!ok)throw Error();}
   button.textContent='Скопировано ✓';setTimeout(()=>button.textContent='Скопировать',2000);
  }catch(_){button.textContent='Выделите текст и скопируйте';}
 });
 function initEditor(){
  const editor=document.getElementById('content-editor'),toolbar=document.querySelector('.toolbar');if(!editor||!toolbar)return;
  const button=document.createElement('button');button.type='button';button.textContent='＋ Текст для копирования';toolbar.append(button);
  let range=null;
  document.addEventListener('selectionchange',()=>{const selection=getSelection();if(selection.rangeCount&&editor.contains(selection.anchorNode))range=selection.getRangeAt(0).cloneRange()});
  button.addEventListener('mousedown',e=>e.preventDefault());
  button.onclick=()=>{
   const dialog=document.createElement('dialog');dialog.className='copy-block-dialog';
   dialog.innerHTML='<h2>Текст для копирования</h2><p>Вставьте промпт, инструкцию или код. Переносы строк сохранятся.</p><textarea aria-label="Текст для копирования" placeholder="Вставьте текст сюда"></textarea><p><button type="button" data-insert>Добавить в статью</button> <button type="button" data-cancel>Отмена</button></p>';
   document.body.append(dialog);dialog.showModal();dialog.querySelector('textarea').focus();
   dialog.onclose=()=>dialog.remove();dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();
   dialog.querySelector('[data-insert]').onclick=()=>{
    const text=dialog.querySelector('textarea').value;if(!text.trim())return;
    const pre=document.createElement('pre'),code=document.createElement('code');code.textContent=text;pre.append(code);
    dialog.close();editor.focus();const selection=getSelection();selection.removeAllRanges();
    if(!range||!editor.contains(range.commonAncestorContainer)){range=document.createRange();range.selectNodeContents(editor);range.collapse(false)}
    range.deleteContents();range.insertNode(pre);
    const after=document.createElement('p');after.innerHTML='<br>';pre.after(after);
    const caret=document.createRange();caret.selectNodeContents(after);caret.collapse(true);selection.addRange(caret);
    editor.dispatchEvent(new Event('input',{bubbles:true}));
   };
  };
  editor.addEventListener('paste',e=>{const anchor=getSelection()?.anchorNode;const element=anchor?.nodeType===1?anchor:anchor?.parentElement;if(element?.closest('pre')){e.preventDefault();document.execCommand('insertText',false,e.clipboardData.getData('text/plain'));}},true);
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initEditor);else initEditor();
})();
