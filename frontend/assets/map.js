const params=new URLSearchParams(location.search),job=params.get('job'),projectId=params.get('project')||localStorage.getItem('geocnpj_project'),colors={high:'#16a34a',alert:'#eab308',review:'#dc2626',unknown:'#64748b'};let map,summary,reviews={},detailCache=new Map(),page=1,total=0,pageFeatures=[],viewportFeatures=[],selectedRows=new Set(),selectedCnpj=null,hoveredCnpj=null,lastViewportKey=null,clusterMarkers=[],spiderMarkers=[],requestTimer=null,viewportController=null;const PAGE_SIZE=120,$=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function renderSummary(m={}){const total=m.total_records??m.total_registros_csv??0,mapped=m.mapped??m.total_features_geojson??0,without=m.without_coordinates??m.total_sem_coordenada??0,review=m.quality?.review;const value=n=>n==null?'—':Number(n).toLocaleString('pt-BR');$('summary').innerHTML=`<div class="stat"><b>${value(total)}</b>Processados</div><div class="stat"><b>${value(mapped)}</b>No mapa</div><div class="stat"><b>${value(without)}</b>Sem coordenada</div><div class="stat"><b>${value(review)}</b>Para revisão</div>`}
function isReviewed(f){return !!reviews[String(f.properties.cnpj_completo)]?.reviewed}
function filters(){return {qualities:[...document.querySelectorAll('.filter input:checked')].map(x=>x.value).join(',')||'__none__',cnpj:$('searchCnpj').value.trim(),name:$('searchName').value.trim(),street:$('searchStreet').value.trim(),number:$('searchNumber').value.trim(),neighborhood:$('neighborhood').value.trim(),score_min:$('scoreMin').value,score_max:$('scoreMax').value,precision:$('precision').value,decision:$('decision').value,cnae:$('searchCnae').value.trim(),activity:$('searchActivity').value.trim(),project_id:projectId||'',review_state:$('reviewState').value}}
function query(extra={}){const q=new URLSearchParams({...filters(),...extra});for(const [k,v] of [...q])if(v==='')q.delete(k);return q}
function featureBounds(features){const bounds=new maplibregl.LngLatBounds();features.forEach(f=>bounds.extend(f.geometry.coordinates));return bounds}
function focusFeatures(features){if(!features.length)return;if(features.length===1)return map.flyTo({center:features[0].geometry.coordinates,zoom:17});const bounds=featureBounds(features);if(!bounds.isEmpty())map.fitBounds(bounds,{padding:70,maxZoom:16,duration:650})}
function highlightFeature(feature){
  const source=map?.getSource('selected-point');
  if(source)source.setData({type:'FeatureCollection',features:[feature]});
}
function hoverFeature(feature){
  const cnpj=String(feature?.properties?.cnpj_completo||'');
  if(hoveredCnpj===cnpj)return;
  hoveredCnpj=cnpj;
  const source=map?.getSource('hover-point');
  if(source)source.setData({type:'FeatureCollection',features:feature?[feature]:[]});
  if(map)map.getCanvas().style.cursor=feature?'pointer':'';
}
function clearHover(){hoverFeature(null)}
function closeDetail(){
  $('recordDetail').hidden=true;selectedCnpj=null;
  const source=map?.getSource('selected-point');
  if(source)source.setData({type:'FeatureCollection',features:[]});
  renderTable();
}
async function showPopup(f){
  const cnpj=String(f.properties.cnpj_completo);
  selectedCnpj=cnpj;
  $('recordDetail').hidden=false;
  $('recordDetailBody').innerHTML='<div class="popup-loading">Carregando cadastro completo…</div>';
  highlightFeature(f);renderTable();
  map.easeTo({center:f.geometry.coordinates,zoom:Math.max(map.getZoom(),16),duration:320});
  try{
    let full=detailCache.get(cnpj);
    if(!full){full=await GeoUI.request(`/api/geocoding/${job}/map/records/${encodeURIComponent(cnpj)}`);detailCache.set(cnpj,full)}
    if(selectedCnpj!==cnpj)return;
    const p=full.properties,secondary=String(p.cnae_fiscal_secundaria||'').split(',').filter(Boolean).join(', ')||'Não informado',type=String(p.identificador_matriz_filial)==='1'?'Matriz':String(p.identificador_matriz_filial)==='2'?'Filial':'Não informado';
    $('recordDetailBody').innerHTML=`<article class="company-card"><header><span class="company-card__eyebrow">ESTABELECIMENTO</span><h3>${esc(p.nome_fantasia||'Sem nome fantasia')}</h3><span class="company-card__cnpj">CNPJ ${esc(p.cnpj_completo)}</span></header><div class="company-card__address">${esc(p.endereco_completo||'Endereço não informado')}</div><section class="company-card__activity"><span>ATIVIDADE PRINCIPAL · ${esc(p.cnae_fiscal_principal||'Não informado')}</span><strong>${esc(p.cnae_principal_desc||'Não informada')}</strong><div class="company-card__hierarchy"><em>Seção ${esc(p.cnae_secao_codigo||'—')} · ${esc(p.cnae_secao_descricao||'Não informada')}</em><em>Divisão ${esc(p.cnae_divisao_codigo||'—')} · ${esc(p.cnae_divisao_descricao||'Não informada')}</em><em>Grupo ${esc(p.cnae_grupo_codigo||'—')} · ${esc(p.cnae_grupo_descricao||'Não informado')}</em></div></section><dl class="company-card__details"><div><dt>Situação</dt><dd>${esc(p.situacao_cadastral_desc||p.situacao_cadastral||'Não informada')}</dd></div><div><dt>Tipo</dt><dd>${esc(type)}</dd></div><div><dt>Início</dt><dd>${esc(p.data_inicio_atividade||'Não informado')}</dd></div><div><dt>Qualidade</dt><dd><i class="quality-indicator" style="background:${colors[p.quality]||colors.unknown}"></i>${esc(p.quality_label||'Não classificada')}</dd></div><div><dt>Score</dt><dd>${esc(p.score_geocode??'—')}</dd></div><div><dt>Precisão</dt><dd>${esc(p.precisao||'Não informada')}</dd></div></dl><details><summary>Dados complementares</summary><div class="company-card__extra"><span><b>CNAEs secundários</b>${esc(secondary)}</span><span><b>Motivo da geocodificação</b>${esc(p.decisao_geocode||'Não informado')}</span></div></details></article>`;
  }catch(e){if(selectedCnpj===cnpj)$('recordDetailBody').innerHTML=`<div class="popup-error"><b>Não foi possível carregar os detalhes.</b><span>${esc(e.message)}</span></div>`}
}
function clusterHtml(p,overlap=false){
  const total=Number(p.point_count),keys=['high','alert','review','unknown'];
  let cursor=0;const parts=[];
  for(const quality of keys){const next=cursor+Number(p[quality]||0)/total*360;parts.push(`${colors[quality]} ${cursor}deg ${next}deg`);cursor=next}
  const el=document.createElement('button');
  const size=overlap?Math.min(39,29+Math.log2(total)*2.5):Math.min(55,31+Math.log2(total)*2.6);
  el.className=overlap?'cluster-marker overlap-marker':'cluster-marker';
  el.style.width=el.style.height=size+'px';
  el.style.background=`conic-gradient(${parts.join(',')})`;
  el.innerHTML=`<span>${total.toLocaleString('pt-BR')}</span>`;
  el.setAttribute('aria-label',`${overlap?'Abrir':'Aproximar'} grupo de ${total} registros`);
  return el;
}
function clearMarkers(){clusterMarkers.forEach(m=>m.remove());clusterMarkers=[]}
function clearSpiderfy(){clearHover();spiderMarkers.forEach(m=>m.remove());spiderMarkers=[];const source=map?.getSource('spider-lines');if(source)source.setData({type:'FeatureCollection',features:[]})}
const coordinateKey=c=>c.map(v=>Number(v).toFixed(7)).join('|');
function spiderfy(feature,offset=0){
  const center=feature.geometry.coordinates,key=coordinateKey(center),group=viewportFeatures.filter(f=>!f.properties.cluster&&coordinateKey(f.geometry.coordinates)===key);
  clearSpiderfy();
  if(group.length<2)return showPopup(feature);
  map.easeTo({center,duration:0});
  const origin=map.project(center),visible=group.slice(offset,offset+36),lines=[];
  visible.forEach((item,index)=>{
    const ring=Math.floor(index/12),slot=index%12,radius=27+ring*20,angle=slot/12*Math.PI*2,target=map.unproject({x:origin.x+Math.cos(angle)*radius,y:origin.y+Math.sin(angle)*radius}),el=document.createElement('button');
    el.className='spider-point';el.style.background=colors[item.properties.quality]||colors.unknown;
    el.title=`${item.properties.nome_fantasia||'Sem nome fantasia'} · ${item.properties.cnpj_completo}`;
    el.onclick=e=>{e.stopPropagation();showPopup(item)};
    spiderMarkers.push(new maplibregl.Marker({element:el}).setLngLat(target).addTo(map));
    lines.push({type:'Feature',geometry:{type:'LineString',coordinates:[center,[target.lng,target.lat]]},properties:{}});
  });
  if(group.length>36){
    const next=offset+36<group.length?offset+36:0,el=document.createElement('button');
    el.className='spider-center';el.textContent=`${offset+1}–${offset+visible.length} / ${group.length}`;
    el.title='Mostrar outros registros neste ponto';el.onclick=e=>{e.stopPropagation();spiderfy(feature,next)};
    spiderMarkers.push(new maplibregl.Marker({element:el}).setLngLat(center).addTo(map));
  }
  map.getSource('spider-lines').setData({type:'FeatureCollection',features:lines});
}
async function loadViewport(){
  if(!map?.getSource('points'))return;
  const b=map.getBounds(),q=query({west:b.getWest(),south:b.getSouth(),east:b.getEast(),north:b.getNorth(),zoom:map.getZoom()}),key=q.toString();
  if(key===lastViewportKey)return;
  lastViewportKey=key;
  viewportController?.abort();viewportController=new AbortController();
  try{
    const data=await fetch(`/api/geocoding/${job}/map/viewport?${q}`,{signal:viewportController.signal}).then(r=>r.ok?r.json():Promise.reject(Error('Falha ao carregar a área visível.')));
    viewportFeatures=data.features;clearHover();clearMarkers();
    const singles=[],groups=new Map();
    for(const f of viewportFeatures){
      if(f.properties.cluster){
        const el=clusterHtml(f.properties);
        el.onclick=event=>{event.stopPropagation();clearSpiderfy();map.easeTo({center:f.geometry.coordinates,zoom:Math.min(17,Math.max(15,map.getZoom()+2))})};
        clusterMarkers.push(new maplibregl.Marker({element:el}).setLngLat(f.geometry.coordinates).addTo(map));
      }else{
        const key=coordinateKey(f.geometry.coordinates);
        if(!groups.has(key))groups.set(key,[]);
        groups.get(key).push(f);
      }
    }
    for(const group of groups.values()){
      if(group.length===1){singles.push(group[0]);continue}
      const counts={point_count:group.length,high:0,alert:0,review:0,unknown:0};
      for(const feature of group)counts[feature.properties.quality in colors?feature.properties.quality:'unknown']++;
      const el=clusterHtml(counts,true);
      el.setAttribute('aria-label',`Abrir ${group.length} registros nesta coordenada`);
      el.onclick=event=>{event.stopPropagation();spiderfy(group[0])};
      clusterMarkers.push(new maplibregl.Marker({element:el}).setLngLat(group[0].geometry.coordinates).addTo(map));
    }
    map.getSource('points').setData({type:'FeatureCollection',features:singles});
  }catch(e){if(lastViewportKey===key)lastViewportKey=null;if(e.name!=='AbortError')GeoUI.toast(e.message,'error')}
}
function scheduleViewport(){clearTimeout(requestTimer);requestTimer=setTimeout(loadViewport,80)}
async function loadRecords(focus=false){const data=await GeoUI.request(`/api/geocoding/${job}/map/records?${query({page,page_size:PAGE_SIZE})}`);total=data.total;pageFeatures=data.features;renderTable();if(focus)focusFeatures(pageFeatures)}
function renderTable(){const pages=Math.max(1,Math.ceil(total/PAGE_SIZE));page=Math.min(page,pages);$('resultCount').textContent=`${total.toLocaleString('pt-BR')} registro(s) no filtro`;$('selectionCount').textContent=selectedRows.size?`${selectedRows.size.toLocaleString('pt-BR')} registro(s) selecionado(s).`:'Nenhum registro selecionado: a exportação usará todo o filtro.';$('pageLabel').textContent=`Página ${page} de ${pages}`;$('prev').disabled=page===1;$('next').disabled=page>=pages;$('reviewList').innerHTML=pageFeatures.length?pageFeatures.map(f=>{const p=f.properties,cnpj=esc(p.cnpj_completo),reviewed=isReviewed(f),chosen=selectedRows.has(String(p.cnpj_completo));return `<div class="review-row ${reviewed?'reviewed':''} ${selectedCnpj===p.cnpj_completo?'selected':''}" data-cnpj="${cnpj}" role="button" tabindex="0"><input class="select-box" type="checkbox" ${chosen?'checked':''} aria-label="Selecionar para exportação"><input class="review-box" type="checkbox" ${reviewed?'checked':''} aria-label="Marcar como revisado"><span><b>${esc(p.nome_fantasia||'Sem nome fantasia')}</b><small>${cnpj}<br>${esc(p.bairro||'Bairro não informado')} · ${esc(p.precisao)} · ${esc(p.decisao_geocode)}</small></span><span class="score">${esc(p.score_geocode)}</span></div>`}).join(''):'<div class="review-row"><span></span><span>Nenhum registro corresponde aos filtros.</span></div>';document.querySelectorAll('.review-row[data-cnpj]').forEach(row=>{row.onclick=e=>{const f=pageFeatures.find(x=>String(x.properties.cnpj_completo)===row.dataset.cnpj);if(e.target.classList.contains('select-box')){e.stopPropagation();e.target.checked?selectedRows.add(row.dataset.cnpj):selectedRows.delete(row.dataset.cnpj);renderTable();focusFeatures(pageFeatures.filter(x=>selectedRows.has(String(x.properties.cnpj_completo))))}else if(e.target.classList.contains('review-box')){e.stopPropagation();setReviewed(row.dataset.cnpj,e.target.checked)}else{showPopup(f)}};row.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();row.click()}}})}
async function applyFilters({focus=false}={}){page=1;clearSpiderfy();await Promise.all([loadRecords(focus),loadViewport()])}
function clearAllFilters(){for(const id of ['searchCnpj','searchName','searchStreet','searchNumber','searchCnae','searchActivity','neighborhood','scoreMin','scoreMax'])$(id).value='';for(const id of ['precision','decision','reviewState'])$(id).value='';document.querySelectorAll('.filter input').forEach(x=>x.checked=true);selectedRows.clear();selectedCnpj=null;applyFilters();const b=summary.bounds;if(b.every(Number.isFinite))map.fitBounds([[b[0],b[1]],[b[2],b[3]]],{padding:45,maxZoom:13})}
async function updateSuggestions(kind){const input=$({cnpj:'searchCnpj',name:'searchName',street:'searchStreet',activity:'searchActivity'}[kind]),box=$({cnpj:'suggestCnpj',name:'suggestName',street:'suggestStreet',activity:'suggestActivity'}[kind]);if(input.value.trim().length<2){box.classList.remove('open');return}const rows=await GeoUI.request(`/api/geocoding/${job}/map/suggestions?field=${kind}&q=${encodeURIComponent(input.value)}`);box.innerHTML=rows.length?rows.map((f,i)=>`<div class="suggestion" data-index="${i}"><b>${esc(kind==='cnpj'?f.properties.cnpj_completo:kind==='name'?f.properties.nome_fantasia:kind==='activity'?f.properties.cnae_principal_desc:f.properties.logradouro)}</b><small>${esc(kind==='street'?f.properties.bairro:kind==='activity'?f.properties.cnae_fiscal_principal:f.properties.endereco_completo||f.properties.cnpj_completo)}</small></div>`).join(''):'<div class="suggestion"><small>Nenhuma sugestão.</small></div>';box.classList.add('open');box.querySelectorAll('[data-index]').forEach(el=>el.onclick=()=>{const f=rows[Number(el.dataset.index)],p=f.properties;$('searchCnpj').value=kind==='cnpj'?p.cnpj_completo:$('searchCnpj').value;$('searchName').value=kind==='name'?p.nome_fantasia:$('searchName').value;$('searchStreet').value=kind==='street'?p.logradouro:$('searchStreet').value;if(kind==='street')$('neighborhood').value=p.bairro||'';if(kind==='activity'){$('searchActivity').value=p.cnae_principal_desc||'';$('searchCnae').value=p.cnae_fiscal_principal||'';}box.classList.remove('open');applyFilters({focus:true})})}
async function setReviewed(cnpj,value){if(!projectId)return GeoUI.toast('Abra o mapa a partir de um projeto para salvar a revisão.','error');reviews[cnpj]=await GeoUI.request(`/api/projects/${projectId}/reviews/${encodeURIComponent(cnpj)}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({reviewed:value})});renderTable()}
function exportRows(format){const q=query({format,selected:[...selectedRows].join(',')});location.href=`/api/geocoding/${job}/map/export?${q}`}
async function showCoverageWarning(project){
  let result;
  try{result=await GeoUI.request(`/api/geocoding/${job}`)}catch(error){return}
  $('resultContext').textContent=`Dados exibidos: ${[result.municipality_name,project?.uf].filter(Boolean).join('/')||'Município não informado'} · ${result.competence||'mês não informado'}`;
  if(!result.is_partial)return;
  const warning=document.createElement('div');warning.className='map-coverage-warning';
  warning.textContent=`Cobertura parcial: ${result.parts_used} de ${result.parts_official} partes oficiais. Registros ausentes da base não aparecem neste mapa.`;
  document.querySelector('.side').insertBefore(warning,document.querySelector('.filters'));
}
async function init(){
  if(!job)throw Error('Geocodificação não informada.');
  if(projectId){
    localStorage.setItem('geocnpj_project',projectId);
    const destination=`/etapas?project=${encodeURIComponent(projectId)}&stage=review`;
    document.querySelectorAll('.back-to-stages').forEach(link=>link.href=destination);
  }
  const [mapSummary,project,reviewData]=await Promise.all([
    GeoUI.request(`/api/geocoding/${job}/map/summary`),
    projectId?fetch(`/api/projects/${projectId}`).then(r=>r.ok?r.json():null).catch(()=>null):null,
    projectId?fetch(`/api/projects/${projectId}/reviews`).then(r=>r.ok?r.json():({records:{}})).catch(()=>({records:{}})):{records:{}}
  ]);
  showCoverageWarning(project);
  summary=mapSummary;reviews=reviewData.records||{};
  if(project)$('projectName').textContent=project.name;
  renderSummary(summary.metadata);
  $('precision').innerHTML+=[...summary.precisions].map(v=>`<option value="${esc(v)}">${esc(v.replaceAll('_',' '))}</option>`).join('');
  $('decision').innerHTML+=[...summary.decisions].map(v=>`<option value="${esc(v)}">${esc(v.replaceAll('_',' '))}</option>`).join('');
  loadRecords();
  map=new maplibregl.Map({container:'map',center:[-46.18,-23.52],zoom:10,style:{version:8,sources:{osm:{type:'raster',tiles:['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],tileSize:256,attribution:'© OpenStreetMap contributors'}},layers:[{id:'osm',type:'raster',source:'osm'}]}});
  map.addControl(new maplibregl.NavigationControl());
  map.on('style.load',()=>{
    map.addSource('points',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    map.addSource('spider-lines',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    map.addSource('hover-point',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    map.addSource('selected-point',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    map.addLayer({id:'spider-lines',type:'line',source:'spider-lines',paint:{'line-color':'#475569','line-width':1.5}});
    map.addLayer({id:'points',type:'circle',source:'points',paint:{'circle-radius':['interpolate',['linear'],['zoom'],12,3,17,7],'circle-color':['match',['get','quality'],'high',colors.high,'alert',colors.alert,'review',colors.review,colors.unknown],'circle-stroke-width':1,'circle-stroke-color':'#fff'}});
    map.addLayer({id:'hover-point',type:'circle',source:'hover-point',paint:{'circle-radius':['interpolate',['linear'],['zoom'],12,10,17,15],'circle-color':['match',['get','quality'],'high',colors.high,'alert',colors.alert,'review',colors.review,colors.unknown],'circle-opacity':0.35,'circle-stroke-width':3,'circle-stroke-color':'#0b3b82'}});
    map.addLayer({id:'selected-point',type:'circle',source:'selected-point',paint:{'circle-radius':15,'circle-color':'#fff','circle-opacity':0.16,'circle-stroke-width':4,'circle-stroke-color':'#1d4ed8'}});
    map.on('mousemove','points',e=>{if(e.features?.[0])hoverFeature(e.features[0])});
    map.on('mouseleave','points',clearHover);
    map.on('click','points',e=>spiderfy(e.features[0]));
    map.on('click',e=>{if(map.queryRenderedFeatures(e.point,{layers:['points','selected-point']}).length)return;clearSpiderfy();if(!$('recordDetail').hidden)closeDetail()});
    map.on('zoomstart',clearSpiderfy);
    map.on('moveend',scheduleViewport);
    const b=summary.bounds;
    if(b.every(Number.isFinite))map.fitBounds([[b[0],b[1]],[b[2],b[3]]],{padding:45,maxZoom:13,duration:0});
    loadViewport();
  });
}
let filterTimer;
const suggestionInputs={cnpj:'searchCnpj',name:'searchName',street:'searchStreet',activity:'searchActivity'};
document.querySelectorAll('input,select').forEach(x=>{
  x.setAttribute('aria-label',x.placeholder||x.options?.[0]?.text||x.id);
  if(!Object.values(suggestionInputs).includes(x.id)) x.oninput=()=>{
    clearTimeout(filterTimer);
    filterTimer=setTimeout(()=>applyFilters(),250);
  };
});
for(const [kind,id] of Object.entries(suggestionInputs)){
  const input=$(id);
  if(!input){console.warn(`Campo de busca ausente: ${id}`);continue}
  input.oninput=()=>{
    clearTimeout(filterTimer);
    filterTimer=setTimeout(()=>{updateSuggestions(kind);applyFilters()},300);
  };
}
$('clearFilters').onclick=clearAllFilters;
$('selectPage').onclick=()=>{pageFeatures.forEach(f=>selectedRows.add(String(f.properties.cnpj_completo)));renderTable();focusFeatures(pageFeatures)};
$('clearSelection').onclick=()=>{selectedRows.clear();renderTable()};
$('prev').onclick=()=>{page--;loadRecords()};
$('next').onclick=()=>{page++;loadRecords()};
$('exportCsv').onclick=()=>exportRows('csv');
$('exportGeojson').onclick=()=>exportRows('geojson');
$('closeDetail').onclick=closeDetail;
$('mapHelpToggle').onclick=()=>{const box=$('mapHelp');box.hidden=!box.hidden;$('mapHelpToggle').setAttribute('aria-expanded',String(!box.hidden))};
$('mapHelpClose').onclick=()=>{$('mapHelp').hidden=true;$('mapHelpToggle').setAttribute('aria-expanded','false')};
init().catch(e=>GeoUI.state('reviewList','error',e.message,{retry:()=>location.reload()}));
