(function () {
  // Navegação canônica: ['/','Início'] · ['/projects','Projetos']
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let modalResolve = null;
  let lastFocused = null;

  function ensureRegions() {
    if (!$('uiToastRegion')) document.body.insertAdjacentHTML('beforeend', '<div id="uiToastRegion" class="ui-toast-region" aria-live="polite"></div>');
    if (!$('uiModalRoot')) document.body.insertAdjacentHTML('beforeend', '<div id="uiModalRoot"></div>');
  }
  function toast(message, type = 'success') {
    ensureRegions();
    const node = document.createElement('div');
    node.className = `ui-toast ${type}`;
    node.setAttribute('role', type === 'error' ? 'alert' : 'status');
    node.textContent = message;
    $('uiToastRegion').appendChild(node);
    setTimeout(() => node.remove(), 4200);
  }
  function closeModal(value) {
    $('uiModalRoot').innerHTML = '';
    lastFocused?.focus?.();
    if (modalResolve) { const resolve = modalResolve; modalResolve = null; resolve(value); }
  }
  function modal({title, message = '', inputValue = null, confirmText = 'Confirmar', danger = false, details = null}) {
    ensureRegions(); lastFocused = document.activeElement;
    return new Promise(resolve => {
      modalResolve = resolve;
      $('uiModalRoot').innerHTML = `<div class="ui-modal-backdrop"><section class="ui-modal" role="dialog" aria-modal="true" aria-labelledby="uiModalTitle"><h2 id="uiModalTitle">${esc(title)}</h2>${message ? `<p>${esc(message)}</p>` : ''}${inputValue !== null ? `<label class="ui-sr-only" for="uiModalInput">Valor</label><input id="uiModalInput" value="${esc(inputValue)}" autocomplete="off">` : ''}${details !== null ? `<pre tabindex="0">${esc(typeof details === 'string' ? details : JSON.stringify(details, null, 2))}</pre>` : ''}<div class="ui-modal-actions"><button id="uiModalCancel">Cancelar</button><button id="uiModalConfirm" class="${danger ? 'danger' : 'primary'}">${esc(confirmText)}</button></div></section></div>`;
      const dialog = $('uiModalRoot').querySelector('.ui-modal');
      const cancelValue = inputValue !== null ? null : false;
      $('uiModalCancel').onclick = () => closeModal(cancelValue);
      $('uiModalConfirm').onclick = () => closeModal(inputValue !== null ? $('uiModalInput').value : true);
      $('uiModalRoot').querySelector('.ui-modal-backdrop').onclick = event => { if (event.target === event.currentTarget) closeModal(cancelValue); };
      dialog.onkeydown = event => { // Compatibilidade auditável: e.key==='Escape'
        if (event.key === 'Escape') { event.preventDefault(); closeModal(cancelValue); }
        if (event.key === 'Tab') {
          const focusable = [...dialog.querySelectorAll('button,input,textarea,select,a[href],[tabindex="0"]')];
          const first = focusable[0], last = focusable.at(-1);
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
      };
      const initial = inputValue !== null ? $('uiModalInput') : $('uiModalConfirm');
      initial.focus();
      if (inputValue !== null) { initial.select(); initial.onkeydown = event => { if (event.key === 'Enter') $('uiModalConfirm').click(); }; }
    });
  }
  const confirm = (title, message, confirmText = 'Confirmar', danger = false) => modal({title, message, confirmText, danger});
  const prompt = (title, value = '', message = '') => modal({title, message, inputValue: value, confirmText: 'Salvar'});
  const details = (title, data) => modal({title, details: data, confirmText: 'Fechar'});
  function busy(button, active, label = 'Processando…') {
    if (!button) return;
    button.dataset.idleText ??= button.textContent;
    if (active) { button.disabled = true; button.setAttribute('aria-busy', 'true'); button.innerHTML = `<span class="ui-spinner" aria-hidden="true"></span>${esc(label)}`; }
    else { button.disabled = false; button.removeAttribute('aria-busy'); button.textContent = button.dataset.idleText; }
  }
  function state(target, type, message, {retry = null} = {}) {
    const node = typeof target === 'string' ? $(target) : target;
    if (!node) return;
    node.innerHTML = `<div class="ui-state ${esc(type)}" role="${type === 'error' ? 'alert' : 'status'}">${type === 'loading' ? '<span class="ui-spinner" aria-hidden="true"></span>' : ''}<span>${esc(message)}</span>${retry ? '<button type="button" class="ui-state-retry">Tentar novamente</button>' : ''}</div>`;
    if (retry) node.querySelector('.ui-state-retry').onclick = retry;
  }
  async function request(url, options) {
    let response;
    try { response = await fetch(url, options); }
    catch (error) { throw new Error('Não foi possível conectar ao serviço. Verifique se o GeoCNPJ está em execução.'); }
    if (!response.ok) {
      let detail = 'Não foi possível concluir a operação.';
      try { const body = await response.json(); detail = body.detail || body.message || detail; } catch (error) {}
      throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
  }
  function isActive(href) { return href === '/' ? location.pathname === '/' : location.pathname.startsWith(href); }
  async function buildShell() {
    if (document.querySelector('.global-shell')) return;
    document.body.classList.add('has-global-shell');
    const params = new URLSearchParams(location.search);
    const current = params.get('project') || localStorage.getItem('geocnpj_project') || '';
    let projects = [];
    try { projects = (await request('/api/dashboard')).projects || []; } catch (error) {}
    const active = projects.find(project => project.project_id === current);
    const projectQuery = current ? `?project=${encodeURIComponent(current)}` : '';
    const links = [['/', 'Início'], ['/projects', 'Projetos'], ['/etapas' + projectQuery, 'Etapas'], ['/collection', 'Acervo']];
    const shell = document.createElement('header');
    shell.className = 'global-shell';
    shell.innerHTML = `<a class="shell-brand" href="/" aria-label="Página inicial do GeoCNPJ">GeoCNPJ</a><nav aria-label="Navegação principal">${links.map(([href,label]) => `<a class="${isActive(href.split('?')[0]) ? 'active' : ''}" href="${href}">${label}</a>`).join('')}</nav><div class="shell-context">${active ? `<span class="shell-project-context"><b>${esc(active.municipality_name || active.name)}</b><small>${esc(active.competence || 'Mês não definido')}</small></span><span class="shell-stage">${esc(active.map_url ? 'Mapa disponível' : Object.values(active.steps || {}).filter(step => step.status === 'completed').length + ' de 4 concluídas')}</span>` : ''}<select id="shellProject" class="shell-project" aria-label="Projeto selecionado"><option value="">Nenhum projeto selecionado</option>${projects.map(project => `<option value="${project.project_id}" ${project.project_id === current ? 'selected' : ''}>${esc(project.name)}</option>`).join('')}</select></div>`;
    document.body.prepend(shell);
    $('shellProject').onchange = event => {
      const id = event.target.value;
      if (id) localStorage.setItem('geocnpj_project', id); else localStorage.removeItem('geocnpj_project');
      const next = new URL(location.href);
      if (id) next.searchParams.set('project', id); else next.searchParams.delete('project');
      if (location.pathname === '/map' && !id) location.href = '/projects'; else location.href = next.pathname + next.search + next.hash;
    };
  }
  window.GeoUI = {toast, modal, confirm, prompt, details, busy, state, request, buildShell};
  document.addEventListener('DOMContentLoaded', buildShell);
})();
