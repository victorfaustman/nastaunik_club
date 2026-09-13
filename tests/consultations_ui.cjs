const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const fs=require('fs'),assert=require('assert');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{
 const page=await browser.newPage({viewport:{width:375,height:812}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 let booked=false,paid=true;
 const starts='2026-10-06T19:30:00+03:00';
 await page.route('https://club.test/**',async route=>{
  const url=new URL(route.request().url());let payload;
  if(url.pathname.endsWith('/bootstrap'))payload={user:{state:'active',full_name:'Тест',first_name:'Тест'},settings:{},home:[],materials:[],courses:[],tags:[],categories:[],consultation:{}};
  else if(url.pathname.endsWith('/cancel')){booked=false;payload={ok:true};}
  else if(url.pathname.endsWith('/consultations')){
   if(route.request().method()==='POST'){booked=true;payload={id:1};}
   else payload={paid_access:paid,test_mode:false,slots:paid?[{starts_at:starts,available:!booked}]:[],bookings:booked?[{id:1,starts_at:starts,topic:'Вопрос'}]:[]};
  }
  if(payload)return route.fulfill({json:payload});
  const file=url.pathname==='/mini-app/'?'mini_app/index.html':url.pathname.slice(1).replace('mini-app','mini_app');
  return fs.existsSync(file)?route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'}):route.fulfill({status:404,body:''});
 });
 await page.goto('https://club.test/mini-app/');
 await page.evaluate(()=>go('consultations'));
 await page.locator('input[type=radio]').check();
 await page.locator('textarea').fill('Вопрос');
 for(const width of [320,375,430]){await page.setViewportSize({width,height:812});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Overflow at ${width}`);}
 await page.getByRole('button',{name:'Записаться',exact:true}).click();
 await page.getByRole('button',{name:'Отменить запись',exact:true}).waitFor();
 await page.getByRole('button',{name:'Отменить запись',exact:true}).click();
 await page.waitForFunction(()=>!document.body.textContent.includes('Ваши записи'));
 paid=false;await page.evaluate(()=>go('consultations'));
 await page.getByRole('button',{name:'Вступить в клуб',exact:true}).waitFor();
 assert.equal(await page.locator('textarea').count(),0);assert.deepEqual(errors,[]);
 console.log('PASS: booking, optional topic, cancellation, free access gate, 320/375/430px');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
