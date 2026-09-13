const {chromium}=require(process.env.PLAYWRIGHT_PATH || 'playwright');
const fs=require('fs');
const assert=require('assert');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try {
 const page=await browser.newPage({viewport:{width:375,height:812}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let user={telegram_id:43,full_name:'Тестовый участник',first_name:'Участник',state:'guest',is_lifetime_free:false};
 let latest=null;
 const data=()=>({user,settings:{},home:[],materials:[],categories:[],tags:[],courses:[],consultation:{}});
 await page.route('https://club.test/**',async route=>{
  const url=new URL(route.request().url());
  let payload;
  if(url.pathname.endsWith('/bootstrap'))payload=data();
  else if(url.pathname.endsWith('/payment/receipt')){latest={status:'pending',id:1};payload={payment_id:1};}
  else if(url.pathname.endsWith('/payment'))payload={user,amount_label:'7 BYN / месяц',card:'5208130008671731',phone:'+375 25 91 29 014',contact_url:'https://t.me/example',latest_payment:latest,test_mode:false};
  if(payload)return route.fulfill({json:payload});
  const file=url.pathname==='/mini-app/'?'mini_app/index.html':url.pathname.slice(1).replace('mini-app','mini_app');
  if(fs.existsSync(file))return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});
  return route.fulfill({status:404,body:''});
 });
 await page.goto('https://club.test/mini-app/');
 await page.locator('.free-access-banner').click();
 await page.locator('.payment-details[open]').waitFor();
 assert((await page.locator('.membership-price').textContent()).includes('7 BYN'));
 for(const width of [320,375,430]){
  await page.setViewportSize({width,height:812});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Overflow at ${width}`);
 }
 await page.locator('input[name=receipt]').setInputFiles({name:'receipt.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-1.4 test')});
 await page.locator('#receipt-form button[type=submit]').click();
 await page.getByText('Чек отправлен на проверку',{exact:true}).waitFor();
 assert.equal(await page.locator('#receipt-form').count(),0);
 user={...user,state:'active'};latest={status:'approved',confirmed_at:'2026-09-13T10:00:00Z'};
 await page.evaluate(()=>refreshPayment(true));
 await page.getByText('Вы участник клуба',{exact:true}).waitFor();
 await page.evaluate(()=>go('home'));
 assert.equal(await page.locator('.free-access-banner').count(),0);
 assert.deepEqual(errors,[]);
 console.log('PASS: banner, expanded payment, personal tariff, 320/375/430 layout, receipt, approval, banner hidden for member');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
