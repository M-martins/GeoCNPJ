/* Read-only inventory with explicit controls for removing locally stored data. */
const inventoryEscape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[char]));
const inventorySize = value => {
  let size = Number(value) || 0;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit++; }
  return `${size.toLocaleString('pt-BR', { maximumFractionDigits: unit ? 1 : 0 })} ${units[unit]}`;
};

async function inventoryRequest(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Não foi possível concluir a operação.');
  return payload;
}

function inventoryDate(value) {
  if (!value) return 'Data não registrada';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Data não registrada' : date.toLocaleString('pt-BR');
}

function renderReferences(data) {
  const present = data.files.filter(file => file.present).length;
  document.getElementById('referenceSummary').textContent =
    `${present} de ${data.files.length} referências disponíveis · ${inventorySize(data.stored_size)} guardados em ${data.stored_file_count} arquivo(s), incluindo versões anteriores.`;
  document.getElementById('references').innerHTML = data.files.map(file => `
    <div class="inventory-row">
      <div class="inventory-main">
        <div class="inventory-title"><strong>${inventoryEscape(file.name)}</strong><span class="inventory-state ${file.present ? 'available' : 'missing'}">${file.present ? 'Disponível' : 'Não encontrada'}</span></div>
        <p>${inventoryEscape(file.description)}</p>
        <small>Fonte: ${file.name.endsWith('.xlsx') ? 'IBGE/Concla' : 'Receita Federal'} · ${file.source_competence ? `obtida durante o mês ${inventoryEscape(file.source_competence)}` : 'ainda não obtida'} · ${file.version_count} versão(ões) guardada(s) · ${inventorySize(file.size)}</small>
        ${file.present ? `<small>Registrada localmente em ${inventoryEscape(inventoryDate(file.updated_at))} · SHA-256 ${inventoryEscape((file.sha256 || '').slice(0, 12))}…</small>` : ''}
        ${file.path ? `<small class="inventory-path" title="${inventoryEscape(file.path)}">${inventoryEscape(file.path)}</small>` : ''}
      </div>
      <div class="inventory-controls">${file.present ? `<a class="btn outline" href="/api/library/references/${encodeURIComponent(file.name)}/download">Baixar cópia</a>` : ''}${file.present || file.version_count ? `<button type="button" class="btn outline danger-text" data-remove-reference="${inventoryEscape(file.name)}">Enviar versões à Lixeira</button>` : ''}</div>
    </div>`).join('');
  const cache = data.geocoding_cache;
  document.getElementById('cnaeHierarchy').innerHTML = `
    <div class="inventory-row distinct-source"><div class="inventory-main"><div class="inventory-title"><strong>Cache da geocodificação</strong><span class="inventory-state ${cache.file_count ? 'available' : 'missing'}">${cache.file_count ? 'No computador' : 'Vazio'}</span></div><p>Inclui tabelas CNEFE usadas pelo geocodebr e endereços já processados. As tabelas são obtidas pelo pacote do Ipea a partir de dados do IBGE, na primeira utilização.</p><small>${inventorySize(cache.size)} · ${cache.file_count} arquivo(s)</small><small class="inventory-path" title="${inventoryEscape(cache.path)}">${inventoryEscape(cache.path)}</small></div><div class="inventory-controls">${cache.file_count ? '<button type="button" class="btn outline danger-text" data-clear-cache>Limpar cache</button>' : ''}</div></div>`;
}

function renderCollectionMonths(overviewRows, library, readiness) {
  const filesByMonth = new Map((library || []).map(item => [item.competence, item]));
  const statusByMonth = new Map((readiness?.competences || []).map(item => [item.competence, item]));
  return overviewRows.length ? overviewRows.map(summary => {
    const month = filesByMonth.get(summary.competence) || summary;
    const coverage = statusByMonth.get(summary.competence) || {};
    const files = month.files || [];
    const present = coverage.present ?? files.length;
    const coverageText = coverage.expected ? `${present} de ${coverage.expected} partes oficiais no computador` : `${present} parte(s) no computador; total oficial ainda não conferido`;
    const missing = coverage.missing?.length ? `<p class="inventory-warning">Cobertura incompleta: ${coverage.missing.length} parte(s) ausente(s). Os resultados gerados com este mês podem ser parciais.</p>` : '';
    const rows = files.map(file => `
      <div class="inventory-file"><span><strong>${inventoryEscape(file.name)}</strong><small>${inventorySize(file.size)} · arquivo local</small></span><span class="inventory-controls">${file.removable ? `<a class="btn outline" href="/api/library/${encodeURIComponent(summary.competence)}/files/${encodeURIComponent(file.name)}/download">Baixar cópia</a>` : ''}${month.managed && file.removable ? `<button type="button" class="btn outline danger-text" data-remove-part="${inventoryEscape(summary.competence)}" data-file="${inventoryEscape(file.name)}">Enviar à Lixeira</button>` : ''}</span></div>`).join('');
    const usage = summary.project_count > 1 ? `<span class="badge shared">Compartilhado por ${summary.project_count} projetos</span>` : summary.project_count === 1 ? '<span class="badge">Em uso</span>' : '';
    const state = `<span class="badge ${summary.validated ? 'available' : 'pending'}">${summary.validated ? 'Validada' : 'Pendente'}</span>`;
    return `<details class="month-detail"><summary><span class="month-summary-main"><strong>${inventoryEscape(summary.competence)}</strong><small>${inventoryEscape(summary.path)} · ${coverageText} · ${month.managed ? 'Gerenciada pelo GeoCNPJ' : 'Pasta externa'}</small></span><span class="month-summary-meta"><span class="size">${inventorySize(summary.size)}</span>${usage}${state}<span class="month-expand">Ver arquivos ▾</span></span></summary><div class="month-body">${missing}${rows || '<p>Nenhum ZIP local nesta pasta.</p>'}<div class="month-actions"><button type="button" class="btn outline danger-text" data-remove-month="${inventoryEscape(summary.competence)}" data-managed="${month.managed ? 'true' : 'false'}">${month.managed ? 'Enviar pasta inteira à Lixeira' : 'Remover vínculo da pasta externa'}</button></div></div></details>`;
  }).join('') : '<div class="empty">Nenhum mês armazenado.</div>';
}

function renderInventoryIssue(row) {
  if (row.issue !== 'missing' || !['process', 'geocoding'].includes(row.kind)) return renderIntegrity(row);
  return `<div class="item"><span><b>${inventoryEscape(row.title)}</b><br><small>${inventoryEscape(row.detail)}<br>${inventoryEscape(row.path)}</small></span><span class="actions"><span class="badge pending">Pasta ausente</span><button type="button" class="btn outline danger-text" data-remove-artifact="${inventoryEscape(row.job_id)}" data-artifact-kind="${inventoryEscape(row.kind)}">Excluir registro</button><button type="button" class="btn outline" onclick="integrityAction(${jsArg(row.orphan_id)},'ignore')">Ignorar aviso</button></span></div>`;
}

function renderStoredProcess(process, size) {
  const available = Boolean(size.exists && size.file_count);
  const detail = `${Number(process.rows_found || 0).toLocaleString('pt-BR')} registros · ${inventoryEscape(process.output_file)}${process.is_partial ? ` · Base parcial: ${process.source_files?.length || 0}/${process.official_file_count || '?'} partes` : ''}`;
  return `<div class="item"><span><b>${inventoryEscape(process.municipality_name)}/${inventoryEscape(process.uf)} · ${inventoryEscape(process.competence)}</b><br><small>${detail}</small></span><span class="actions">${available ? `<span class="size">${inventorySize(size.size)}</span>${storageBadge(size)}${projectSelect(process)}` : '<span class="badge pending">Arquivo ausente</span>'}<button type="button" class="btn outline danger-text" data-remove-artifact="${inventoryEscape(process.job_id)}" data-artifact-kind="process">Excluir</button></span></div>`;
}

function renderStoredGeocoding(job, size) {
  const available = Boolean(size.exists && size.file_count);
  const detail = `${Number(job.map_summary?.mapped || 0).toLocaleString('pt-BR')} pontos · job ${inventoryEscape(job.job_id)}${job.is_partial ? ' · Origem parcial' : ''}`;
  return `<div class="item"><span><b>${inventoryEscape(job.municipality_name)} · ${inventoryEscape(job.competence)}</b><br><small>${detail}</small></span><span class="actions">${available ? `<span class="size">${inventorySize(size.size)}</span>${storageBadge(size)}${job.map_url ? `<a class="btn outline" href="${inventoryEscape(job.map_url)}">Abrir mapa</a>` : ''}<a class="btn" href="${inventoryEscape(job.download_url)}">Baixar pacote</a>` : '<span class="badge pending">Arquivo ausente</span>'}<button type="button" class="btn outline danger-text" data-remove-artifact="${inventoryEscape(job.job_id)}" data-artifact-kind="geocoding">Excluir</button></span></div>`;
}

async function refreshDownloadedInventory() {
  renderReferences(await inventoryRequest('/api/library/references'));
}

async function inventoryRemove(url, title, description, actionLabel, body = null) {
  if (!await GeoUI.confirm(title, description, actionLabel, true)) return;
  try {
    const result = await inventoryRequest(url, {
      method: 'POST',
      ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
    });
    GeoUI.toast(result.message || 'Acervo atualizado.');
    await refreshDownloadedInventory();
    await load();
  } catch (error) {
    GeoUI.toast(error.message, 'error');
  }
}

document.addEventListener('click', event => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.removeArtifact) {
    const kind = button.dataset.artifactKind, id = button.dataset.removeArtifact;
    inventoryRemove(`/api/collection/artifacts/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/remove`,
      'Excluir este resultado?', 'Se os arquivos ainda estiverem no computador, serão enviados à Lixeira. O registro também será removido do Acervo. Resultados vinculados a projetos ou usados por outros resultados precisam ser desvinculados primeiro.', 'Excluir resultado');
  } else if (button.dataset.removeReference) {
    const name = button.dataset.removeReference;
    inventoryRemove(`/api/library/references/${encodeURIComponent(name)}/remove`,
      `Excluir ${name}?`, 'Todas as cópias locais dessa referência serão enviadas à Lixeira. Para usá-la novamente, obtenha-a na etapa 1.', 'Enviar à Lixeira');
  } else if (button.hasAttribute('data-clear-cache')) {
    inventoryRemove('/api/library/cache/remove', 'Limpar cache da geocodificação?',
      'As tabelas CNEFE e os endereços em cache serão enviados à Lixeira. Uma próxima geocodificação poderá precisar baixá-los e processá-los de novo.', 'Limpar cache');
  } else if (button.dataset.removePart) {
    const month = button.dataset.removePart, file = button.dataset.file;
    inventoryRemove(`/api/library/${encodeURIComponent(month)}/files/${encodeURIComponent(file)}/remove`,
      `Excluir ${file}?`, `O arquivo do mês ${month} será enviado à Lixeira. A cobertura desse mês diminuirá; resultados já gerados permanecem no Acervo.`, 'Enviar à Lixeira');
  } else if (button.dataset.removeMonth) {
    const month = button.dataset.removeMonth, managed = button.dataset.managed === 'true';
    if (managed) {
      inventoryRemove(`/api/library/${encodeURIComponent(month)}/remove`, `Excluir o mês ${month}?`,
        'A pasta inteira desse mês, inclusive arquivos adicionais, será enviada à Lixeira. Bases e mapas já gerados continuam, mas podem deixar de ser reproduzíveis.', 'Enviar à Lixeira', { delete_files: true });
    } else {
      inventoryRemove(`/api/library/${encodeURIComponent(month)}/remove`, `Desvincular ${month}?`,
        'A pasta externa permanecerá no computador. Apenas o vínculo com o GeoCNPJ será removido.', 'Remover vínculo', { delete_files: false });
    }
  }
});

refreshDownloadedInventory().catch(error => {
  document.getElementById('references').innerHTML = `<div class="empty">${inventoryEscape(error.message)}</div>`;
});
