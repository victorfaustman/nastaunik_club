const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const assert=require('assert');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});try{
 const page=await browser.newPage();let requestBody='';
 await page.route('https://club.test/action',async route=>{requestBody=route.request().postData();await route.fulfill({status:409,body:'Changed'});});
 await page.route('https://club.test/',route=>route.fulfill({contentType:'text/html',body:'<p id="course-order-status"></p><div id="course-order-list" data-action="/action"><article data-course-id="1" style="padding:40px"><span draggable="true" data-course-drag>Drag one</span></article><article data-course-id="2" style="padding:40px"><span draggable="true" data-course-drag>Drag two</span></article></div>'}));
 await page.goto('https://club.test/');await page.addScriptTag({path:'mini_app/static/course-order.js'});
 await page.locator('[data-course-id="1"] [data-course-drag]').dragTo(page.locator('[data-course-id="2"]'));
 await page.getByText('Список изменился. Обновите страницу.',{exact:true}).waitFor();
 assert(requestBody.includes('[2,1]'));assert(requestBody.includes('[1,2]'));
 assert.deepEqual(await page.locator('[data-course-id]').evaluateAll(nodes=>nodes.map(n=>n.dataset.courseId)),['1','2']);
 assert.equal(await page.locator('#course-order-list').evaluate(n=>n.inert),false);
 console.log('PASS: drag sends ordered IDs; stale-order failure restores original cards and enables controls');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
