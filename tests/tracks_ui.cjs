const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const fs=require('fs'),assert=require('assert');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:375,height:812},colorScheme:'dark'}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 let paid=false,selected=null,viewed=false,prefs={tempo:'regular',days:[1,3],reminders:false,local_time:'19:00',timezone:'Europe/Minsk'},preferenceWrites=0;
 const material={id:1,title:'Первый шаг: знакомство с ИИ',short_description:'Понятный старт без сложных терминов',is_free:1,tags:[{id:1,name:'Для начинающих'}],created_at:'2026-09-19',like_count:3,view_count:10};
 const courses=[{id:1,title:'NotebookLM для учителя',description:'От первых источников до своих учебных материалов',is_free:0,lesson_count:2,progress:0,created_at:'2026-09-18'}, {id:2,title:'Бесплатный вводный курс',description:'Первые шаги',is_free:1,lesson_count:1,progress:0,created_at:'2026-09-17'}];
 function trackData(){const steps=[{id:11,kind:'material',item_id:1,title:material.title,completed:viewed,locked:false},{id:12,kind:'course',item_id:1,title:courses[0].title,completed:false,locked:!paid}];return {tracks:[{id:1,title:'Уверенный старт с ИИ',description:'От знакомства с инструментами до первого готового урока. Понятный маршрут для начинающих.',level:'beginner',steps,step_count:2,completed_count:Number(viewed),progress:viewed?50:0,next_step:steps.find(s=>!s.completed),completed:false}],preferences:{...prefs,active_track_id:selected}}}
 await page.route('https://telegram.org/**',r=>r.fulfill({body:'',contentType:'text/javascript'}));
 await page.route('https://club.test/**',async r=>{const path=new URL(r.request().url()).pathname;let payload;
  if(path.endsWith('/bootstrap'))payload={user:{state:paid?'active':'new',first_name:'Вячеслав',full_name:'Вячеслав'},settings:{},materials:[{...material,viewed}],home:[],courses:courses.map(c=>({...c,locked:!paid&&!c.is_free})),tags:material.tags,categories:[],consultation:{},...trackData()};
  else if(path.endsWith('/tracks'))payload=trackData();
  else if(path.endsWith('/tracks/1/select')){selected=1;payload={ok:true}}
  else if(path.endsWith('/tracks/preferences')){prefs={...prefs,...r.request().postDataJSON()};preferenceWrites++;payload={preferences:prefs}}
  else if(path.endsWith('/activity'))payload={ok:true};
  else if(path.endsWith('/material/1'))payload={...material,full_description:'<p>Содержание первого шага</p>',viewed,files:[],blocks:[],related_materials:[]};
  else if(path.endsWith('/material/1/complete')){viewed=true;payload={ok:true,viewed:true,view_count:11}}
  else if(path.endsWith('/payment'))payload={user:{state:paid?'active':'new',full_name:'Вячеслав',is_lifetime_free:false},contact_url:'https://t.me/test',foreign_request:null,amount_label:'10 BYN',test_mode:true};
  if(payload)return r.fulfill({json:payload});
  const file=path==='/mini-app/'?'mini_app/index.html':path.slice(1).replace('mini-app','mini_app');
  return fs.existsSync(file)?r.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'}):r.fulfill({status:404,body:''});
 });
 fs.mkdirSync('artifacts/tracks',{recursive:true});
 await page.goto('https://club.test/mini-app/');await page.locator('.learning-nav').waitFor();
 assert.equal(await page.locator('.learning-nav button').count(),5);
 assert.match(await page.locator('.learning-nav button').nth(2).textContent(),/Треки/);
 await page.screenshot({path:'artifacts/tracks/home-375-dark.png',fullPage:true});
 for(const width of [320,375,430,768]){
  await page.setViewportSize({width,height:812});
  for(const tab of ['home','library','tracks']){await page.evaluate(tab=>go(tab),tab);await page.locator('.learning-nav').waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${tab} overflow at ${width}`)}
 }
 await page.setViewportSize({width:375,height:812});await page.evaluate(()=>go('library'));
 await page.getByRole('button',{name:'Курсы',exact:true}).click();
 assert.deepEqual(await page.locator('.course-card h3').allTextContents(),courses.map(c=>c.title));
 await page.getByRole('button',{name:'Всё',exact:true}).click();await page.getByRole('searchbox').fill('Notebook');
 await page.waitForTimeout(220);assert.equal(await page.locator('.material-card').count(),0);assert.equal(await page.locator('.course-card').count(),1);
 await page.evaluate(()=>go('tracks'));await page.locator('.track-card').click();
 await page.locator('.track-step-row').nth(1).click();await page.locator('#material-access-dialog').waitFor();await page.getByRole('button',{name:'Пока не сейчас'}).click();
 await page.getByRole('button',{name:'Начать этот трек',exact:true}).click();await page.locator('#track-settings').waitFor();assert.equal(await page.locator('[name=reminders]').isChecked(),false);
 await page.locator('[name=reminders]').check();await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.locator('#track-settings').waitFor({state:'detached'});assert.equal(preferenceWrites,1);
 await page.screenshot({path:'artifacts/tracks/track-375-dark.png',fullPage:true});
 await page.locator('.track-step-row').first().click();await page.getByText('Содержание первого шага',{exact:true}).waitFor();
 await page.waitForTimeout(1450);await page.getByRole('button',{name:'К моему треку'}).click();await page.getByText('1 из 2 шагов · 50%',{exact:true}).waitFor();
 await page.evaluate(()=>go('profile'));await page.getByRole('button',{name:'Темп и напоминания'}).click();await page.getByRole('button',{name:'Отключить напоминания',exact:true}).click();await page.locator('#track-settings').waitFor({state:'detached'});assert.equal(prefs.reminders,false);
 paid=true;await page.reload();await page.locator('.learning-nav').waitFor();await page.evaluate(()=>go('tracks'));await page.locator('.track-card').click();assert.equal(await page.locator('.track-step-row.locked').count(),0);
 await page.emulateMedia({colorScheme:'light'});await page.screenshot({path:'artifacts/tracks/track-375-light.png',fullPage:true});
 assert.deepEqual(errors,[]);console.log('PASS: 5-tab nav; responsive views; library search/order; paid locks; selection; opt-in/off; read progress; return to route');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
