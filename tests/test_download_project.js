const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'assets', 'index.js'), 'utf8');
const start = source.indexOf('function downloadSessionKey(){');
const end = source.indexOf('\nasync function poll(){', start);
assert(start >= 0 && end > start);

function fixture(job) {
  const values = new Map([['geocnpj_download_projectA', 'job-old']]);
  const urls = [], elements = {job:{innerHTML:''}, competence:{value:'2026-11'}};
  const context = {
    projectId:'projectA', jobId:null, downloadStartedHere:false, api:'/api',
    sessionStorage:{getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)},
    $:id=>elements[id], json:async url=>{urls.push(url);return job}, poll:async()=>{context.polled=true}
  };
  vm.createContext(context);
  vm.runInContext(source.slice(start,end),context);
  return {context,values,urls,elements};
}

(async()=>{
  const none=fixture({status:'completed',competence:'2026-11'});
  none.values.clear();
  await none.context.restoreLatestDownload();
  assert.deepEqual(none.urls, []);
  assert.match(none.elements.job.innerHTML,/Nenhum download em andamento/);

  const old=fixture({status:'completed',competence:'2026-11'});
  await old.context.restoreLatestDownload();
  assert.deepEqual(old.urls,['/api/downloads/job-old']);
  assert.equal(old.context.jobId,null);
  assert.equal(old.values.size,0);
  assert.match(old.elements.job.innerHTML,/Downloads antigos ficam no Acervo/);

  const active=fixture({status:'running',competence:'2026-11'});
  await active.context.restoreLatestDownload();
  assert.equal(active.context.jobId,'job-old');
  assert.equal(active.context.polled,true);
  console.log('Acompanhamento mostra somente o download ativo do projeto.');
})().catch(error=>{console.error(error);process.exitCode=1});
