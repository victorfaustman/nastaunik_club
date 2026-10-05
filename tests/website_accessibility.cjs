// Read-only accessibility audit. AXE_PATH points to a locally downloaded axe-core build.
const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try {
 const page=await browser.newPage();
 if(process.env.LOCAL_ASSETS) await page.route('**/site/static/site.*',route=>route.fulfill({path:require('path').resolve('website',new URL(route.request().url()).pathname.split('/').pop())}));
  let violations=0;
  for(const colorScheme of ['light','dark']) for(const width of [375,1440]) {
   await page.emulateMedia({colorScheme});
   await page.setViewportSize({width,height:900});
   for(const path of ['/','/library?type=materials','/library?type=courses','/tracks','/consultations','/profile','/material/30']) {
    await page.goto((process.env.SITE_URL||'https://nastaunik.aiteacher.by')+path);
    await page.locator('.site-header').waitFor();
    await page.waitForTimeout(1000); // Allow asynchronous detail navigation to finish.
    await page.addScriptTag({path:process.env.AXE_PATH});
    const result=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}}));
    violations+=result.violations.length;
    console.log(JSON.stringify({colorScheme,width,path,violations:result.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))}));
   }
  }
  if(violations) process.exitCode=1;
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
