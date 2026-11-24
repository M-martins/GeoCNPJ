const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'..','frontend','assets','index.js'),'utf8');
const start=source.indexOf('function fmtElapsed('),end=source.indexOf('async function json(',start);
assert(start>=0&&end>start);
const context={};vm.createContext(context);vm.runInContext(source.slice(start,end),context);
assert.equal(context.fmtElapsed(94),'1 min 34 s');
assert.equal(context.fmtElapsed(3661),'1 h 1 min 1 s');
const old={created_at:'2026-11-22T08:40:21-03:00',updated_at:'2026-11-22T08:41:55-03:00'};
assert.equal(context.processSeconds(old),94);
assert.equal(context.processSeconds({...old,processing_seconds:82.5}),82.5);
console.log('Métrica de tempo e compatibilidade com jobs anteriores verificadas.');
