// Re-encode generated originals for fast delivery; no creative image edits.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const sharp=require(process.env.SHARP_PATH||'sharp');
(async()=>{
 const spec=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
 const out=path.resolve('assets/track-covers');fs.mkdirSync(out,{recursive:true});
 for(const track of spec.tracks){
  const target=path.join(out,track.file);
  if(fs.existsSync(target))throw Error('Refusing to overwrite '+target);
  await sharp(track.source).resize({width:1280,withoutEnlargement:true}).webp({quality:85,effort:6}).toFile(target);
  track.sha256=crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex');
  console.log(track.id,track.file,fs.statSync(target).size);
 }
 fs.writeFileSync(path.join(out,'manifest.json'),JSON.stringify({generator:'built-in image_gen',tracks:spec.tracks.map(({source,...track})=>track)},null,2)+'\n');
})().catch(e=>{console.error(e);process.exit(1)});
