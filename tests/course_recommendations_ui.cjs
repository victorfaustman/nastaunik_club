const fs=require('fs'),assert=require('assert');
const source=fs.readFileSync('mini_app/static/app.js','utf8');
const line=source.split(/\r?\n/).find(l=>l.startsWith('function courseRelatedMaterials('));
const render=new Function('state','materialCard',line+';return courseRelatedMaterials')({data:{user:{state:'active'}}},m=>`<article>${m.title}</article>`);
assert.equal(render({completed:false,related_materials:[{title:'Article'}]}),'');
assert.equal(render({completed:true,related_materials:[]}),'');
assert(render({completed:true,related_materials:[{title:'Article'}]}).includes('<article>Article</article>'));
assert(source.includes('${courseFeedback(c)}${courseRelatedMaterials(c)}'));
console.log('PASS: recommendations after completion, empty and unfinished hidden');
