(function(){
  let active=null;
  function close(){
    if(!active)return;
    active.summary.setAttribute('aria-expanded','false');
    active.popover.remove();active=null;
  }
  function open(summary){
    const details=summary.closest('.tech-help');
    const message=details?.querySelector('div')?.textContent?.trim();
    if(!message)return;
    close();
    const popover=document.createElement('div');
    popover.className='help-popover';popover.setAttribute('role','tooltip');popover.textContent=message;
    document.body.append(popover);
    summary.setAttribute('aria-expanded','true');active={summary,popover};
    const rect=summary.getBoundingClientRect(),width=popover.offsetWidth,height=popover.offsetHeight;
    const left=Math.max(12,Math.min(innerWidth-width-12,rect.left+rect.width/2-width/2));
    let top=rect.bottom+8;
    if(top+height>innerHeight-12)top=rect.top-height-8;
    popover.style.left=left+'px';popover.style.top=Math.max(12,top)+'px';
  }
  document.addEventListener('click',event=>{
    const summary=event.target.closest('.tech-help summary');
    if(summary){event.preventDefault();active?.summary===summary?close():open(summary);return}
    if(!event.target.closest('.help-popover'))close();
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape')close()});
  window.addEventListener('resize',close);
  window.addEventListener('scroll',close,true);
})();
