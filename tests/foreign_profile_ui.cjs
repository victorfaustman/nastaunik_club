const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const fs=require('fs'),assert=require('assert');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:375,height:812}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 let user={telegram_id:43,state:'new',full_name:'Участник',first_name:'Участник',is_lifetime_free:false},foreign=null,submissions=0;
 await page.route('https://club.test/**',async route=>{
  const path=new URL(route.request().url()).pathname;let payload;
  if(path.endsWith('/bootstrap'))payload={user,settings:{},home:[],materials:[],courses:[],categories:[],tags:[],consultation:{}};
  else if(path.endsWith('/foreign-request')){submissions++;foreign={status:'pending',access_granted:false};payload={ok:true};}
  else if(path.endsWith('/payment'))payload={user,foreign_request:foreign,amount_label:'10 BYN / месяц',card:'5208130008671731',phone:'+375 25 91 29 014',contact_url:'https://t.me/example',latest_payment:null,test_mode:false};
  if(payload)return route.fulfill({json:payload});
  const file=path==='/mini-app/'?'mini_app/index.html':path.slice(1).replace('mini-app','mini_app');
  return fs.existsSync(file)?route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'}):route.fulfill({status:404,body:''});
 });
 await page.goto('https://club.test/mini-app/');await page.evaluate(()=>openMembership());
 await page.getByRole('button',{name:'Я не из Беларуси',exact:true}).click();
 await page.getByText('Заявка «Я не из Беларуси» на рассмотрении',{exact:true}).waitFor();
 assert.equal(submissions,1);assert.equal(await page.getByRole('button',{name:'Я не из Беларуси',exact:true}).count(),0);
 foreign={status:'approved',access_granted:true};user={...user,state:'active',access_end_at:null};
 await page.evaluate(()=>refreshPayment(true));
 await page.getByRole('heading',{name:'Доступ предоставлен',exact:true}).waitFor();
 assert.equal(await page.locator('.payment-details').count(),0);assert.equal(await page.locator('.membership-price').count(),0);
 assert((await page.locator('body').textContent()).includes('Автоматических списаний не будет'));
 for(const width of [320,375,430]){await page.setViewportSize({width,height:812});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
 foreign={status:'rejected',access_granted:false};user={...user,state:'new'};
 await page.evaluate(()=>refreshPayment(true));await page.getByText('Заявка рассмотрена',{exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'Я не из Беларуси',exact:true}).count(),0);
 assert.deepEqual(errors,[]);console.log('PASS: request, pending, automatic approval, payment hidden for grant, rejection, mobile layout');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
