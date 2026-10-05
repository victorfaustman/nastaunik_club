// Read-only verification of the four installed covers and responsive rendering.
const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const assert=require('assert'),fs=require('fs');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{
  const page=await browser.newPage();
  const response=await page.request.get('https://nastaunik.aiteacher.by/mini-app/api/bootstrap',{headers:{'X-Nastaunik-Site':'1'}});
  const data=await response.json();
  for(const id of [1,2,3,4]){
   const track=data.tracks.find(t=>t.id===id);assert(track?.cover_url.includes('20261005.webp'));
   assert.equal((await page.request.get(new URL(track.cover_url,'https://nastaunik.aiteacher.by').href)).status(),200);
  }
  fs.mkdirSync('artifacts/tracks',{recursive:true});
  for(const width of [375,1440]){
   await page.setViewportSize({width,height:1000});
   await page.goto('https://nastaunik.aiteacher.by/tracks');
   await page.locator('.track-card img').first().waitFor();
   await page.waitForFunction(()=>[...document.querySelectorAll('.track-card img')].length===4&&[...document.querySelectorAll('.track-card img')].every(i=>i.complete&&i.naturalWidth>0));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:`artifacts/tracks/covers-${width}.png`,fullPage:true});
  }
  await page.goto('https://nastaunik.aiteacher.by/track/1');
  await page.locator('.track-detail-cover').waitFor();
  await page.waitForFunction(()=>document.querySelector('.track-detail-cover')?.naturalWidth>0);
  console.log('PASS: four signed covers, mobile/desktop cards and track detail');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
