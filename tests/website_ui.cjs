const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const assert=require('assert'),fs=require('fs');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:950},colorScheme:'light'}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base=process.env.WEBSITE_TEST_URL;fs.mkdirSync('artifacts/website',{recursive:true});
 await page.goto(base);await page.locator('.site-welcome').waitFor();assert.equal(await page.locator('.site-sidebar .site-nav-item').count(),5);
 await page.locator('.site-library-group summary').click();await page.locator('.site-library-submenu a').first().click();assert.equal(await page.evaluate(()=>state.libraryType),'courses');
 await page.locator('.site-library-submenu a').last().click();assert.equal(await page.evaluate(()=>state.libraryType),'materials');
 await page.goBack();await page.waitForFunction(()=>state.libraryType==='courses');
 await page.screenshot({path:'artifacts/website/desktop-home.png',fullPage:true});
 for(const width of [320,375,430,768,1440]){await page.setViewportSize({width,height:900});for(const tab of ['home','library','tracks','profile','consultations']){await page.evaluate(tab=>go(tab),tab);await page.locator('.site-header').waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overflow ${tab}/${width}`)}}
 await page.setViewportSize({width:375,height:812});await page.evaluate(()=>go('home'));await page.screenshot({path:'artifacts/website/mobile-home.png',fullPage:true});
 await page.goto(base+'material/1');await page.getByText('Body 1',{exact:true}).waitFor();
 await page.goto(base+'library');await page.locator('.site-header .button').click();await page.locator('#site-telegram-link:not([hidden])').waitFor();
 const url=new URL(await page.locator('#site-telegram-link').getAttribute('href')),token=url.searchParams.get('start').slice(4);
 const response=await page.request.get(base+'test/code?token='+token);const code=(await response.json()).code;assert(code);
 await page.locator('#site-code').fill(code);await page.locator('#site-code-form button').click();await page.locator('.site-signout').waitFor();assert.equal(await page.evaluate(()=>state.data.user.telegram_id),43);
 await page.goto(base+'material/2');await page.getByText('Body 2',{exact:true}).waitFor();await page.waitForTimeout(1450);assert.equal(await page.evaluate(()=>state.data.materials.find(m=>m.id===2).viewed),true);
 await page.setViewportSize({width:1440,height:950});await page.goto(base+'course/2');await page.getByText('Программа курса',{exact:true}).waitFor();await page.getByRole('button',{name:'Начать курс',exact:true}).click();await page.getByText('Учебный текст',{exact:true}).waitFor();assert.equal(await page.locator('.site-lesson-outline').count(),1);
 await page.screenshot({path:'artifacts/website/desktop-lesson.png',fullPage:true});
 await page.locator('.lesson-next').click();await page.getByText('Курс завершён',{exact:true}).first().waitFor();
 await page.goto(base+'profile');await page.getByRole('button',{name:'Темп и напоминания'}).waitFor();
 await page.locator('.site-signout').click();await page.locator('.site-welcome').waitFor();
 await page.goto(base+'material/2');await page.getByText('Материалы появятся',{exact:false}).count();assert.equal(await page.getByText('Body 2',{exact:true}).count(),0);
 assert.deepEqual(errors,[]);console.log('PASS: public site; responsive pages; direct URLs; one-time bot code + secure browser session; member access; shared reading/course progress; lesson outline; logout');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
