const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const assert=require('assert');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1200,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://telegram.org/**',r=>r.fulfill({body:'',contentType:'text/javascript'}));
 const base=process.env.TRACK_TEST_URL;
 await page.goto(base+'page?section=tracks&track=1');
 await page.locator('.track-step [data-move="1"]').first().click();
 assert.match(await page.locator('.track-step b').first().textContent(),/Course/);
 await page.locator('.track-step').first().dragTo(page.locator('.track-step').nth(2));
 assert.match(await page.locator('.track-step b').last().textContent(),/Course/);
 await page.locator('input[name=title]').fill('Мой первый маршрут');
 await page.getByRole('button',{name:'Сохранить трек',exact:true}).click();
 try{await page.waitForURL(/saved=1/,{timeout:8000})}catch(e){console.error('Save status:',await page.locator('#track-save-status').textContent(), 'URL:',page.url(), 'JS:',errors);throw e}
 assert.equal(await page.locator('[name=title]').inputValue(),'Мой первый маршрут');
 assert.match(await page.locator('.track-step b').last().textContent(),/Course/);
 await page.screenshot({path:'artifacts/tracks/admin-desktop.png',fullPage:true});
 for(const mode of ['paid','unpaid']){
  await page.goto(base+'mini-app/preview?track=1&mode='+mode);
  await page.locator('.track-step-row').first().waitFor();
  assert.equal(await page.locator('.track-step-row.locked').count(),mode==='paid'?0:2);
  await page.locator('.track-step-row').first().click();await page.locator('.track-return').waitFor();
  await page.locator('.track-return').click();await page.locator('.track-step-row').first().waitFor({state:'visible'});
 }
 await page.goto(base+'mini-app/preview?track=1&mode=paid');await page.locator('.track-step-row').last().click();await page.getByText('Программа курса',{exact:true}).waitFor();
 assert.deepEqual(errors,[]);console.log('PASS: CRM reorder, save and reload; paid/unpaid track previews; material and course preview navigation');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
