const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const fs=require('fs'),assert=require('assert');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:375,height:812}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const free={id:2,title:'Бесплатный курс',is_free:1,locked:false,lessons:[{id:22,title:'Первый урок',position:1,is_required:true}],lesson_count:1,progress:0,required_count:1,completed_count:0,resume_lesson_id:22};
 await page.route('https://club.test/**',async route=>{
  const path=new URL(route.request().url()).pathname;let payload;
  if(path.endsWith('/bootstrap'))payload={user:{state:'new',first_name:'Тест',full_name:'Тест'},settings:{},materials:[],home:[],courses:[free,{id:1,title:'Платный курс',is_free:0,locked:true}],tags:[],categories:[],consultation:{}};
  else if(path.endsWith('/course/2'))payload=free;
  else if(path.endsWith('/course/2/lesson/22'))payload={id:22,title:'Первый урок',course:free,position:1,total_lessons:1,blocks:[{id:3,block_type:'longread',content:'Содержание бесплатного урока'}]};
  if(payload)return route.fulfill({json:payload});
  const file=path==='/mini-app/'?'mini_app/index.html':path.slice(1).replace('mini-app','mini_app');
  return fs.existsSync(file)?route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'}):route.fulfill({status:404,body:''});
 });
 await page.goto('https://club.test/mini-app/');await page.evaluate(()=>go('courses'));
 assert.equal(await page.locator('.course-card.locked button:disabled').count(),1);
 await page.getByRole('button',{name:'Начать курс',exact:true}).click();
 await page.getByRole('button',{name:'Начать курс',exact:true}).click();
 await page.getByText('Содержание бесплатного урока',{exact:true}).waitFor();
 for(const width of [320,375,430]){await page.setViewportSize({width,height:812});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
 assert.deepEqual(errors,[]);console.log('PASS: free course and lesson open without membership; paid course locked; mobile layout');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
