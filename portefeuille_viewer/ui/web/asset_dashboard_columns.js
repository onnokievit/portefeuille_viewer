/* Shared option widths, separate stock/sprinter widths; no payoff resizing. */
(()=>{
  'use strict';
  const base=[4,8,5,4,9,6,6,6,6,7,7,7,5,8,13,6],sum=base.reduce((a,b)=>a+b,0);
  let state=window.dashboardPositionColumnConfig||{version:1,tables:{options:base.map(v=>v/sum),stocks:Array(5).fill(.2),sprinters:Array(9).fill(1/9)}};
  let gesture=null,dirty=false,pending=Promise.resolve({}),revision=0;
  const style=document.createElement('style');
  style.textContent=`table[data-position-columns]{table-layout:fixed;width:100%}
    table[data-position-columns] th{position:relative}
    table[data-position-columns] th,table[data-position-columns] td{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .position-column-grip{position:absolute;right:0;top:0;bottom:0;width:7px;cursor:col-resize;touch-action:none;z-index:3;outline:none}
    .position-column-grip:hover,.position-column-grip:focus{background:var(--control-border)}
    body.position-resizing,body.position-resizing *{cursor:col-resize!important;user-select:none!important}`;
  document.head.append(style);
  function apply(){
    for(const table of document.querySelectorAll('table[data-position-columns]')){
      const kind=table.dataset.positionColumns,weights=state.tables[kind];if(!weights||!table.tHead)continue;
      let group=table.querySelector('colgroup');
      if(!group){group=document.createElement('colgroup');weights.forEach(()=>group.append(document.createElement('col')));table.prepend(group);}
      [...group.children].forEach((col,i)=>col.style.width=(weights[i]*100)+'%');
      [...table.tHead.rows[0].cells].slice(0,-1).forEach((cell,index)=>{
        if(cell.querySelector('.position-column-grip'))return;
        const grip=document.createElement('span');grip.className='position-column-grip';grip.tabIndex=0;
        grip.setAttribute('role','separator');grip.setAttribute('aria-orientation','vertical');
        grip.setAttribute('aria-label','Kolom '+(index+1)+' breder of smaller maken');
        grip.title='Sleep voor kolombreedte · pijltjestoetsen · dubbelklik voor gelijke verdeling';
        const action=()=>({kind,index,width:table.getBoundingClientRect().width,base:JSON.parse(JSON.stringify(state)),wasDirty:dirty});
        grip.addEventListener('pointerdown',event=>{
          if(event.button!==0)return;event.preventDefault();event.stopPropagation();
          gesture={...action(),start:event.clientX};grip.setPointerCapture(event.pointerId);document.body.classList.add('position-resizing');
        });
        grip.addEventListener('pointermove',event=>{if(gesture)adjust(gesture,event.clientX-gesture.start);});
        grip.addEventListener('pointerup',()=>finish(false));grip.addEventListener('pointercancel',()=>finish(true));grip.addEventListener('lostpointercapture',()=>finish(false));
        grip.addEventListener('keydown',event=>{
          if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();event.stopPropagation();
          adjust(action(),event.key==='ArrowLeft'?-2:2);save();
        });
        grip.addEventListener('dblclick',event=>{
          event.preventDefault();event.stopPropagation();
          const values=state.tables[kind],pair=values[index]+values[index+1];values[index]=pair/2;values[index+1]=pair/2;
          dirty=true;apply();save();
        });cell.append(grip);
      });
    }
  }
  function adjust(action,delta){
    if(!action.width)return;
    state=JSON.parse(JSON.stringify(action.base));
    const values=state.tables[action.kind],index=action.index,pair=values[index]+values[index+1];
    const minimum=Math.min(24/action.width,pair/3),amount=Math.max(minimum,Math.min(pair-minimum,values[index]+delta/action.width));
    values[index]=amount;values[index+1]=pair-amount;dirty=true;apply();
  }
  function finish(cancel){
    if(!gesture)return;
    if(cancel){state=gesture.base;dirty=gesture.wasDirty;apply();}
    gesture=null;document.body.classList.remove('position-resizing');if(!cancel)save();
  }
  function save(){
    if(!dirty||typeof bridge==='undefined'||!bridge)return pending;
    dirty=false;const raw=JSON.stringify(state),sequence=++revision;
    pending=pending.then(()=>new Promise(resolve=>bridge.savePositionColumns(raw,error=>{
      if(error&&sequence===revision){dirty=true;document.getElementById('status').textContent='Kolombreedtes niet opgeslagen: '+error;}
      resolve({error:error||''});
    })));return pending;
  }
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&gesture){event.preventDefault();finish(true);}});
  window.updatePositionColumnWidths=apply;
  window.flushDashboardColumns=async()=>{finish(false);await pending;if(dirty)await save();return dirty?{error:'Kolombreedtes zijn niet opgeslagen'}:{};};
  apply();
})();
