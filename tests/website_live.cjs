// Read-only smoke check against the published website; does not log in or alter content.
const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const assert=require('assert');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:950}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto('https://nastaunik.aiteacher.by/');
 await page.locator('.site-welcome').waitFor();
 assert.equal(await page.locator('.site-sidebar a').count(),5);
 assert.equal(await page.evaluate(()=>state.data.user.guest),true);
 for(const width of [320,375,430,768,1440]){
  await page.setViewportSize({width,height:900});
  for(const tab of ['home','library','tracks','consultations','profile']){
   await page.evaluate(tab=>go(tab),tab);
   await page.locator('.site-header').waitFor();
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overflow ${tab}/${width}`);
  }
 }
 await page.goto('https://nastaunik.aiteacher.by/library?type=courses');
 await page.locator('.site-header').waitFor();
 assert.equal(await page.evaluate(()=>state.data.user.telegram_id),0);
 assert.deepEqual(errors,[]);
 console.log('PASS: production website, guest catalog and 5 responsive widths');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
