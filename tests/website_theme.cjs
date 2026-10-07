const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:950},colorScheme:'dark'});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const base=process.env.WEBSITE_TEST_URL;fs.mkdirSync('artifacts/website',{recursive:true});
  await page.goto(base);await page.locator('.site-welcome').waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.siteTheme),'light','web defaults to light even with dark OS preference');
  assert.equal(await page.evaluate(()=>getComputedStyle(document.body).backgroundColor),'rgb(247, 245, 240)');
  await page.screenshot({path:'artifacts/website/theme-home-light.png',fullPage:true});
  await page.getByRole('button',{name:'Включить тёмную тему',exact:true}).click();
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.siteTheme),'dark');
  assert.equal(await page.evaluate(()=>getComputedStyle(document.body).backgroundColor),'rgb(34, 32, 30)');
  await page.reload();await page.locator('.site-welcome').waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.siteTheme),'dark');
  await page.screenshot({path:'artifacts/website/theme-home-dark.png',fullPage:true});
  await page.goto(base+'library?type=courses');await page.locator('.site-header').waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.siteTheme),'dark');
  await page.getByRole('button',{name:'Включить светлую тему',exact:true}).press('Enter');
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.siteTheme),'light');
  for(const theme of ['light','dark']){
   if(await page.evaluate(()=>document.documentElement.dataset.siteTheme)!==theme)await page.locator('.site-theme-toggle').click();
   for(const width of [320,375,430,768,1440]){
    await page.setViewportSize({width,height:900});
    for(const tab of ['home','library','tracks','profile','consultations']){
     await page.evaluate(tab=>go(tab),tab);await page.locator('.site-header').waitFor();
     assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overflow ${theme}/${tab}/${width}`);
     const button=page.locator('.site-theme-toggle');assert(await button.isVisible());
     await page.waitForFunction(()=>{const box=document.querySelector('.site-theme-toggle')?.getBoundingClientRect();return box?.width>=44&&box?.height>=44});
    }
   }
  }
  await page.getByRole('button',{name:'Включить светлую тему',exact:true}).click();
  await page.setViewportSize({width:375,height:812});await page.evaluate(()=>go('home'));
  await page.screenshot({path:'artifacts/website/theme-mobile-light.png',fullPage:true});
  assert.deepEqual(errors,[]);console.log('PASS: light default with dark OS; explicit dark theme; persisted choice; keyboard; 50 responsive views; no JS errors');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
