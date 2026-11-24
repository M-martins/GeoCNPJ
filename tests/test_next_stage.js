const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'assets', 'index.js'), 'utf8');
const start = source.indexOf('async function goToPreparation(){');
const end = source.indexOf('\nlet processMonthState=', start);
assert(start >= 0 && end > start);

function fixture(refresh) {
  const calls = [], errors = [];
  const data = {hidden: false};
  const preparation = {hidden: true, scrollIntoView() { calls.push('scroll'); }};
  const elements = {
    phase2: preparation,
    competence: {value: '2026-11'},
    processCompetence: {value: '', options: [{value: '2026-11'}]}
  };
  const context = {
    $: id => elements[id],
    document: {querySelectorAll: () => [data, preparation]},
    window: refresh ? {workflowRefresh: async stage => { calls.push(stage); await refresh(); }} : {},
    selectProjectMonth: async month => { calls.push(`month:${month}`); },
    loadProcessReadiness: async () => { calls.push('readiness'); },
    showSelectedMonth: async () => { calls.push('selected'); },
    GeoUI: {toast: message => errors.push(message)}
  };
  vm.createContext(context);
  vm.runInContext(source.slice(start, end), context);
  return {context, calls, errors, data, preparation, elements};
}

(async () => {
  const normal = fixture(async () => {});
  await normal.context.goToPreparation();
  assert.deepEqual(normal.calls, ['month:2026-11', 'readiness', 'selected', 'preparation']);
  assert.equal(normal.elements.processCompetence.value, '2026-11');
  assert.deepEqual(normal.errors, []);

  const fallback = fixture(null);
  await fallback.context.goToPreparation();
  assert.equal(fallback.data.hidden, true);
  assert.equal(fallback.preparation.hidden, false);
  assert(fallback.calls.includes('scroll'));

  const failed = fixture(async () => { throw new Error('Falha temporária'); });
  await failed.context.goToPreparation();
  assert.deepEqual(failed.errors, ['Falha temporária']);
  console.log('Próxima etapa seleciona o mês e abre a preparação.');
})().catch(error => { console.error(error); process.exitCode = 1; });
