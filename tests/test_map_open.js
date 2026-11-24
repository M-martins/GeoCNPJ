const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'assets', 'map.js'), 'utf8');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {id, value:'', innerHTML:'', textContent:'', style:{}, hidden:false,
    options:[{text:'Todos'}], setAttribute(){}, classList:{add(){},remove(){},contains(){return false}}});
  return elements.get(id);
}
const createdMarkers = [];
class Marker {
  constructor({element}) { this.element=element; this.removed=false; createdMarkers.push(this); }
  setLngLat(coordinates) { this.coordinates=coordinates; return this; }
  addTo() { return this; }
  remove() { this.removed=true; }
}
class FakeMap {
  constructor() { this.sources={}; this.handlers={}; this.canvas={style:{}}; this.zoom=10; this.bounds=[-46.5,-23.6,-46.2,-23.3]; setTimeout(()=>this.handlers['style.load']?.(),0); }
  addControl() {}
  addSource(id,source) { this.sources[id]={setData:data=>{this.sources[id].data=data},data:source.data}; }
  getSource(id) { return this.sources[id]; }
  getCanvas() { return this.canvas; }
  addLayer() {}
  on(name,callback,layerCallback) { this.handlers[layerCallback?name+':'+callback:name]=layerCallback||callback; }
  queryRenderedFeatures() { return []; }
  getBounds() { const b=this.bounds; return {getWest:()=>b[0],getSouth:()=>b[1],getEast:()=>b[2],getNorth:()=>b[3]}; }
  getZoom() { return this.zoom; }
  fitBounds(b,opts) { this.bounds=[b[0][0],b[0][1],b[1][0],b[1][1]];this.zoom=opts.maxZoom;this.handlers.moveend?.(); }
  easeTo(opts) { this.center=opts.center;if(opts.zoom)this.zoom=opts.zoom;this.handlers.moveend?.(); }
  project([lng,lat]) { return {x:lng*100000,y:lat*100000}; }
  unproject({x,y}) { return {lng:x/100000,lat:y/100000}; }
}
let mapInstance, viewportRequests=0;
const features=[1,2].map(n=>({type:'Feature',geometry:{type:'Point',coordinates:[-46.35,-23.4]},properties:{cnpj_completo:String(n),nome_fantasia:'Empresa '+n,quality:n===1?'review':'high'}}));
const context={URLSearchParams,AbortController,location:{search:'?job=job1&project=project1'},localStorage:{getItem(){return null},setItem(){}},
  setTimeout,clearTimeout,console,
  document:{getElementById:element,createElement:()=>({style:{},setAttribute(){},classList:{add(){},remove(){}}}),
    querySelector:selector=>selector==='.side'?{insertBefore(){}}:element('filters'),
    querySelectorAll:selector=>selector==='.back-to-stages'?[element('backOne'),element('backTwo')]:selector==='.filter input:checked'?[{value:'high'},{value:'alert'},{value:'review'},{value:'unknown'}]:[]},
  maplibregl:{Map:class extends FakeMap{constructor(...args){super(...args);mapInstance=this}},Marker,NavigationControl:class{},LngLatBounds:class{}},
  GeoUI:{request:async url=>url.endsWith('/summary')?{metadata:{mapped:2,total_records:2,quality:{review:2}},bounds:[-46.4,-23.5,-46.3,-23.3],precisions:[],decisions:[]}:url.includes('/records?')?{total:0,features:[]}:url.endsWith('/job1')?{is_partial:false}:url.includes('/records/')?features[0]:{records:{}},toast(){},state(id,kind,message){console.error(id,kind,message)}} ,
  fetch:async url=>({ok:true,json:async()=>url.includes('/viewport?')?(viewportRequests++,{features:url.includes('zoom=16')?features:[{type:'Feature',geometry:{type:'Point',coordinates:[-46.35,-23.4]},properties:{cluster:true,point_count:2,high:0,alert:0,review:2,unknown:0}}]}):url.includes('/reviews')?{records:{}}:{name:'Projeto de teste'}})
};
vm.createContext(context);vm.runInContext(source,context);
(async()=>{
  for(let attempt=0;attempt<40&&!viewportRequests;attempt++)await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(viewportRequests,1,'pontos devem carregar na abertura');
  mapInstance.handlers['mousemove:points']({features:[features[0]]});
  assert.equal(mapInstance.sources['hover-point'].data.features[0].properties.cnpj_completo,'1','passar o mouse deve realçar o ponto');
  assert.equal(mapInstance.canvas.style.cursor,'pointer');
  mapInstance.handlers['mouseleave:points']();
  assert.equal(mapInstance.sources['hover-point'].data.features.length,0,'tirar o mouse deve remover o realce');
  assert.equal(mapInstance.canvas.style.cursor,'');
  assert.match(elements.get('backOne').href,/stage=review/);
  mapInstance.zoom=16;mapInstance.bounds=[-46.4,-23.5,-46.3,-23.3];
  await context.loadViewport();
  const overlap=createdMarkers.find(marker=>marker.element.className.includes('overlap-marker')&&!marker.removed);
  assert.ok(overlap,'coordenadas repetidas devem virar grupo clicável');
  assert.match(overlap.element.style.background,/#dc2626/);
  assert.match(overlap.element.style.background,/#16a34a/);
  overlap.element.onclick({stopPropagation(){}});
  const spiderPoints=createdMarkers.filter(marker=>marker.element.className==='spider-point'&&!marker.removed);
  assert.equal(spiderPoints.length,2,'grupo deve abrir em leque');
  mapInstance.handlers.click({point:{}});
  assert.equal(spiderPoints.filter(marker=>!marker.removed).length,0,'clique fora deve fechar o leque');
  overlap.element.onclick({stopPropagation(){}});
  const reopened=createdMarkers.filter(marker=>marker.element.className==='spider-point'&&!marker.removed);
  reopened[0].element.onclick({stopPropagation(){}});
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(elements.get('recordDetail').hidden,false,'detalhes devem abrir à direita');
  assert.deepEqual(Array.from(mapInstance.center),[-46.35,-23.4],'ponto deve ser centralizado');
  assert.match(elements.get('recordDetailBody').innerHTML,/company-card/);
  mapInstance.handlers.click({point:{}});
  assert.equal(elements.get('recordDetail').hidden,true,'clique fora deve fechar o detalhe');
  console.log('Abertura do mapa, aranha, centralização e detalhes à direita verificados.');
})().catch(error=>{console.error(error);process.exitCode=1});
