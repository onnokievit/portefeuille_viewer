/* Editable view: move existing nodes, never duplicate data, editors or charts. */
(()=>{
  'use strict';
  const engine=DashboardLayoutEngine,config=window.dashboardLayoutConfig;
  const saved=engine.normalize(config.layout);
  let layout=engine.valid(saved)?saved:engine.defaults(config.mode);
  let editing=false,gesture=null,connection=null,pending=Promise.resolve({}),dirty=false,revision=0;
  const main=document.querySelector('main'),oldGrid=document.querySelector('main>.grid');
  const panelFor=id=>document.getElementById(id).closest('section');
  const market=[...oldGrid.children].filter(n=>n.tagName==='SECTION');
  const elements={payoff:panelFor('payoff-chart'),indicator:document.getElementById('indicator'),
    payoff_table:panelFor('payoff-table'),price:panelFor('price-chart'),result:panelFor('result-chart'),quantity:panelFor('quantity-chart'),
    puts:document.getElementById('puts-section'),calls:document.getElementById('calls-section'),holdings:document.getElementById('holdings-section'),
    test_orders:document.getElementById('test-orders-section'),market:market[0],earnings:market[1]};
  const positionIds=['puts','calls','holdings'];
  const labels={payoff:'Payoffgrafiek',indicator:'Assetindicator',payoff_table:'Payofftabel',price:'Dagkoers',result:'Totaalresultaat',quantity:'Aantallen',puts:'Posities · automatische hoogte',calls:'Calls',holdings:'Aandelen / sprinters',test_orders:'Testorders / scenario’s',market:'Marktbeeld',earnings:'Earnings'};
  const style=document.createElement('style');
  style.textContent=`
    .layout-toolbar{display:inline-flex;gap:6px;align-items:center;flex-wrap:nowrap;margin:0}
    .layout-toolbar button{padding:5px 9px}.layout-toolbar button.save-error{border-color:var(--red);color:var(--red)}
    .layout-canvas.dashboard-workspace{display:grid;grid-template-columns:repeat(240,minmax(0,1fr))!important;grid-template-areas:none!important;grid-template-rows:none!important;grid-auto-rows:2.7px;row-gap:0;column-gap:0;align-items:stretch;min-width:0;width:calc(100% + 7px)}
    .layout-item{position:relative;min-width:0;min-height:0;overflow:hidden;grid-area:auto;margin:0 7px 7px 0!important}
    .layout-body{height:100%;min-width:0;min-height:0;overflow:auto;display:flex;flex-direction:column}
    .layout-body>section{flex:1;min-height:0;max-height:none!important;margin:0!important;width:100%}
    .layout-body>.payoff-plot{height:100%}.layout-body>.payoff-plot .chart-box{height:auto;min-height:0;flex:1}
    .layout-item[data-block=indicator] .layout-body>#indicator{height:100%;min-height:0;max-height:none}
    .layout-item[data-block=payoff_table] .layout-body>section{display:flex;flex-direction:column}
    .layout-item #payoff-table{height:auto;min-height:0;max-height:none;flex:1}
    .layout-item[data-block=price] .layout-body>section,.layout-item[data-block=result] .layout-body>section,.layout-item[data-block=quantity] .layout-body>section{display:flex;flex-direction:column}
    .layout-item .chart-box{height:auto;min-height:0;flex:1;margin:0}
    .layout-item[data-block=test_orders] .layout-body{overflow:hidden}
    .layout-item[data-block=test_orders] #test-orders-section{display:flex;flex-direction:column;overflow:hidden}
    .layout-item[data-block=test_orders] #tests-table{flex:1;min-height:0;max-height:none;overflow:auto}
    .layout-item .positions-grid{height:auto}.layout-item .scroll{max-height:none}
    .layout-auto-stack{align-self:start;overflow:visible}
    .layout-auto-stack .layout-body{height:auto;overflow:visible;gap:7px}
    .layout-auto-stack .layout-body>.position-section{flex:none;height:auto;overflow:visible}
    .layout-auto-stack .position-section[hidden]{display:none!important}
    .layout-auto-stack .positions-grid{height:auto;min-height:0}
    .layout-auto-stack .scroll{height:auto;max-height:none;overflow-x:auto;overflow-y:hidden}
    .layout-editing .layout-auto-stack.layout-empty .layout-body{min-height:80px}
    .layout-auto-stack .layout-resize{cursor:ew-resize}
    .layout-handle,.layout-resize{display:none;touch-action:none}
    .layout-editing .layout-item{outline:1px dashed var(--control-border);border-radius:8px}
    .layout-editing .layout-handle{display:block;position:absolute;top:2px;left:4px;right:4px;height:24px;z-index:5;cursor:grab;text-align:left;padding:2px 6px;font-size:11px;background:var(--control-bg);border:1px solid var(--control-border)}
    .layout-editing .layout-body{padding-top:29px;pointer-events:none}
    .layout-editing .layout-resize{display:block;position:absolute;bottom:1px;right:1px;width:24px;height:24px;z-index:6;cursor:nwse-resize;padding:0;background:var(--control-bg)}
    .layout-editing .layout-auto-stack .layout-resize{cursor:ew-resize}
    .layout-dragging{outline:2px solid var(--focus)!important;z-index:8;opacity:.85}
    .layout-item[hidden]{display:none!important}.layout-item.layout-empty .layout-body>section{display:block!important}
    .layout-item.layout-empty .layout-body{opacity:.6}.layout-editing .layout-empty:after{content:'Geen posities voor deze asset';position:absolute;top:50px;left:12px;color:var(--muted);font-size:11px;pointer-events:none}
  `;
  document.head.append(style);
  const toolbar=document.createElement('div');toolbar.className='layout-toolbar';
  toolbar.dataset.mode=config.mode;
  toolbar.innerHTML='<button id="layout-edit" type="button">Indeling bewerken</button><button id="layout-reset" type="button" hidden>Standaard herstellen</button><span id="layout-state" class="sr-only" role="status"></span>';
  const header=document.querySelector('main>header');
  header.insertBefore(toolbar,header.querySelector('.spacer'));
  const grid=document.createElement('div');grid.className='layout-canvas dashboard-workspace';
  oldGrid.before(grid);
  const wrappers={};
  for(const id of engine.ids){
    if(id==='calls'||id==='holdings')continue;
    const element=elements[id];if(!element)throw new Error('Ontbrekend dashboardblok: '+id);
    const wrapper=document.createElement('div');wrapper.className='layout-item';wrapper.dataset.block=id;
    const body=document.createElement('div');body.className='layout-body';
    if(id==='puts'){wrapper.classList.add('layout-auto-stack');positionIds.forEach(key=>body.append(elements[key]));}
    else body.append(element);
    const handle=document.createElement('button');handle.type='button';handle.className='layout-handle';handle.textContent='⠿ '+labels[id];handle.title='Sleep om te verplaatsen · pijltjestoetsen om nauwkeurig te schuiven';
    const resize=document.createElement('button');resize.type='button';resize.className='layout-resize';resize.textContent='↘';resize.setAttribute('aria-label',labels[id]+' formaat wijzigen');resize.title=id==='puts'?'Breedte wijzigen · hoogte volgt de inhoud':'Sleep om te vergroten/verkleinen · pijltjestoetsen';
    wrapper.append(body,handle,resize);grid.append(wrapper);wrappers[id]=wrapper;
    handle.addEventListener('pointerdown',e=>start(e,id,'move'));
    resize.addEventListener('pointerdown',e=>start(e,id,'resize'));
    for(const [control,kind]of [[handle,'move'],[resize,'resize']])control.addEventListener('keydown',e=>{
      if(!editing||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();
      const block=layout.blocks.find(b=>b.id===id),patch={};
      const field=kind==='move'?(e.key==='ArrowLeft'||e.key==='ArrowRight'?'x':'y'):(e.key==='ArrowLeft'||e.key==='ArrowRight'?'w':'h');
      if(id==='puts'&&field==='h')return;
      patch[field]=block[field]+(['ArrowLeft','ArrowUp'].includes(e.key)?-1:1);
      try{layout=engine.place(layout,id,patch);apply();markDirty();}catch(error){status(String(error));}
    });
  }
  oldGrid.remove();
  const status=message=>{
    document.getElementById('layout-state').textContent=message;
    const button=document.getElementById('layout-edit');button.title=message;
    button.classList.toggle('save-error',message.startsWith('Niet opgeslagen'));
  };
  let framePending=false;
  function requestFlow(){
    if(framePending)return;framePending=true;
    requestAnimationFrame(()=>{framePending=false;apply();});
  }
  function apply(){
    grid.classList.toggle('layout-editing',editing);
    const anchor=layout.blocks.find(b=>b.id==='puts'),stack=wrappers.puts;
    stack.style.gridColumn=(anchor.x+1)+' / span '+anchor.w;
    const empty=positionIds.every(id=>elements[id].hidden);
    stack.hidden=empty&&!editing;stack.classList.toggle('layout-empty',empty);
    const height=stack.hidden?0:Math.ceil((stack.querySelector('.layout-body').getBoundingClientRect().height+7)/2.7);
    const display=engine.flowPositions(layout,height);
    for(const block of display.blocks){
      const wrapper=wrappers[block.id],element=elements[block.id];
      wrapper.style.gridColumn=(block.x+1)+' / span '+block.w;
      wrapper.style.gridRow=(block.y+1)+' / span '+block.h;
      if(block.id!=='puts'){
        wrapper.hidden=element.hidden&&!editing;
        wrapper.classList.toggle('layout-empty',element.hidden);
      }
    }
  }
  const observer=new MutationObserver(requestFlow);
  for(const element of Object.values(elements))observer.observe(element,{attributes:true,attributeFilter:['hidden']});
  for(const id of positionIds)observer.observe(elements[id],{childList:true,subtree:true,characterData:true});
  new ResizeObserver(requestFlow).observe(wrappers.puts.querySelector('.layout-body'));
  function start(event,id,kind){
    if(!editing||event.button!==0)return;event.preventDefault();
    const rect=grid.getBoundingClientRect();
    gesture={id,kind,startX:event.clientX,startY:event.clientY,startScrollY:scrollY,base:JSON.parse(JSON.stringify(layout)),block:{...layout.blocks.find(b=>b.id===id)},col:rect.width/engine.columns,control:event.currentTarget};
    gesture.control.setPointerCapture(event.pointerId);wrappers[id].classList.add('layout-dragging');
  }
  grid.addEventListener('pointermove',event=>{
    if(!gesture)return;
    const dx=Math.round((event.clientX-gesture.startX)/gesture.col),dy=Math.round((event.clientY-gesture.startY+scrollY-gesture.startScrollY)/2.7);
    const b=gesture.block,patch=gesture.kind==='move'?{x:b.x+dx,y:b.y+dy}:gesture.id==='puts'?{w:b.w+dx}:{w:b.w+dx,h:b.h+dy};
    try{layout=engine.place(gesture.base,gesture.id,patch);apply();}catch(error){status(String(error));}
    const edge=50;if(event.clientY>innerHeight-edge)window.scrollBy(0,20);else if(event.clientY<edge)window.scrollBy(0,-20);
  });
  function finish(cancel){
    if(!gesture)return;const previous=gesture;gesture=null;
    wrappers[previous.id].classList.remove('layout-dragging');
    if(cancel){layout=previous.base;apply();}else if(JSON.stringify(layout)!==JSON.stringify(previous.base))markDirty();
  }
  grid.addEventListener('pointerup',()=>finish(false));grid.addEventListener('pointercancel',()=>finish(true));
  grid.addEventListener('lostpointercapture',()=>finish(false));
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&gesture){e.preventDefault();finish(true);}});
  function markDirty(){dirty=true;revision++;status('Indeling bewaren…');save();}
  function save(){
    if(!connection||!dirty)return pending;
    const version=revision,raw=JSON.stringify(layout);dirty=false;
    pending=pending.then(()=>new Promise(resolve=>{
      connection.saveLayout(raw,error=>{
        if(error&&version===revision){dirty=true;status('Niet opgeslagen: '+error);}
        else if(version===revision)status('Indeling opgeslagen · '+config.mode);
        resolve({error:error||''});
      });
    }));return pending;
  }
  window.flushDashboardLayout=async()=>{finish(false);await pending;if(dirty)await save();return dirty?{error:'Dashboardindeling is niet opgeslagen'}:{};};
  window.layoutBridgeReady=value=>{connection=value;if(dirty)save();};
  if(typeof bridge!=='undefined'&&bridge)window.layoutBridgeReady(bridge);
  document.getElementById('layout-edit').addEventListener('click',()=>{
    finish(false);editing=!editing;apply();document.getElementById('layout-reset').hidden=!editing;document.getElementById('layout-edit').textContent=editing?'Klaar met indelen':'Indeling bewerken';
    status(editing?'Sleep de kopbalk · vergroot met ↘ · wijzigingen worden opgeslagen':'Indeling opgeslagen · '+config.mode);
  });
  document.getElementById('layout-reset').addEventListener('click',()=>{finish(true);layout=engine.defaults(config.mode);apply();markDirty();});
  apply();
})();
