
const api='/api',query=new URLSearchParams(location.search);let projectId=query.get('project')||localStorage.getItem('geocnpj_project'),currentProject=null,catalog=[],jobId=null,processJobId=null,validationId=null,geoJobId=null,geoOnline=false,dataRoot='',storageFree=null,destinationTimer=null;const $=id=>document.getElementById(id);const escUi=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));if(projectId)localStorage.setItem('geocnpj_project',projectId);
let downloadStartedHere = false;
async function selectProjectMonth(month) {
  if (!projectId) throw new Error('Abra um projeto antes de continuar para a base municipal.');
  currentProject = await json(`${api}/projects/${encodeURIComponent(projectId)}/select-month/${encodeURIComponent(month)}`, {method:'POST'});
}
async function loadProject(){if(!projectId)return;try{currentProject=await json(api+'/projects/'+projectId);$('projectBadge').textContent=currentProject.name;if(currentProject.competence&&$('competence').querySelector(`option[value="${currentProject.competence}"]`))$('competence').value=currentProject.competence}catch(e){projectId=null;localStorage.removeItem('geocnpj_project')}}
function withProject(url){if(!projectId)return url;return url+(url.includes('?')?'&':'?')+'project='+encodeURIComponent(projectId)}
function fmt(value){
  if(value==null)return '—';
  const units=['B','KB','MB','GB','TB'];let size=Number(value),unit=0;
  while(size>=1000&&unit<units.length-1){size/=1000;unit++}
  const digits=unit===0?0:size>=100?1:2;
  return `${size.toLocaleString('pt-BR',{minimumFractionDigits:unit?1:0,maximumFractionDigits:digits})} ${units[unit]}`;
}
function fmtElapsed(seconds){
  const value=Math.max(0,Math.round(Number(seconds)||0)),hours=Math.floor(value/3600),minutes=Math.floor(value%3600/60),rest=value%60;
  return hours?`${hours} h ${minutes} min ${rest} s`:minutes?`${minutes} min ${rest} s`:`${rest} s`;
}
function processSeconds(job){
  if(job.processing_seconds!=null)return job.processing_seconds;
  const start=Date.parse(job.started_at||job.created_at),end=Date.parse(job.finished_at||job.updated_at);
  return Number.isFinite(start)&&Number.isFinite(end)?Math.max(0,(end-start)/1000):null;
}
async function json(url,opt){return GeoUI.request(url,opt)}
function statusPt(status){return {queued:'Na fila',running:'Em andamento',uploading:'Enviando dados',cancelling:'Interrompendo',cancelled:'Interrompido',completed:'Concluído',error:'Falhou',interrupted:'Interrompido'}[status]||status}
function joinLocal(base,child){return String(base||'').replace(/[\\/]+$/,'')+'\\'+child}
function updateDestinationPreview(){
  if(!dataRoot)return;
  const month=$('competence').value,custom=$('destinationRoot').value.trim();
  $('destination').textContent=custom?joinLocal(custom,month):joinLocal(joinLocal(dataRoot,'competencias'),month);
  $('referencesDestination').textContent=joinLocal(dataRoot,'referencias');
  $('freeSpace').textContent=custom?'Verificando…':fmt(storageFree);
  clearTimeout(destinationTimer);
  if(custom)destinationTimer=setTimeout(async()=>{
    try{const result=await json(api+'/storage?path='+encodeURIComponent(custom));if($('destinationRoot').value.trim()===custom)$('freeSpace').textContent=fmt(result.free)}
    catch(e){$('freeSpace').textContent='Não verificado'}
  },350);
  if(catalog.length)updateSelection();
}
async function load(){
  GeoUI.busy($('refresh'),true,'Atualizando…');
  try{
    $('message').textContent='';
    const [c,s]=await Promise.all([json(api+'/catalog/competences'),json(api+'/storage')]);
    $('competence').innerHTML=c.competences.map(x=>`<option ${x===c.latest?'selected':''}>${escUi(x)}</option>`).join('');
    $('competence').disabled=false;dataRoot=s.path;storageFree=s.free;
    await loadProject();updateDestinationPreview();await loadFiles();await loadProcessReadiness();await loadPhase3();await restoreLatestDownload();await restoreLatestProcess();
  }catch(e){GeoUI.state('message','error',e.message,{retry:load})}
  finally{GeoUI.busy($('refresh'),false)}
}
async function loadFiles(){
  try{const c=$('competence').value,d=await json(api+'/catalog/'+c);catalog=d.files;renderFiles();selectRecommended();updateDestinationPreview()}
  catch(e){$('message').textContent=e.message}
}
const referenceDescriptions={
  'Cnaes.zip':'Atividades econômicas: traduz os códigos CNAE.',
  'Motivos.zip':'Motivos da situação cadastral dos estabelecimentos.',
  'Municipios.zip':'Nomes e códigos de município usados pela Receita.',
  'Paises.zip':'Nomes e códigos de países do cadastro.',
  'MunicipiosUF.csv':'Receita Federal: relaciona os códigos municipais à UF; complementa o Municipios.zip.',
  'CNAE_Subclasses_2_3_Estrutura_Detalhada.xlsx':'IBGE/Concla: hierarquia CNAE 2.3 para seção, divisão e grupo (enriquecimento opcional).'
};
function fileStatus(file){
  const state=file.local?.status;
  if(state==='same_month')return 'Arquivo local encontrado';
  if(state==='reusable')return 'Versão idêntica: reutilizar';
  if(state==='shared_reference')return 'Biblioteca local: verificar mês';
  return file.name.endsWith('.xlsx')?'No IBGE/Concla':'Na Receita Federal';
}
function renderFiles(){
  const establishments=catalog.map((file,index)=>({file,index})).filter(item=>item.file.kind==='establishment');
  const references=catalog.filter(file=>file.kind==='reference');
  $('files').innerHTML=
    '<div class="section">Partes da base de Estabelecimentos</div>'+
    '<p class="file-intro">São divisões da mesma base nacional. Uma ou mais partes permitem gerar uma base parcial; selecione todas para ter cobertura completa do mês.</p>'+
    establishments.map(({file,index})=>`<label class="file"><input class="pick" type="checkbox" data-index="${index}"><span><b>${escUi(file.name)}</b><br><small>Parte da base nacional do mês selecionado</small></span><span class="size">${fmt(file.size)}</span><span class="status">${fileStatus(file)}</span></label>`).join('')+
    '<div class="section">Referências do CNPJ · incluídas automaticamente</div>'+
    '<p class="file-intro">Os quatro ZIPs a seguir são publicados com a base CNPJ pela Receita Federal e compartilhados entre projetos.</p>'+
    references.filter(file=>file.name.endsWith('.zip')).map(renderReference).join('')+
    '<div class="section">Complementos oficiais · incluídos automaticamente</div>'+
    '<p class="file-intro">O arquivo de município/UF vem de <a href="https://www.gov.br/receitafederal/dados/municipios.csv/view" target="_blank" rel="noopener">outra publicação da Receita ↗</a> e completa o Municipios.zip. A planilha de hierarquia CNAE 2.3 vem do <a href="https://cnae.ibge.gov.br/classificacoes/download-concla/8265-download" target="_blank" rel="noopener">IBGE/Concla ↗</a>; sem ela, o processamento continua, mas não acrescenta seção, divisão e grupo.</p>'+
    references.filter(file=>!file.name.endsWith('.zip')).map(renderReference).join('');
  document.querySelectorAll('.pick').forEach(input=>input.onchange=updateSelection);
}
function renderReference(file){const source=file.name.endsWith('.xlsx')?'IBGE / Concla':'Receita Federal';const size=file.size==null?'Arquivo pequeno':fmt(file.size);return `<div class="file reference-file"><span class="reference-marker" aria-hidden="true">✓</span><span><b>${escUi(file.name)}</b><br><small>${escUi(referenceDescriptions[file.name]||'Tabela auxiliar.')}</small><br><small>Fonte: ${source}</small></span><span class="size">${size}</span><span class="status">${fileStatus(file)}</span></div>`}
function selectRecommended(){document.querySelectorAll('.pick').forEach(input=>input.checked=true);updateSelection()}
function selectedEstablishments(){return [...document.querySelectorAll('.pick:checked')].map(input=>catalog[+input.dataset.index])}
function samePath(a,b){return String(a||'').replace(/\\/g,'/').replace(/\/$/,'').toLowerCase()===String(b||'').replace(/\\/g,'/').replace(/\/$/,'').toLowerCase()}
function establishmentAtDestination(file,destination=$('destination').textContent){return file?.local?.status==='same_month'&&samePath(file.local.path,joinLocal(destination,file.name))}
function downloadSelectionMode(chosen=selectedEstablishments(),references=catalog.filter(file=>file.kind==='reference')){
  const local=chosen.filter(file=>establishmentAtDestination(file)).length;
  const referencesLocal=references.every(file=>['same_month','reusable'].includes(file.local?.status));
  if(chosen.length&&local===chosen.length&&referencesLocal)return {label:'Conferir arquivos já disponíveis',busy:'Conferindo arquivos…',confirm:'Conferir arquivos já disponíveis?',confirmButton:'Conferir arquivos',local};
  if(chosen.length&&local===chosen.length)return {label:'Obter tabelas auxiliares',busy:'Obtendo tabelas…',confirm:'Obter tabelas auxiliares necessárias?',confirmButton:'Obter tabelas',local};
  if(local)return {label:'Baixar apenas o que falta',busy:'Obtendo arquivos…',confirm:'Baixar apenas os arquivos faltantes?',confirmButton:'Obter arquivos',local};
  return {label:'Baixar arquivos selecionados',busy:'Baixando arquivos…',confirm:'Baixar arquivos da Receita para este computador?',confirmButton:'Iniciar download',local};
}
function updateSelection(){
  const chosen=selectedEstablishments(),total=catalog.filter(file=>file.kind==='establishment').length;
  const references=catalog.filter(file=>file.kind==='reference'),mode=downloadSelectionMode(chosen,references);
  const saved=catalog.filter(file=>file.kind==='establishment'&&establishmentAtDestination(file)).length;
  $('selectedSize').textContent=fmt([...chosen,...references].reduce((sum,file)=>sum+(file.size||0),0));
  $('selectionNote').textContent='Na pasta indicada: '+saved+' de '+total+' partes deste mês. '+(!chosen.length?'Selecione ao menos uma parte.':mode.local===chosen.length?'As partes selecionadas já estão disponíveis. O GeoCNPJ confere os arquivos antes de avançar.':mode.local?`${mode.local} de ${chosen.length} partes selecionadas já estão disponíveis; serão obtidas apenas as faltantes.`:chosen.length===total?'Todas as partes estão selecionadas para este pedido.':'Para gerar a base municipal completa, obtenha todas as partes.');
  const button=$('start'),busy=button.getAttribute('aria-busy')==='true';
  button.dataset.idleText=mode.label;
  if(!busy)button.textContent=mode.label;
  button.disabled=busy||!chosen.length;
}
async function start(){
  const chosen=selectedEstablishments(),references=catalog.filter(file=>file.kind==='reference');
  if(!chosen.length)return;
  const mode=downloadSelectionMode(chosen,references),month=$('competence').value,destination_root=$('destinationRoot').value.trim()||null;
  const complete=chosen.length===catalog.filter(file=>file.kind==='establishment').length;
  const detail=`Fonte: Receita Federal / SERPRO\nMês: ${month}\nEstabelecimentos: ${chosen.length} parte(s), ${mode.local} já na pasta indicada\nReferências e complementos: ${references.length}, incluídos automaticamente\nTamanho máximo: ${$('selectedSize').textContent}\nZIPs de Estabelecimentos: ${$('destination').textContent}\nReferências e complementos: ${$('referencesDestination').textContent}${complete?'':'\n\nVocê poderá gerar uma base parcial; registros das partes não baixadas ficarão de fora.'}`;
  if(!await GeoUI.confirm(mode.confirm,detail,mode.confirmButton))return;
  GeoUI.busy($('start'),true,'Iniciando…');
  try{
    const files=[...chosen,...references].map(file=>file.name);
    const job=await json(api+'/downloads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({competence:month,files,destination_root})});
    jobId=job.job_id;sessionStorage.setItem(downloadSessionKey(),jobId);downloadStartedHere=true;GeoUI.busy($('start'),true,mode.busy);poll();
  }catch(e){GeoUI.state('message','error',e.message);GeoUI.busy($('start'),false);updateSelection()}
}
function downloadBusyLabel(job){
  const destination=job.destination||$('destination').textContent;
  const allLocal=(job.files||[]).every(item=>{if(['reused','completed'].includes(item.status))return true;const file=catalog.find(entry=>entry.name===item.name);return item.kind==='reference'?['same_month','reusable'].includes(file?.local?.status):establishmentAtDestination(file,destination)});
  return allLocal?'Conferindo arquivos…':'Obtendo arquivos…';
}
async function action(name){await json(`${api}/downloads/${jobId}/${name}`,{method:'POST'});poll()}
function downloadCompletionState(saved, total, referencesReady) {
  if (!referencesReady) return {
    heading: 'Tabelas auxiliares ausentes',
    message: `Há ${saved} de ${total} partes de Estabelecimentos no computador, mas faltam tabelas auxiliares da Receita. Baixe-as com os arquivos selecionados antes de preparar a base.`,
    canAdvance: false, warning: true, selectLabel: 'Selecionar arquivos necessários'
  };
  if (total > 0 && saved === total) return {
    heading: 'Arquivos disponíveis neste computador',
    message: `Todas as ${total} partes deste mês estão no computador. Na etapa 2, escolha a UF e o município; o GeoCNPJ confere os arquivos automaticamente.`,
    canAdvance: true, warning: false, selectLabel: null
  };
  return {
    heading: 'Base parcial disponível neste computador',
    message: `Há ${saved} de ${total} partes deste mês no computador. Na etapa 2, você pode gerar uma base parcial; o resultado pode omitir registros.`,
    canAdvance: true, warning: false, selectLabel: 'Selecionar partes restantes'
  };
}
function downloadSessionKey(){return 'geocnpj_download_'+(projectId||'local')}
function clearDownloadView(){
  jobId=null;downloadStartedHere=false;
  $('job').innerHTML='<div class="empty-state"><b>Nenhum download em andamento neste projeto</b><span>Escolha os arquivos acima para começar. Downloads antigos ficam no Acervo.</span></div>';
}
async function restoreLatestDownload(){
  const savedId=sessionStorage.getItem(downloadSessionKey());
  if(!savedId){clearDownloadView();return}
  try{
    const job=await json(api+'/downloads/'+encodeURIComponent(savedId));
    if(job.status==='completed'){
      sessionStorage.removeItem(downloadSessionKey());clearDownloadView();return;
    }
    if(job.competence!==$('competence').value){clearDownloadView();return}
    jobId=savedId;await poll();
  }catch(e){sessionStorage.removeItem(downloadSessionKey());clearDownloadView()}
}
async function poll(){
  if(!jobId)return;
  try{
    const j=await json(api+'/downloads/'+jobId);
    const active=['queued','running','cancelling'].includes(j.status);
    const historical=j.status==='completed';
    $('job').innerHTML=(historical?'<details class="download-history"><summary>Ver detalhes do pedido anterior concluído</summary>':'')+
      `<div class="jobtop"><b>Mês ${escUi(j.competence)} · ${historical?'Histórico do pedido':statusPt(j.status)}</b><span>${fmt(j.downloaded_bytes)} / ${fmt(j.total_bytes)} · ${j.percent||0}% ${historical?'do pedido anterior':'do pedido'}</span></div><div class="progress"><div class="bar" style="width:${j.percent||0}%"></div></div><p>Arquivo atual: <b>${escUi(j.current_file||'—')}</b></p><div class="logs">${escUi((j.logs||[]).slice(-8).join('\n'))}</div><div class="actions">${active?'<button class="danger" onclick="action(\'cancel\')">Interromper</button>':''}${['cancelled','error'].includes(j.status)?'<button onclick="action(\'resume\')">Retomar</button>':''}</div>`+
      (historical?'</details>':'');
    if(active){GeoUI.busy($('start'),true,downloadBusyLabel(j));setTimeout(poll,1500);return}
    GeoUI.busy($('start'),false);
    if(j.status==='completed'){
      sessionStorage.removeItem(downloadSessionKey());
      $('competence').value=j.competence;
      await loadFiles();
      await loadProcessReadiness();
      const parts=catalog.filter(file=>file.kind==='establishment');
      const localMonth=(readinessState?.competences||[]).find(item=>item.competence===j.competence);
      const saved=Number(localMonth?.present||0);
      if(saved===0){clearDownloadView();updateSelection();return}
      const completion=downloadCompletionState(saved,parts.length,readinessState?.references_complete===true);
      if (downloadStartedHere && completion.canAdvance && projectId) {
        downloadStartedHere = false;
        try { await selectProjectMonth(j.competence); await window.workflowRefresh?.('data', false); }
        catch (error) { GeoUI.toast(error.message, 'error'); }
      }
      const next=completion.canAdvance?'<button id="downloadNext" class="primary" type="button" onclick="goToPreparation()">Próxima etapa: conferir dados →</button>':'';
      const select=completion.selectLabel?`<button id="selectRemaining" type="button" onclick="selectRemaining()">${completion.selectLabel}</button>`:'';
      $('job').insertAdjacentHTML('afterbegin',`<div class="download-finish${completion.warning?' missing':''}"><strong>${completion.heading}</strong><p>${completion.message}</p><div class="actions">${next}${select}</div></div>`);
    }
    updateSelection();
  }catch(e){$('message').textContent=e.message;GeoUI.busy($('start'),false);updateSelection()}
}
function selectRemaining(){
  document.querySelectorAll('.pick').forEach(input=>input.checked=!establishmentAtDestination(catalog[+input.dataset.index]));
  updateSelection();
  $('files').scrollIntoView({behavior:'smooth',block:'start'});
}
async function goToPreparation(){
  try {
    const month=$('competence').value;
    await selectProjectMonth(month);
    await loadProcessReadiness();
    const option=[...$('processCompetence').options].find(item=>item.value===month);
    if(option){$('processCompetence').value=month;await showSelectedMonth()}
    if(window.workflowRefresh) await window.workflowRefresh('preparation');
    else {
      const stage=$('phase2');
      document.querySelectorAll('.workflow-stage').forEach(node=>node.hidden=node!==stage);
      stage.scrollIntoView({behavior:'smooth',block:'start'});
    }
  } catch(error) {
    GeoUI.toast(error.message, 'error');
  }
}
let processMonthState=null,readinessState=null,validationAttempted=new Set(),expectedCounts=new Map();
async function expectedParts(month){
  if(expectedCounts.has(month))return expectedCounts.get(month);
  const files=month===$('competence').value?catalog:(await json(api+'/catalog/'+month)).files;
  const count=files.filter(file=>file.kind==='establishment').length;
  expectedCounts.set(month,count);return count;
}
async function loadProcessReadiness(){
  const r=await json(api+'/process/readiness'),local=r.competences||[],select=$('processCompetence');
  const previous=select.disabled?'':select.value;
  readinessState=r;
  select.innerHTML=local.length?local.map(c=>`<option value="${escUi(c.competence)}">${escUi(c.competence)}</option>`).join(''):'<option value="">Nenhum mês no computador</option>';
  select.disabled=!local.length;
  const preferred=[previous,$('competence').value,...(r.ready_competences||[])].find(month=>local.some(c=>c.competence===month));
  if(preferred)select.value=preferred;
  await showSelectedMonth();
}
async function showSelectedMonth(){
  const month=$('processCompetence').value,local=(readinessState?.competences||[]).find(c=>c.competence===month),notice=$('processReadiness');
  processMonthState=local?{...local,can_prepare:local.validated}:null;
  if(!local){notice.className='notice';notice.textContent='Baixe um mês dos dados da Receita Federal na etapa 01 para começar.';updateProcessButton();return}
  if(!readinessState.references_complete){notice.className='notice';notice.textContent='As tabelas de apoio da Receita ainda não estão neste computador. Volte à etapa 01 para baixá-las.';updateProcessButton();return}
  if(local.validated){notice.className='notice ok';notice.textContent=`${month} pronto para preparar a base municipal. ${local.present} partes dos dados disponíveis.`;updateProcessButton();return}
  notice.className='notice';notice.textContent=`Conferindo as partes disponíveis de ${month}...`;updateProcessButton();
  try{
    const total=local.expected||await expectedParts(month),missing=Math.max(0,total-local.present);
    processMonthState={...local,official_count:total,can_prepare:local.present>0&&missing>0};updateProcessButton();
    if(missing){notice.innerHTML=`<b>${local.present} de ${total} partes deste mês estão no computador.</b><p>Você pode gerar uma base apenas com as partes disponíveis. O resultado será parcial: estabelecimentos que estão nas outras ${missing} partes não aparecerão nas contagens, na geocodificação ou no mapa.</p><button type="button" id="downloadMissingParts">Ver partes para baixar</button>`;const button=$('downloadMissingParts');button.onclick=()=>window.workflowOpen?.('data');return}
    if(validationId)return;
    if(validationAttempted.has(month)){showValidationFailure();return}
    validationAttempted.add(month);await validateData(month);
  }catch(error){notice.textContent='Não foi possível conferir este mês agora. '+error.message}
}
async function validateData(month){
  try{const state=await json(api+'/process/validate/'+month,{method:'POST'});validationId=state.validation_id;pollValidation()}
  catch(error){validationId=null;showValidationFailure()}
}
function showValidationFailure(){const notice=$('processReadiness');notice.className='notice';notice.innerHTML='<b>Não foi possível conferir este mês.</b><p>Confira os downloads na etapa 01 e tente novamente.</p><button type="button">Conferir novamente</button>';notice.querySelector('button').onclick=()=>{validationAttempted.delete($('processCompetence').value);showSelectedMonth()}}
async function pollValidation(){
  if(!validationId)return;
  try{
    const v=await json(api+'/process/validation/'+validationId),active=['queued','running'].includes(v.status),notice=$('processReadiness');
    notice.className=v.status==='completed'?'notice ok':'notice';
    if(active){notice.innerHTML=`<b>Conferindo os dados de ${v.competence} automaticamente...</b><div class="progress" style="margin-top:10px"><div class="bar" style="width:${v.percent||0}%"></div></div><div style="margin-top:7px">${v.files_completed||0} de ${v.total_files||'?'} partes conferidas</div>`;setTimeout(pollValidation,800)}
    else{validationId=null;if(v.status==='completed')await loadProcessReadiness();else showValidationFailure()}
  }catch(error){validationId=null;showValidationFailure()}
}
let municipalityChoice=null,municipalityTimer=null,municipalitySequence=0,municipalityCache=new Map(),municipalityRows=[];
function normalizeMunicipality(value){return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toUpperCase()}
function hideMunicipalitySuggestions(){const list=$('municipalitySuggestions');list.hidden=true;$('municipalityQuery').setAttribute('aria-expanded','false')}
function chooseMunicipality(row){municipalityChoice={code:row.code,name:row.name,uf:$('processUf').value};$('municipalityQuery').value=row.name;$('municipalityHint').textContent=`${row.name} selecionado · código Receita ${row.code}`;hideMunicipalitySuggestions();updateProcessButton()}
function renderMunicipalitySuggestions(rows){
  const list=$('municipalitySuggestions');municipalityRows=rows;
  list.replaceChildren();
  if(!rows.length){const empty=document.createElement('div');empty.className='municipality-empty';empty.textContent='Nenhum município encontrado. Confira o nome.';list.append(empty)}
  else rows.slice(0,12).forEach(row=>{const button=document.createElement('button');button.type='button';button.setAttribute('role','option');const repeated=rows.filter(item=>item.name===row.name).length>1;button.textContent=repeated?`${row.name} · código ${row.code}`:row.name;button.title=`Código Receita ${row.code}`;button.onmousedown=event=>event.preventDefault();button.onclick=()=>chooseMunicipality(row);list.append(button)});
  list.hidden=false;$('municipalityQuery').setAttribute('aria-expanded','true');
}
async function searchMunicipality(){
  const q=$('municipalityQuery').value.trim(),seq=++municipalitySequence;
  municipalityChoice=null;updateProcessButton();
  if(q.length<2){hideMunicipalitySuggestions();$('municipalityHint').textContent='As sugestões aparecem enquanto você digita.';return}
  $('municipalityHint').textContent='Procurando município...';
  try{
    const normalized=normalizeMunicipality(q),key=$('processUf').value+':'+normalized,rows=municipalityCache.has(key)?municipalityCache.get(key):await json(api+'/municipalities?q='+encodeURIComponent(q)+'&uf='+encodeURIComponent($('processUf').value));
    if(seq!==municipalitySequence)return;
    municipalityCache.set(key,rows);
    const exact=rows.filter(row=>normalizeMunicipality(row.name)===normalized);
    if(exact.length===1){chooseMunicipality(exact[0]);return}
    renderMunicipalitySuggestions(rows);$('municipalityHint').textContent=exact.length>1?'Há municípios com este mesmo nome. Confira o código antes de escolher.':rows.length?'Escolha uma sugestão ou continue digitando.':'Tente outra grafia.';
  }catch(error){if(seq!==municipalitySequence)return;hideMunicipalitySuggestions();$('municipalityHint').textContent='Busca indisponível no momento. Tente novamente.'}
}
let reuseOptions=[],reuseTimer=null,processActive=false;
function updateProcessButton(){$('startProcess').disabled=processActive||!processMonthState?.can_prepare||!readinessState?.references_complete||!municipalityChoice||municipalityChoice.uf!==$('processUf').value;clearTimeout(reuseTimer);reuseTimer=setTimeout(checkReuse,250)}
async function checkReuse(){const notice=$('reuseNotice');if(!projectId||!processMonthState?.can_prepare||!municipalityChoice){notice.style.display='none';return}const query=new URLSearchParams({competence:$('processCompetence').value,uf:$('processUf').value,municipality_code:municipalityChoice.code,active_only:$('activeOnly').checked,output_format:$('outputFormat').value});try{reuseOptions=await json(api+'/reuse/matches?'+query);if(!reuseOptions.length){notice.style.display='none';return}const best=reuseOptions[0],p=best.process,owners=best.projects.map(x=>x.name).join(', '),geo=best.geocodings[0],coverage=p.is_partial?`<p><b>Base parcial: ${p.source_files?.length||0} de ${p.official_file_count||'?'} partes oficiais.</b> Os registros podem estar incompletos.</p>`:'';notice.style.display='block';notice.className='notice ok';notice.innerHTML=`<b>Este mesmo recorte já foi processado.</b><p>${escUi(p.municipality_name)}/${escUi(p.uf)} · ${escUi(p.competence)} · ${Number(p.rows_found||0).toLocaleString('pt-BR')} registros${owners?' · usado em '+escUi(owners):''}.</p>${coverage}<div class="row"><button onclick="reusePrepared(0)">Usar base municipal pronta</button>${geo?'<button class="primary" onclick="reuseGeocoded(0,0)">Usar também a geocodificação</button>':''}<button onclick="dismissReuse()">Processar novamente</button></div>`}catch(e){notice.style.display='none'}}
function dismissReuse(){$('reuseNotice').style.display='none';reuseOptions=[]}
async function reusePrepared(index){if(!await GeoUI.confirm('Reutilizar base municipal?','A base pronta será vinculada ao projeto atual e nenhum processamento será repetido.','Usar base pronta'))return;const match=reuseOptions[index];currentProject=await json(`${api}/projects/${projectId}/attach-process/${match.process.job_id}`,{method:'POST'});$('projectBadge').textContent=currentProject.name;$('reuseNotice').innerHTML='<b>Base municipal reutilizada.</b> Nenhum processamento foi repetido.';await loadPhase3();document.getElementById('phase3').scrollIntoView({behavior:'smooth'})}
async function reuseGeocoded(index,geoIndex){if(!await GeoUI.confirm('Reutilizar resultado geocodificado?','A base e a geocodificação concluídas serão vinculadas ao projeto atual.','Usar resultado pronto'))return;const match=reuseOptions[index],geo=match.geocodings[geoIndex];await json(`${api}/projects/${projectId}/attach-process/${match.process.job_id}`,{method:'POST'});currentProject=await json(`${api}/projects/${projectId}/attach-geocoding/${geo.job_id}`,{method:'POST'});location.href=withProject(geo.map_url)}
async function checkPhase3Reuse(){if(!currentProject?.process_job_id||currentProject?.geocoding_job_id)return;const query=new URLSearchParams({competence:currentProject.competence,uf:currentProject.uf,municipality_code:currentProject.municipality_code,active_only:currentProject.active_only,output_format:currentProject.process_output_format||'csv'});const matches=await json(api+'/reuse/matches?'+query),candidate=matches.find(m=>m.geocodings.length&&m.process.job_id!==currentProject.process_job_id);if(!candidate)return;reuseOptions=matches;const index=matches.indexOf(candidate),geo=candidate.geocodings[0];$('geoReadiness').className='notice ok';$('geoReadiness').innerHTML=`<b>Uma geocodificação equivalente já existe.</b><p>Você pode reaproveitar o mapa e o pacote concluídos, ou iniciar uma nova geocodificação.</p><button class="primary" onclick="reuseGeocoded(${index},0)">Usar geocodificação existente</button>`}
async function startProcess(){
  if(!municipalityChoice||!processMonthState?.can_prepare)return;
  const partial=!processMonthState.validated,used=processMonthState.present,total=processMonthState.official_count||processMonthState.expected;
  if(partial&&!await GeoUI.confirm('Gerar base com cobertura parcial?',
    `Você escolheu ${used} de ${total} partes do mês ${$('processCompetence').value}. A base pode omitir estabelecimentos do município. As contagens, a geocodificação e o mapa também ficarão incompletos.\n\nSua decisão e as partes usadas serão registradas no resultado.`,
    'Gerar base parcial'))return;
  GeoUI.busy($('startProcess'),true,'Iniciando…');
  try{const payload={competence:$('processCompetence').value,uf:$('processUf').value,municipality_code:municipalityChoice.code,municipality_name:municipalityChoice.name,active_only:$('activeOnly').checked,output_format:$('outputFormat').value,project_id:projectId,accept_incomplete:partial};const j=await json(api+'/processes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});processJobId=j.job_id;GeoUI.busy($('startProcess'),true,'Preparando base…');if(projectId)try{currentProject=await json(api+'/projects/'+projectId)}catch(error){}pollProcess()}
  catch(e){$('processReadiness').className='notice';$('processReadiness').textContent=e.message;GeoUI.busy($('startProcess'),false)}
}
async function restoreLatestProcess(){try{const jobs=await json(api+'/processes'),active=jobs.find(j=>['queued','running','cancelling'].includes(j.status)),recent=active||jobs.find(j=>j.job_id===currentProject?.process_job_id);if(recent){processJobId=recent.job_id;processActive=!!active;const month=[...$('processCompetence').options].find(option=>option.value===recent.competence);if(month){$('processCompetence').value=recent.competence;await showSelectedMonth()}updateProcessButton();pollProcess()}}catch(error){/* A consulta do histórico não impede o restante da etapa. */}}
async function goToGeocoding(){
  const stage=$('phase3');
  document.querySelectorAll('.workflow-stage').forEach(node=>{node.hidden=node!==stage});
  document.querySelectorAll('.stage-step').forEach(node=>node.classList.toggle('active',node.dataset.stage==='geocoding'));
  stage.scrollIntoView({behavior:'smooth',block:'start'});
  if(window.workflowRefresh)try{await window.workflowRefresh('geocoding',false)}catch(error){}
  await loadPhase3();
}
async function cancelProcess(){await json(`${api}/processes/${processJobId}/cancel`,{method:'POST'});pollProcess()}
async function pollProcess(){if(!processJobId)return;try{const j=await json(api+'/processes/'+processJobId),active=['queued','running','cancelling'].includes(j.status),wasActive=processActive;processActive=active;const coverage=j.is_partial?`<div class="notice partial-warning"><b>Base parcial: ${j.source_files?.length||0} de ${j.official_file_count||'?'} partes oficiais.</b> Os registros e totais deste município podem estar incompletos. Esta decisão foi registrada.</div>`:'';$('processJob').innerHTML=`<div class="jobtop"><b>${escUi(j.municipality_name)} / ${escUi(j.uf)} · ${statusPt(j.status)}</b><span>${j.percent||0}%</span></div>${coverage}<div class="progress"><div class="bar" style="width:${j.percent||0}%"></div></div><div class="process-metrics"><div><small>Registros encontrados</small><b>${Number(j.rows_found||0).toLocaleString('pt-BR')}</b></div><div><small>Arquivos usados</small><b>${j.total_files||'?'}${j.is_partial?' de '+(j.official_file_count||'?')+' oficiais':''}</b></div><div><small>Tempo de geração</small><b>${processSeconds(j)==null?'—':fmtElapsed(processSeconds(j))}</b></div></div><p>${Number(j.rows_read||0).toLocaleString('pt-BR')} linhas lidas · ${j.files_completed||0}/${j.total_files||'?'} arquivos concluídos</p><div class="logs">${escUi((j.logs||[]).slice(-8).join('\n'))}</div><div class="actions">${active?'<button class="danger" onclick="cancelProcess()">Cancelar</button>':''}${j.status==='completed'?`<a href="${j.download_url}" class="primary" style="padding:11px 13px;border-radius:9px;background:var(--ink);color:#fff;text-decoration:none;font-weight:700">Baixar resultado</a> <button class="primary" onclick="goToGeocoding()">Continuar para geocodificação →</button>`:''}</div>`;if(active){updateProcessButton();setTimeout(pollProcess,1500)}else{GeoUI.busy($('startProcess'),false);updateProcessButton();if(j.status==='completed'){await loadPhase3();if(window.workflowRefresh&&wasActive)await window.workflowRefresh('preparation',false)}}}catch(e){$('processReadiness').textContent=e.message;GeoUI.busy($('startProcess'),false);updateProcessButton()}}
async function loadInventory(){try{const items=await json(api+'/library');$('inventory').innerHTML=items.length?items.map(i=>`<div class="file" style="grid-template-columns:1fr 130px 130px auto"><span><b>${i.competence}</b><br><small>${escUi(i.path)} · ${i.origin==='pasta_existente'?'Pasta externa vinculada':'Gerenciada pelo GeoCNPJ'}</small></span><span>${i.file_count} ZIP(s)</span><span>${fmt(i.size)}</span><span><span class="badge">${i.validated?'Validada':'Não validada'}</span> <button class="danger" onclick="removeLibrary('${i.competence}',${i.managed})">${i.managed?'Excluir':'Remover vínculo'}</button></span></div>`).join(''):'<div class="section">Nenhum mês de dados registrado.</div>'}catch(e){showLibrary(e.message,false)}}
async function chooseFolder(target){try{const result=await json(api+'/system/select-folder',{method:'POST'});if(result.path){$(target).value=result.path;$(target).dispatchEvent(new Event('input'))}}catch(e){showLibrary(e.message,false)}}
function showLibrary(message,ok){$('libraryMessage').style.display='block';$('libraryMessage').className=ok?'notice ok':'notice';$('libraryMessage').textContent=message}
async function importExisting(){try{const competence=$('importCompetence').value.trim(),folder=$('importFolder').value.trim();if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(competence))throw new Error('Informe o mês dos dados no formato AAAA-MM.');if(!folder)throw new Error('Informe o caminho completo da pasta.');showLibrary('Consultando o catálogo e validando os ZIPs da pasta...',true);const result=await json(api+'/library/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({competence,folder})});showLibrary(`${competence} importada e validada com ${result.manifest.files.length} arquivo(s).`,true);await loadInventory();await loadProcessReadiness()}catch(e){showLibrary(e.message,false)}}
async function removeLibrary(competence,managed){const text=managed?`A pasta do mês ${competence} será enviada para a Lixeira.`:`O vínculo de ${competence} será removido e os arquivos externos serão preservados.`;if(!await GeoUI.confirm(managed?'Enviar arquivos do mês para a Lixeira?':'Remover vínculo?',text,managed?'Enviar à Lixeira':'Remover vínculo',managed))return;try{const result=await json(`${api}/library/${competence}/remove`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delete_files:managed})});showLibrary(result.message,true);GeoUI.toast(result.message);await loadInventory();await loadProcessReadiness()}catch(e){showLibrary(e.message,false)}}
function renderGeoCoverage(artifacts){
  const artifact=artifacts.find(item=>item.process_job_id===$('geoArtifact').value);
  if(!artifact?.is_partial)return;
  $('geoReadiness').className='notice';
  const warning=document.createElement('div');warning.className='coverage-warning';
  warning.textContent=`Base parcial: ${artifact.parts_used} de ${artifact.parts_official} partes oficiais. A geocodificação e o mapa também terão cobertura incompleta.`;
  $('geoReadiness').append(warning);
}
async function loadPhase3(){try{const [artifacts,health,history]=await Promise.all([json(api+'/geocoding/artifacts'),json(api+'/geocoding/health'),json(api+'/geocoding')]);geoOnline=health.online&&health.ok;const projectArtifacts=currentProject?.process_job_id?artifacts.filter(a=>a.process_job_id===currentProject.process_job_id):[];$('geoArtifact').innerHTML=projectArtifacts.length?projectArtifacts.map(a=>`<option value="${a.process_job_id}">${escUi(a.municipality_name)}/${escUi(a.uf)} · ${escUi(a.competence)} · ${Number(a.rows).toLocaleString('pt-BR')} registros</option>`).join(''):'<option>Conclua primeiro a etapa 2</option>';$('geoArtifact').disabled=!projectArtifacts.length;if(currentProject?.process_job_id&&projectArtifacts.some(a=>a.process_job_id===currentProject.process_job_id))$('geoArtifact').value=currentProject.process_job_id;$('geoReadiness').className=projectArtifacts.length&&geoOnline?'notice ok':'notice';$('geoReadiness').innerHTML=!projectArtifacts.length?'Etapa 3 bloqueada: gere uma base neste projeto ou <a href="/collection">escolha uma no acervo local</a>.':geoOnline?`Etapa 3 liberada. ${escUi(health.message||'Python/geocodebr disponível.')}`:`A base está pronta, mas o motor Python não respondeu. Verifique a instalação e tente novamente.`;$('startGeo').disabled=!projectArtifacts.length||!geoOnline;if(!geoOnline&&projectArtifacts.length&&!$('startGeo').dataset.startAttempted){$('startGeo').dataset.startAttempted='1';handleGeoService()}const completed=history.filter(j=>j.status==='completed'&&j.map_url&&currentProject?.geocoding_job_id&&j.job_id===currentProject.geocoding_job_id);$('geoJob').hidden=!!completed.length&&!geoJobId;$('geoHistory').innerHTML=completed.length?completed.map(j=>`<div class="file" style="grid-template-columns:1fr auto"><span><b>${escUi(j.municipality_name)} · ${escUi(j.competence)}</b><br><small>${j.map_summary?.mapped||0} pontos · ${j.map_summary?.without_coordinates||0} sem coordenada</small></span><span><a href="${withProject(j.map_url)}" class="btn">Abrir mapa</a> <a href="${j.download_url}" class="btn">Baixar pacote</a></span></div>`).join(''):'<div class="file">Nenhum mapa gerado ainda.</div>';const live=history.find(j=>currentProject?.geocoding_job_id===j.job_id&&['queued','uploading','running','cancelling'].includes(j.status));if(live&&!geoJobId){geoJobId=live.job_id;pollGeo()}await checkPhase3Reuse();renderGeoCoverage(projectArtifacts)}catch(e){$('geoReadiness').textContent=e.message}}
async function handleGeoService(){try{if(!geoOnline){$('geoReadiness').textContent='Verificando motor Python...';await json(api+'/geocoding/start-service',{method:'POST'});setTimeout(loadPhase3,3500)}else await loadPhase3()}catch(e){$('geoReadiness').textContent=e.message}}
async function startGeo(){$('geoJob').hidden=false;GeoUI.busy($('startGeo'),true,'Iniciando…');try{const payload={process_job_id:$('geoArtifact').value,output_format:$('geoFormat').value,cores:Number($('geoCores').value)||1,resolve_ties:$('resolveTies').checked,project_id:projectId},j=await json(api+'/geocoding',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});geoJobId=j.job_id;GeoUI.busy($('startGeo'),true,'Geocodificando…');pollGeo()}catch(e){$('geoReadiness').textContent=e.message;GeoUI.busy($('startGeo'),false)}}
const GEO_STAGES=[['reading','Ler base'],['preparing','Preparar endereços'],['cache','Consultar cache'],['matching','Comparar com CNEFE'],['merging','Aplicar critérios'],['exporting','Gerar arquivos'],['packaging','Montar pacote']];
function geoElapsed(job){const start=Date.parse(job.started_at||job.created_at),end=job.finished_at?Date.parse(job.finished_at):Date.now();return Number.isFinite(start)?fmtElapsed((end-start)/1000):'—'}
function geoPhase(job){const stage=job.stage||job.remote?.stage;const found=GEO_STAGES.findIndex(([id])=>id===stage);return job.status==='completed'?GEO_STAGES.length:found>=0?found:0}
function geoProgressHtml(j){const remote=j.remote||{},phase=geoPhase(j),active=['queued','uploading','running','cancelling'].includes(j.status),done=j.status==='completed',parts=GEO_STAGES.map(([id,label],index)=>`<li class="${index<phase?'done':index===phase&&active?'current':''}">${index<phase?'✓':index+1}. ${label}</li>`).join(''),metric=(label,value)=>`<div><small>${label}</small><b>${value}</b></div>`,count=n=>n==null?'—':Number(n).toLocaleString('pt-BR'),logs=remote.logs||j.logs||[];return `<div class="jobtop"><b>${escUi(j.municipality_name)} · ${statusPt(j.status)}</b><span>${done?'Concluído':active?`Fase ${Math.min(phase+1,GEO_STAGES.length)} de ${GEO_STAGES.length}`:'—'}</span></div><ol class="geo-phases">${parts}</ol><p>${escUi(j.message||'Aguardando andamento do motor.')}</p>${active&&phase===3?'<p class="geo-progress-note">A comparação com o CNEFE não informa porcentagem por endereço; o tempo e os eventos abaixo continuam sendo atualizados.</p>':''}<div class="process-metrics">${metric('Registros de entrada',count(remote.total_registros_entrada))}${metric('Endereços únicos',count(remote.total_enderecos_unicos))}${metric('Reutilizados do cache',count(remote.enderecos_em_cache))}${metric('Novos para geocodebr',count(remote.enderecos_novos_para_geocodebr))}${metric('Tempo decorrido',geoElapsed(j))}</div>${logs.length?`<div class="logs">${escUi(logs.slice(-8).join('\n'))}</div>`:''}<div class="actions">${active&&j.can_cancel?'<button class="danger" type="button" onclick="cancelGeo()">Parar geocodificação</button>':''}${done?`<a href="${withProject(j.map_url)}" class="primary" style="padding:11px 13px;border-radius:9px;background:var(--blue);color:#fff;text-decoration:none;font-weight:700">Visualizar mapa</a> <a href="${j.download_url}" class="primary" style="padding:11px 13px;border-radius:9px;background:var(--ink);color:#fff;text-decoration:none;font-weight:700">Baixar pacote geocodificado</a>`:''}</div>`}
async function cancelGeo(){if(!geoJobId)return;try{await json(api+'/geocoding/'+encodeURIComponent(geoJobId)+'/cancel',{method:'POST'});await pollGeo()}catch(e){$('geoReadiness').textContent=e.message}}
async function pollGeo(){if(!geoJobId)return;try{const j=await json(api+'/geocoding/'+encodeURIComponent(geoJobId)),active=['queued','uploading','running','cancelling'].includes(j.status);$('geoJob').hidden=false;$('geoJob').innerHTML=geoProgressHtml(j);if(active)setTimeout(pollGeo,2000);else{GeoUI.busy($('startGeo'),false);if(j.status==='completed')await loadPhase3()}}catch(e){$('geoReadiness').textContent=e.message;GeoUI.busy($('startGeo'),false)}}
$('refresh').onclick=load;$('competence').onchange=async()=>{await loadFiles();await restoreLatestDownload()};$('selectMin').onclick=selectRecommended;$('start').onclick=start;$('municipalityQuery').oninput=()=>{clearTimeout(municipalityTimer);municipalitySequence++;municipalityRows=[];municipalityChoice=null;hideMunicipalitySuggestions();updateProcessButton();municipalityTimer=setTimeout(searchMunicipality,180)};$('municipalityQuery').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();if(municipalityRows.length&&$('municipalitySuggestions').hidden===false){const first=municipalityRows[0];if(municipalityRows.filter(row=>row.name===first.name).length===1)chooseMunicipality(first);else $('municipalityHint').textContent='Este nome existe mais de uma vez. Escolha uma das opções.'}else searchMunicipality()}if(event.key==='Escape')hideMunicipalitySuggestions()};$('municipalityQuery').onblur=()=>setTimeout(hideMunicipalitySuggestions,120);$('processCompetence').onchange=showSelectedMonth;$('processUf').onchange=()=>{municipalityChoice=null;municipalitySequence++;$('municipalityQuery').value='';$('municipalityHint').textContent='Digite o município da UF escolhida.';hideMunicipalitySuggestions();updateProcessButton()};$('activeOnly').onchange=updateProcessButton;$('outputFormat').onchange=updateProcessButton;$('startProcess').onclick=startProcess;$('startGeo').onclick=startGeo;load();

document.getElementById('destinationRoot').addEventListener('input',updateDestinationPreview);
