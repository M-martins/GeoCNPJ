const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'assets', 'index.js'), 'utf8');
const start = source.indexOf('let municipalityChoice=null');
const end = source.indexOf('let reuseOptions=[]', start);
assert(start >= 0 && end > start);

function element() {
  return {hidden: true, value: '', textContent: '', children: [],
    setAttribute() {}, replaceChildren() { this.children = []; }, append(child) { this.children.push(child); }};
}
const elements = {municipalityQuery: element(), municipalitySuggestions: element(), municipalityHint: element(), processUf: element()};
elements.processUf.value = 'MG';
const context = {
  document: {createElement: element}, $: id => elements[id], updateProcessButton() { context.buttonUpdates++; },
  buttonUpdates: 0, api: '/api', json: async url => url.includes('nova')
    ? [{code:'0100',name:'NOVA UNIAO'},{code:'0200',name:'NOVA UNIAO'}]
    : [{code:'4177',name:'BRASOPOLIS'}]
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);

(async () => {
  elements.municipalityQuery.value = 'brasopolis';
  await context.searchMunicipality();
  assert.equal(elements.municipalityQuery.value, 'BRASOPOLIS');
  assert.match(elements.municipalityHint.textContent, /4177/);
  assert.equal(elements.municipalitySuggestions.hidden, true);
  elements.municipalityQuery.value = 'nova uniao';
  await context.searchMunicipality();
  assert.equal(elements.municipalityQuery.value, 'nova uniao');
  assert.equal(elements.municipalitySuggestions.hidden, false);
  assert.match(elements.municipalityHint.textContent, /mesmo nome/);
  assert.match(elements.municipalitySuggestions.children[0].textContent, /0100/);
  console.log('Busca automática e nomes repetidos verificados.');
})().catch(error => { console.error(error); process.exitCode = 1; });
