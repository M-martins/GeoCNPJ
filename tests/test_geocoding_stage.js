const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'assets', 'index.js'), 'utf8');
const start = source.indexOf('function renderGeoCoverage(');
const end = source.indexOf('async function handleGeoService(', start);
assert(start >= 0 && end > start);
const elements = Object.fromEntries(['geoArtifact','geoReadiness','startGeo','geoHistory','geoJob'].map(id =>
  [id, {innerHTML:'',className:'',textContent:'',value:'',disabled:true,append(item){this.warning=item.textContent}}]));
const context = {
  $: id => elements[id], api:'/api', currentProject:{process_job_id:'process1'}, geoOnline:false, escUi:value=>String(value), geoJobId:null,
  json:async url => url.endsWith('/artifacts')
    ? [{process_job_id:'process1',municipality_name:'BIRITIBA-MIRIM',uf:'SP',competence:'2026-11',rows:504,is_partial:true,parts_used:2,parts_official:10}]
    : url.endsWith('/health') ? {online:true,ok:true,message:'Python disponível'} : [],
  checkPhase3Reuse:async()=>{},withProject:url=>url,
  document:{createElement:()=>({className:'',textContent:''})}
};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
(async()=>{
  await context.loadPhase3();
  assert.equal(elements.startGeo.disabled,false);
  assert.equal(elements.geoArtifact.value,'process1');
  assert.match(elements.geoReadiness.warning,/2 de 10/);
  assert.doesNotMatch(elements.geoReadiness.textContent,/Cannot set properties/);
  console.log('Etapa de geocodificação disponível e aviso parcial verificados.');
})().catch(error=>{console.error(error);process.exitCode=1});
