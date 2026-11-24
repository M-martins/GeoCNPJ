const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'..','frontend','assets','help.js'),'utf8');
const handlers={},windowHandlers={};let popover;
const details={querySelector:()=>({textContent:'Explicação técnica completa'})};
const summary={attrs:{},closest:()=>details,getBoundingClientRect:()=>({left:400,width:23,top:550,bottom:573}),setAttribute(name,value){this.attrs[name]=value}};
const context={innerWidth:800,innerHeight:600,window:{addEventListener(name,handler){windowHandlers[name]=handler}},document:{
  addEventListener(name,handler){handlers[name]=handler},body:{append(node){popover=node}},
  createElement(){return {style:{},offsetWidth:300,offsetHeight:70,setAttribute(){},remove(){this.removed=true}}}
}};
vm.createContext(context);vm.runInContext(source,context);
handlers.click({target:{closest:selector=>selector==='.tech-help summary'?summary:null},preventDefault(){}});
assert.equal(summary.attrs['aria-expanded'],'true');
assert.ok(parseInt(popover.style.top)<550,'dica deve subir quando faltar espaço abaixo');
handlers.click({target:{closest:()=>null}});
assert.equal(popover.removed,true);
assert.equal(summary.attrs['aria-expanded'],'false');
console.log('Dica reposicionada e fechamento fora verificados.');
