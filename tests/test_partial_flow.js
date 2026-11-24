const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'assets', 'index.js'), 'utf8');
const start = source.indexOf('async function startProcess(){');
const end = source.indexOf('async function restoreLatestProcess(){', start);
assert(start >= 0 && end > start);
const elements = {
  startProcess: {}, processReadiness: {className:'',textContent:''},
  processCompetence:{value:'2026-11'},processUf:{value:'SP'},activeOnly:{checked:true},outputFormat:{value:'csv'}
};
let accepted = false, requests = [], confirmations = 0;
const context = {
  $: id => elements[id], api:'/api', projectId:'project1',
  municipalityChoice:{code:'6231',name:'BIRITIBA-MIRIM'},
  processMonthState:{validated:false,can_prepare:true,present:2,official_count:10},
  GeoUI:{busy(){},async confirm(){confirmations++;return accepted}},
  json:async (url,options)=>{requests.push(JSON.parse(options.body));return {job_id:'job1'}},
  pollProcess(){},processJobId:null
};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);

(async()=>{
  await context.startProcess();
  assert.equal(requests.length,0);
  accepted=true;
  await context.startProcess();
  assert.equal(requests.length,1);
  assert.equal(requests[0].accept_incomplete,true);
  assert.equal(requests[0].municipality_code,'6231');
  assert.equal(confirmations,2);
  context.processMonthState={validated:true,can_prepare:true,present:10,official_count:10};
  await context.startProcess();
  assert.equal(requests[1].accept_incomplete,false);
  assert.equal(confirmations,2);

  const readinessStart=source.indexOf('let processMonthState=null');
  const readinessEnd=source.indexOf('async function validateData(',readinessStart);
  const monthElements={competence:{value:'2026-11'},processCompetence:{value:'2026-11'},processReadiness:{className:'',textContent:'',innerHTML:''},downloadMissingParts:{onclick:null}};
  const monthContext={
    $:id=>monthElements[id],window:{workflowOpen(){}},
    catalog:Array.from({length:10},()=>({kind:'establishment'})),updateProcessButton(){},
    json:async()=>({}),api:'/api',validationId:null,validationAttempted:new Set()
  };
  vm.createContext(monthContext);
  vm.runInContext(source.slice(readinessStart,readinessEnd)+'\nfunction selectedMonth(){return processMonthState}',monthContext);
  vm.runInContext('readinessState={references_complete:true,competences:[{competence:"2026-11",validated:false,present:2}]}',monthContext);
  await monthContext.showSelectedMonth();
  assert.equal(monthContext.selectedMonth().can_prepare,true);
  assert.match(monthElements.processReadiness.innerHTML,/pode gerar uma base/);
  console.log('Aceite da base parcial e envio da decisão verificados.');
})().catch(error=>{console.error(error);process.exitCode=1});
