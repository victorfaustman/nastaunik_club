// Real learner completion is validated by the server, not page-local answer memory.
(()=>{
 function syncQuestionNavigation(){
  const next=document.querySelector('.lesson-navigation .lesson-next');
  const lesson=state.currentLesson;
  if(!next||!lesson||lesson.completed)return;
  const pending=(lesson.blocks||[]).some(block=>{
   if(block.block_type!=='test'||block.settings?.required===false)return false;
   const box=document.getElementById(`lesson-test-${block.id}`);
   return box?.dataset.answerPending==='1'||Boolean(box?.querySelector('.lesson-test-result.wrong'));
  });
  next.textContent=lesson.next_lesson_id?(lesson.next_button_label||'Завершить урок и продолжить'):(lesson.finish_button_label||'Завершить курс');
  next.disabled=pending;
  const footer=next.closest('.lesson-navigation');
  footer.querySelector('.lesson-question-hint')?.remove();
  if(pending){
   const hint=document.createElement('p');hint.className='lesson-question-hint';hint.setAttribute('role','status');
   hint.textContent='Повторите ответ кнопкой «Попробовать ещё раз» внутри вопроса. После верного ответа можно продолжить.';
   footer.append(hint);
  }
 }
 const answer=window.answerCourseTest;
 if(answer)window.answerCourseTest=async(...args)=>{
  await answer(...args);
  const box=document.getElementById(`lesson-test-${args[2]}`);
  if(box){
   box.dataset.answerPending=box.querySelector('.lesson-test-result.correct')?'0':'1';
   if(box.querySelector('.lesson-test-result.correct'))document.querySelector('.lesson-save-error')?.remove();
  }
  syncQuestionNavigation();
 };
 const retry=window.retryCourseTest;
 if(retry)window.retryCourseTest=button=>{
  const box=button.closest('.lesson-test-block');retry(button);
  if(box)box.dataset.answerPending='1';
  syncQuestionNavigation();
  const hint=document.querySelector('.lesson-question-hint');
  if(hint)hint.textContent='Выберите ответ в вопросе ещё раз. После верного ответа можно продолжить.';
  box?.querySelector('.lesson-test-options button')?.focus();
 };
 function errorText(error){
  const raw=String(error?.message||'Не удалось сохранить прохождение. Проверьте соединение и повторите действие.');
  try{const data=JSON.parse(raw);return data.reason||data.message||raw}catch(_){return raw}
 }
 window.completeCourseLesson=async(courseId,lessonId,button)=>{
  if(button.disabled)return;
  const label=button.textContent;
  const lesson=state.currentLesson;
  if(!lesson||Number(lesson.id)!==Number(lessonId))return;
  const footer=button.closest('.lesson-navigation');
  footer?.querySelector('.lesson-save-error')?.remove();
  button.disabled=true;button.textContent='Сохраняем…';
  try{
   // Preview/test mode has no persisted attempts; keep its local mandatory gate.
   if(state.testMode){
    if(lesson.blocks?.some(block=>block.block_type==='test'&&block.settings?.required!==false&&!state.testPassed.has(`${courseId}:${lessonId}:${block.id}`)))throw Error('Сначала ответьте правильно на все обязательные вопросы этого урока.');
    state.testCourseCompleted.add(testCourseKey(courseId,lessonId));
    const next=lesson.next_lesson_id||null;
    state.testCourseLast.set(courseId,next||lessonId);
    const c=applyTestCourseState(state.currentCourse);updateCachedCourse(c);
    if(next)await openCourseLesson(courseId,next);
    else if(c?.completed)await showCourseComplete(courseId);
    else await openCourse(courseId);
    return;
   }
   // The backend checks saved correct attempts for every required question.
   // A page reload must not erase the learner's eligibility to finish the lesson.
   const result=await api(`/course/${courseId}/lesson/${lessonId}/complete`,{method:'POST'});
   if(!result?.ok||result.blocked)throw Error(result?.reason||'Не удалось сохранить прохождение урока.');
   updateCachedCourse({id:courseId,progress:result.progress,completed:result.completed,started:true,resume_lesson_id:result.next_lesson_id||lessonId});
   if(result.next_lesson_id)await openCourseLesson(courseId,result.next_lesson_id);
   else if(result.completed)await showCourseComplete(courseId);
   else await openCourse(courseId);
  }catch(error){
   button.disabled=false;button.textContent=label;
   if(button.isConnected&&footer){
    const status=document.createElement('p');
    status.className='lesson-save-error';status.setAttribute('role','alert');
    status.style.cssText='flex-basis:100%;grid-column:1 / -1;margin:8px 0 0;overflow-wrap:anywhere';
    status.textContent=errorText(error);footer.append(status);
   }
  }
 };
})();
