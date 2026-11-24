const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'assets', 'stages.js'), 'utf8');
const names = ['data','preparation','geocoding','review'];
const sections = names.map(stage => ({dataset:{stage},hidden:false,
  querySelector(){return {textContent:'',className:''}}}));
const stageProgress = {innerHTML:'',querySelectorAll(){return []},scrollIntoView(){}};
const listeners = {};
const overview = {innerHTML:'',append(){}};
const context = {
  window:{},URLSearchParams,projectId:'project1',location:{search:'?project=project1&stage=review'},
  GeoUI:{request:async url => url.includes('/projects/')
    ? {name:'Projeto',competence:'2026-11',rows:504,coverage:{is_partial:false},
       steps:{data:{status:'completed'},preparation:{status:'completed'},geocoding:{status:'pending'},review:{status:'locked'}}}
    : {competences:[{competence:'2026-11',present:2}]}},
  document:{
    addEventListener(name, handler){listeners[name]=handler},
    querySelectorAll(selector){return selector==='.workflow-stage'?sections:[]},
    getElementById(id){return {stageProgress,projectOverview:overview,reviewResult:{innerHTML:''}}[id]}
  },
  fmtElapsed:()=>'',withProject:url=>url
};
vm.createContext(context);
vm.runInContext(source,context);
assert.deepEqual(sections.map(section=>section.hidden),[false,true,true,true]);

(async()=>{
  await context.window.workflowRefresh('geocoding',false);
  assert.deepEqual(sections.map(section=>section.hidden),[true,true,false,true]);
  context.window.workflowOpen('review');
  assert.deepEqual(sections.map(section=>section.hidden),[true,true,false,true]);
  context.GeoUI.request = async url => url.includes('/projects/')
    ? {name:'Projeto',competence:'2026-11',steps:{data:{status:'completed'},preparation:{status:'completed'},geocoding:{status:'completed'},review:{status:'available'}}}
    : {competences:[]};
  await listeners.DOMContentLoaded();
  assert.deepEqual(sections.map(section=>section.hidden),[true,true,true,false]);
  console.log('Retorno do mapa abre a etapa de revisão.');
})().catch(error=>{console.error(error);process.exitCode=1});
