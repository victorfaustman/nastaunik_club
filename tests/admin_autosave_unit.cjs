const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const timers=new Map(),storage=new Map(),requests=[];let sequence=0,ready;
const fields=[{name:'title',type:'text',value:'Initial'},{name:'action',type:'hidden',value:'course_lesson_save'}];
fields.action=fields[1];
const status={textContent:'',setAttribute(){},classList:{toggle(){}}};
const listeners={};
const form={elements:fields,dataset:{autosaveId:'1'},id:'lesson-form',
 querySelector:selector=>selector==='[data-save-state]'?status:null,
 getAttribute:name=>name==='action'?'/save':null,addEventListener:(type,fn)=>listeners[type]=fn};
class Body{constructor(form){this.data=new Map(form.elements.map(f=>[f.name,f.value]));}keys(){return this.data.keys();}set(k,v){this.data.set(k,v)}delete(k){this.data.delete(k)}}
const context={window:{},location:{pathname:'/admin/',href:'http://test/admin/',search:''},URLSearchParams,Date,JSON,
 document:{addEventListener:(_,fn)=>ready=fn,querySelectorAll:()=>[form]},FormData:Body,
 localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
 setTimeout:fn=>{const id=++sequence;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),
 fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))};
vm.runInNewContext(fs.readFileSync('mini_app/static/admin_autosave.js','utf8'),context);ready();
const fire=()=>{const [id,fn]=[...timers].at(-1);timers.delete(id);return fn()};
(async()=>{
 fields[0].value='First';context.window.scheduleAdminAutosave(form);const first=fire();
 assert.equal(requests[0].url,'/save');
 fields[0].value='Newer';context.window.scheduleAdminAutosave(form);
 requests[0].resolve({ok:true});await first;
 assert.equal(JSON.parse([...storage.values()][0]).values.title,'Newer','old response must not erase newer draft');
 const second=fire();requests[1].resolve({ok:true});await second;assert.equal(storage.size,0);
 fields[0].value='Offline';context.window.scheduleAdminAutosave(form);const third=fire();requests[2].reject(Error('offline'));await third;
 assert.equal(JSON.parse([...storage.values()][0]).values.title,'Offline');assert.match(status.textContent,/Не удалось сохранить/);
 listeners.submit();assert.equal(storage.size,1,'manual submission must keep draft until confirmed success');
 console.log('PASS: named action input; autosave race; failed network; manual-submit draft retention');
})().catch(e=>{console.error(e);process.exitCode=1});
