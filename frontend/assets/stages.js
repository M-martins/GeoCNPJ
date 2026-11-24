(function () {
  window.GeoCanonicalStages = true;
  const escapeStage = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const order = ['data', 'preparation', 'geocoding', 'review'];
  const labels = {data:'Dados oficiais', preparation:'Base municipal', geocoding:'Geocodificação', review:'Mapa e revisão'};
  const statusLabels = {completed:'Concluída', available:'Disponível', pending:'Não iniciada', running:'Em andamento', queued:'Na fila', error:'Requer atenção', locked:'Bloqueada'};
  let project = null, localMonths = [], referencesComplete = false;
  function status(stage) {
    const value = project && project.steps && project.steps[stage] ? project.steps[stage].status : (stage === 'data' ? 'pending' : 'locked');
    if (stage === 'preparation' && project && ['pending','locked'].includes(value) && (project.steps?.data?.status === 'completed' || (referencesComplete && localMonths.some(month => Number(month.present) > 0)))) return 'available';
    if (stage === 'geocoding' && project?.steps?.preparation?.status === 'completed' && ['pending','locked'].includes(value)) return 'available';
    return value === 'pending' && order.indexOf(stage) > 0 ? 'locked' : value;
  }
  function current() {
    if (status('data') !== 'completed') return 'data';
    for (const stage of order.slice(1)) if (status(stage) === 'available') return stage;
    for (const stage of order) if (status(stage) !== 'completed') return stage;
    return 'review';
  }
  function show(stage, scroll) {
    if (status(stage) === 'locked') stage = current();
    document.querySelectorAll('.workflow-stage').forEach(node => { node.hidden = node.dataset.stage !== stage; });
    document.querySelectorAll('.stage-step').forEach(node => { node.classList.toggle('active', node.dataset.stage === stage); });
    if (scroll) document.getElementById('stageProgress').scrollIntoView({behavior:'smooth', block:'start'});
  }
  window.workflowOpen = function (stage, open) { if (open !== false) show(stage, true); };
  function render() {
    const host = document.getElementById('stageProgress');
    host.innerHTML = order.map(function (stage, index) {
      const state = status(stage), disabled = state === 'locked', marker = ['completed','available'].includes(state) ? '✓' : String(index + 1).padStart(2, '0');
      return '<button type="button" class="stage-step '+state+'" data-stage="'+stage+'" '+(disabled?'disabled':'')+'><span class="stage-marker">'+marker+'</span><span><small>ETAPA '+String(index+1).padStart(2,'0')+'</small><b>'+labels[stage]+'</b><em>'+statusLabels[state]+'</em></span></button>';
    }).join('');
    host.querySelectorAll('.stage-step:not(:disabled)').forEach(function (button) { button.onclick = function () { show(button.dataset.stage, true); }; });
    document.querySelectorAll('.workflow-stage').forEach(function (node) {
      const state = status(node.dataset.stage), badge = node.querySelector('.stage-status');
      badge.textContent = statusLabels[state]; badge.className = 'stage-status '+state;
    });
  }
  function overview(stage) {
    const host = document.getElementById('projectOverview');
    if (!project) { host.innerHTML = '<div><div class="kicker">PROJETO ATUAL</div><h2>Nenhum projeto selecionado</h2><p>Escolha ou crie um projeto para iniciar.</p></div><a class="overview-next" href="/projects">Abrir projetos</a>'; return; }
    const done = order.filter(function (item) { return status(item) === 'completed'; }).length;
    host.innerHTML = '<div class="overview-main"><div><div class="kicker">PROJETO ATUAL</div><h2>'+escapeStage(project.name)+'</h2><p>'+(project.municipality_name ? escapeStage(project.municipality_name)+'/'+escapeStage(project.uf) : 'Município ainda não definido')+' · '+escapeStage(project.competence || 'mês não definido')+'</p></div><div class="overview-progress"><b>'+done+' de 4 etapas</b><span>concluídas</span></div></div><div class="overview-metrics"><div><span>Etapa atual</span><b>'+labels[stage]+'</b></div><div><span>Registros</span><b>'+Number(project.rows||0).toLocaleString('pt-BR')+'</b></div><div><span>Tempo da base</span><b>'+(project.processing_seconds==null?'—':fmtElapsed(project.processing_seconds))+'</b></div><div><span>Resultado</span><b>'+(project.map_url?'Mapa disponível':'Em preparação')+'</b></div></div>';
    if (project.map_url) document.getElementById('reviewResult').innerHTML = '<article class="result-summary"><div><span class="ui-badge success">Etapa concluída</span><h3>'+escapeStage(project.municipality_name)+' — '+escapeStage(project.competence)+'</h3><p>'+Number((project.map_summary&&project.map_summary.mapped)||project.rows||0).toLocaleString('pt-BR')+' pontos disponíveis para consulta e revisão.</p></div><a class="primary-link" href="'+withProject(project.map_url)+'">Abrir mapa</a></article>';
  }
  function renderCoverage() {
    const coverage = project && project.coverage;
    if (!coverage || !coverage.is_partial) return;
    const text = `Cobertura parcial: ${coverage.parts_used} de ${coverage.parts_official} partes do mês foram usadas. Os registros, totais e o mapa podem estar incompletos.`;
    const warning = document.createElement('div');
    warning.className = 'coverage-warning';
    warning.textContent = text;
    document.getElementById('projectOverview').append(warning);
    const review = document.getElementById('reviewResult');
    if (review && project.map_url) {
      const reviewWarning = warning.cloneNode(true);
      review.prepend(reviewWarning);
    }
  }
  window.workflowRefresh = async function (preferredStage, scroll = true) {
    const [projectResult, readinessResult] = await Promise.allSettled([
      projectId ? GeoUI.request('/api/projects/'+projectId) : Promise.resolve(null),
      GeoUI.request('/api/process/readiness')
    ]);
    project = projectResult.status === 'fulfilled' ? projectResult.value : null;
    localMonths = readinessResult.status === 'fulfilled' ? readinessResult.value.competences || [] : [];
    referencesComplete = readinessResult.status === 'fulfilled' && readinessResult.value.references_complete === true;
    const stage = current(); render(); overview(stage); renderCoverage();
    show(preferredStage && status(preferredStage) !== 'locked' ? preferredStage : stage, scroll);
  };
  document.querySelectorAll('.workflow-stage').forEach(node => { node.hidden = node.dataset.stage !== 'data'; });
  document.addEventListener('DOMContentLoaded', () => window.workflowRefresh(new URLSearchParams(location.search).get('stage'), false));
})();
