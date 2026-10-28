/* Persistent view components. Asset changes commit with their analytics. */
'use strict';
let bridge=null, current=null, displayedAsset=null, optionKey=null;
const el=id=>document.getElementById(id);
const num=(value,decimals=2)=>value===null||value===undefined||value===''?'—':
  (Number.isFinite(Number(value))?Number(value).toLocaleString('nl-NL',{
    maximumFractionDigits:decimals,minimumFractionDigits:decimals}):String(value));
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function text(n,value){value=String(value);if(n.textContent!==value)n.textContent=value;}
function className(n,value){if(n.className!==value)n.className=value;}

const metricDefinitions=[['Koers','koers'],['Vorige koers','koers_prev'],['Dagverschil','pct_change',true],
  ['Net change','net_change'],['Pct lineair','portfolio_total_waarde_lineair_pct',true],['Pct delta','portfolio_total_waarde_delta_pct',true]];
const metricValues=metricDefinitions.map(([label])=>{
  const card=node('div',undefined,'metric'),value=node('b','—');
  card.append(node('small',label),value);el('metrics').append(card);return value;
});

function updateBadges(id,items,background,title=''){
  const container=el(id);
  while(container.children.length<items.length)container.append(node('span',undefined,'dividend-badge'));
  items.forEach((item,index)=>{
    const badge=container.children[index];text(badge,item);
    if(badge.dataset.background!==(background||'')){
      badge.dataset.background=background||'';
      badge.style.backgroundColor=background||'';
      badge.style.color=background?(background==='#FF0000'?'#fff':'#111'):'';
    }
    const tooltip=title||String(item);if(badge.title!==tooltip)badge.title=tooltip;
  });
}

const indicatorFields=[['asset_fase','fase'],['trend_phase','subtle'],['primary_action','action'],
  ['secondary_action','subtle'],['indicator_role','subtle']];
const scoreFields=[['Dir','direction_score'],['LT','long_term_direction_score'],['ST','short_term_direction_score'],
  ['Range','range_position_pct'],['Asset theta','theta_opportunity_proxy_score'],['Optie theta','theta_score'],
  ['IV/RV','iv_vs_realized_volatility_score'],['Q','data_quality']];
const indicatorLeft=node('div',undefined,'indicator-left');
const indicatorLabels=node('div',undefined,'indicator-labels');
const indicatorScores=node('div',undefined,'indicator-scores');
const indicatorReasons=node('div',undefined,'indicator-reasons');
const pills=indicatorFields.map(()=>{const pill=node('span','-');indicatorLabels.append(pill);return pill;});
const scores=scoreFields.map(([label])=>{
  const item=node('span'),value=node('b','-');item.append(document.createTextNode(label+' '),value);
  indicatorScores.append(item);return value;
});
const reasons=[0,1].map(()=>{const line=node('div','');indicatorReasons.append(line);return line;});
indicatorLeft.append(indicatorLabels,indicatorScores);
// One-time component construction, never on price updates or asset changes.
el('indicator').textContent='';el('indicator').append(indicatorLeft,indicatorReasons);
function updateIndicator(row,asset){
  indicatorFields.forEach(([field,kind],index)=>{
    text(pills[index],row[field]||'-');
    className(pills[index],'indicator-pill '+kind+(kind==='action'?' '+String(row[field]||'').replace(/[^a-zA-Z0-9_-]/g,'_'):''));
  });
  scoreFields.forEach(([,field],index)=>{
    const v=row[field];let value=v==null||v===''?'-':String(v);
    if(field!=='data_quality'&&v!=null&&v!==''&&Number.isFinite(Number(v)))value=Number(v).toFixed(1);
    text(scores[index],value);
  });
  [row.reason_1||(!Object.keys(row).length?(asset?'Geen asset indicator snapshot':'Selecteer een asset'):''),row.reason_2||'']
    .forEach((value,index)=>{text(reasons[index],value);if(reasons[index].title!==value)reasons[index].title=value;});
}

const tableStates=new Map();
const itmFields=new Set(['broker','asset_rollup','optie_call_put','optie_strike','optie_exp_date','afwijking_pct']);
let commentSequence=0;
function saveCommentCell(cell){
  const draft=cell.textContent||'';
  if(cell.dataset.pendingRequest&&cell.dataset.pendingText===draft)return cell._savePromise;
  if(!cell.dataset.pendingRequest&&draft===(cell.dataset.savedText||''))return Promise.resolve({});
  const request=String(++commentSequence);
  cell.dataset.pendingRequest=request;cell.dataset.pendingText=draft;delete cell.dataset.saveError;
  cell._savePromise=new Promise(resolve=>{
    if(!bridge){resolve({error:'Geen verbinding met commentaaropslag'});return;}
    bridge.saveComment(cell.dataset.commentId,draft,request,raw=>{
      const result=JSON.parse(raw);commentResult(raw);resolve(result);
    });
  });
  return cell._savePromise;
}
function updateCommentCell(cell,row){
  const meta=row._comment;
  if(!cell.dataset.commentId){
    cell.contentEditable='plaintext-only';cell.classList.add('comment-editable');cell.spellcheck=false;
    cell.setAttribute('aria-label','Optiecommentaar');
    cell.addEventListener('blur',()=>saveCommentCell(cell));
    cell.addEventListener('keydown',event=>{
      if(event.key==='Enter'){event.preventDefault();cell.blur();}
      else if(event.key==='Escape'){
        event.preventDefault();text(cell,cell.dataset.savedText||'');delete cell.dataset.saveError;cell.blur();
      }
    });
    cell.addEventListener('contextmenu',event=>{
      event.preventDefault();cell.blur();
      saveCommentCell(cell).then(result=>{if(!result.error&&bridge)bridge.chooseCommentColor(cell.dataset.commentId);});
    });
  }
  cell.dataset.commentId=meta.id;
  if(!cell.dataset.pendingRequest){
    cell.dataset.savedText=row.optie_comment||'';
    if(document.activeElement!==cell&&!cell.dataset.saveError)text(cell,cell.dataset.savedText);
  }
  const colour=meta.background||'',foreground=colour?(meta.foreground||'#000000'):'';
  if(cell.dataset.commentBackground!==colour){cell.dataset.commentBackground=colour;cell.style.backgroundColor=colour;}
  if(cell.style.color!==foreground)cell.style.color=foreground;
  if(!cell.dataset.saveError)cell.title='Enter: bewaren · Escape: annuleren · Rechtsklik: kleur kiezen';
}
function commentResult(raw){
  const result=JSON.parse(raw);
  for(const cell of document.querySelectorAll('[data-comment-id]')){
    if(cell.dataset.commentId!==result.id)continue;
    if(result.operation==='text'&&cell.dataset.pendingRequest!==result.request)continue;
    if(result.operation==='text'){delete cell.dataset.pendingRequest;delete cell.dataset.pendingText;}
    if(result.error){
      cell.dataset.saveError='true';cell.title='Niet bewaard: '+result.error;text(el('status'),cell.title);continue;
    }
    delete cell.dataset.saveError;cell.dataset.savedText=result.text;
    if(document.activeElement!==cell&&!cell.dataset.pendingRequest)text(cell,result.text);
    cell.dataset.commentBackground=result.background||'';
    cell.style.backgroundColor=result.background||'';
    cell.style.color=result.background?(result.foreground||'#000000'):'';
    cell.title='Enter: bewaren · Escape: annuleren · Rechtsklik: kleur kiezen';
  }
}
async function flushDashboardComments(){
  try{
    const settingsResult=await submitDashboardControls();
    const results=[settingsResult,...await Promise.all([...document.querySelectorAll('[data-comment-id]')].map(saveCommentCell))];
    bridge.commentsFlushed(results.map(result=>result.error).filter(Boolean).join('\n'));
  }catch(error){bridge.commentsFlushed(String(error));}
}
function updateTable(id,rows,columns){
  let state=tableStates.get(id);
  if(!state){
    const wrap=node('div',undefined,'scroll'),table=node('table'),head=node('tr'),thead=node('thead'),body=node('tbody');
    thead.append(head);table.append(thead,body);wrap.append(table);el(id).append(wrap);
    state={head,body,rows:new Map()};tableStates.set(id,state);
  }
  while(state.head.children.length<columns.length)state.head.append(node('th'));
  columns.forEach(([label],i)=>text(state.head.children[i],label));
  const retained=new Set(),duplicates=new Map();
  rows.forEach((row,index)=>{
    const base=JSON.stringify([row.broker,row.asset_rollup,row.asset_detail,row.optie_call_put,row.optie_exp_date,row.optie_strike]);
    const ordinal=duplicates.get(base)||0;duplicates.set(base,ordinal+1);const key=base+':'+ordinal;retained.add(key);
    let tr=state.rows.get(key);
    if(!tr){tr=node('tr');columns.forEach(()=>tr.append(node('td')));state.rows.set(key,tr);}
    const itm=Number(row.itm_otm),cp=String(row.optie_call_put||'').toLowerCase();
    columns.forEach(([,field,kind],i)=>{
      if(field==='optie_comment'&&row._comment?.id){updateCommentCell(tr.children[i],row);return;}
      let value=row[field];
      if(kind==='number')value=num(value,['koers','Koers','optie_strike'].includes(field)?(current.payoff_controls?.decimals??2):2);
      else if(kind==='percent')value=value==null?'—':num(value)+'%';
      else if(kind==='date'&&value){const parts=String(value).slice(0,10).split('-');value=parts.length===3?parts.reverse().join('-'):value;}
      else if(value==null||value==='')value='—';
      const cell=tr.children[i];text(cell,value);
      let colour='';
      if(row.itm_otm!=null&&Number.isFinite(itm)&&itm!==0&&itmFields.has(field)){
        if(cp==='put'||cp==='p')colour='rgb(255, 200, 200)';
        else if(cp==='call'||cp==='c')colour='rgb(200, 255, 200)';
      }
      if(cell.style.backgroundColor!==colour){cell.style.backgroundColor=colour;cell.style.color=colour?'#111':'';}
    });
    if(state.body.children[index]!==tr)state.body.insertBefore(tr,state.body.children[index]||null);
  });
  for(const [key,row]of state.rows)if(!retained.has(key)){row.remove();state.rows.delete(key);}
}

const positionGroups=[['options','put','put-positions'],['options','call','call-positions'],
  ['stocks',null,'holding-positions'],['sprinters',null,'holding-positions']].map(([key,side,container],i)=>{
    const group=node('div',undefined,'group '+(key==='options'?'option-group':''));
    group.id='position-group-'+i;el(container).append(group);return{key,side,container,group};
  });
function updatePositions(payload){
  for(const {key,side,group}of positionGroups){
    const source=key==='options'?payload.positions[key].map((row,i)=>({...row,_comment:payload.option_comments[i]})):payload.positions[key];
    const rows=source.filter(row=>!side||String(row.optie_call_put).toLowerCase()===side||
      String(row.optie_call_put).toLowerCase()===(side==='call'?'c':'p'));
    updateTable(group.id,rows,payload.position_columns[key]);group.hidden=!rows.length;
  }
  for(const [section,container]of [['puts-section','put-positions'],['calls-section','call-positions'],['holdings-section','holding-positions']]){
    el(section).hidden=![...el(container).children].some(group=>!group.hidden);
  }
  const holdings=[...el('holding-positions').children].filter(group=>!group.hidden);
  holdings.forEach(group=>{group.style.gridColumn=holdings.length===1?'1 / -1':'';});
}

function assetOptions(){
  const select=el('asset'),key=JSON.stringify(current.assets);
  if(key!==optionKey){
    const old=new Map([...select.options].map(option=>[option.value,option]));
    current.assets.forEach((asset,index)=>{
      const option=old.get(asset)||node('option',asset);option.value=asset;old.delete(asset);
      if(select.options[index]!==option)select.insertBefore(option,select.options[index]||null);
    });
    old.forEach(option=>option.remove());optionKey=key;
  }
  if(select.value!==current.asset)select.value=current.asset;
}
function applyDashboard(payload){
  const scrollX=window.scrollX,scrollY=window.scrollY;
  updatePayoffControls(payload.payoff_controls);
  metricDefinitions.forEach(([,key,pct],index)=>{
    const value=payload.summary[key];text(metricValues[index],num(value,['koers','koers_prev'].includes(key)?payload.payoff_controls.decimals:2)+(pct&&value!=null?'%':''));
    className(metricValues[index],['pct_change','net_change'].includes(key)&&value!=null?(value>0?'positive':value<0?'negative':''):'');
  });
  updateIndicator(payload.indicator,payload.asset);
  const dividend=payload.dividend_display,earnings=payload.earnings_display;
  updateBadges('dividend',['Dividend',dividend.date,num(dividend.amount)+(dividend.currency?' '+dividend.currency:'')],dividend.background);
  updateBadges('earnings',['Earnings',earnings.date],earnings.background,earnings.source?'Geplande earnings volgens '+earnings.source:'Geen komende earningsdatum beschikbaar');
  updatePositions(payload);displayedAsset=payload.asset;
  document.querySelector('.dashboard-workspace').setAttribute('aria-busy','false');
  for(const input of payoffInputs)input.disabled=false;
  document.querySelectorAll('[data-spin]').forEach(button=>button.disabled=false);
  text(el('status'),'Snapshot ontvangen '+new Date().toLocaleTimeString('nl-NL')+(Object.keys(payload.summary).length?'':' · Kerncijfers nog niet beschikbaar'));
  // Section visibility still follows available holdings; do not let browser scroll anchoring jump to another block.
  if(window.scrollX!==scrollX||window.scrollY!==scrollY)window.scrollTo(scrollX,scrollY);
}
function commitDashboard(asset){
  if(current?.asset===asset)applyDashboard(current);
}
function render(payload){
  current=JSON.parse(payload);assetOptions();el('asset-status').value=current.asset_status||'all';
  if(displayedAsset!==null&&current.asset&&current.asset!==displayedAsset){
    // Keep the stable view while the worker computes. Commit all blocks together.
    document.querySelector('.dashboard-workspace').setAttribute('aria-busy','true');
    for(const input of payoffInputs)input.disabled=true;
    document.querySelectorAll('[data-spin]').forEach(button=>button.disabled=true);
    text(el('payoff-status'),'Laden…');return;
  }
  applyDashboard(current);
  if(!current.asset)clearAnalytics('');
}

let themeSequence=0;
const themeSelector=el('dashboard-theme');
themeSelector.value=document.documentElement.dataset.theme==='sand'?'sand':'dark';
function applyDashboardTheme(value){
  document.documentElement.dataset.theme=value;themeSelector.value=value;
  window.dispatchEvent(new Event('dashboard-theme-changed'));
}
themeSelector.addEventListener('change',()=>{
  const previous=document.documentElement.dataset.theme,value=themeSelector.value,sequence=++themeSequence;
  applyDashboardTheme(value);
  if(bridge)bridge.setTheme(value,error=>{
    if(error&&sequence===themeSequence){applyDashboardTheme(previous);text(el('status'),error);}
  });
});
const payoffInputs=['step','step-tick','shift','decimals'].map(el);
const controlFields={step:'step_pct','step-tick':'step_tick',shift:'shift',decimals:'decimals'};
let pendingConfiguration=null;
let savedPeriod=[el('start').value,el('end').value];
function updatePayoffControls(cfg){
  for(const input of payoffInputs){
    const value=cfg[controlFields[input.id]];input.dataset.savedValue=String(value);
    if(document.activeElement!==input)input.value=input.id==='decimals'?String(value):Number(value).toFixed(2);
  }
}
function submitDashboardControls(changed='controls'){
  const values={asset:displayedAsset,changed,start:el('start').value,end:el('end').value};
  payoffInputs.forEach(input=>{values[controlFields[input.id]]=Number(input.value);});
  const periodChanged=values.start!==savedPeriod[0]||values.end!==savedPeriod[1];
  const controlsChanged=payoffInputs.some(input=>Number(input.value)!==Number(input.dataset.savedValue));
  if(!periodChanged&&!controlsChanged)return Promise.resolve({});
  const key=JSON.stringify(values);
  if(pendingConfiguration?.key===key)return pendingConfiguration.promise;
  const promise=new Promise(resolve=>{
    if(!bridge){resolve({error:'Geen verbinding met de instellingen'});return;}
    bridge.configure(key,error=>{
      if(error){text(el('payoff-status'),error);text(el('status'),error);}
      else savedPeriod=[values.start,values.end];
      resolve({error:error||''});
    });
  });
  pendingConfiguration={key,promise};promise.then(()=>{if(pendingConfiguration?.key===key)pendingConfiguration=null;});
  return promise;
}
function nudgePayoffControl(id,direction){
  const input=el(id);if(input.disabled)return;
  const increment=id==='step'?Number(el('step-tick').value):id==='step-tick'?.05:id==='shift'?.1:1;
  const decimals=id==='decimals'?0:2;
  input.value=Math.min(Number(input.max),Math.max(Number(input.min),Number(input.value)+direction*increment)).toFixed(decimals);
  submitDashboardControls(id);
}
document.querySelectorAll('[data-spin]').forEach(button=>button.addEventListener('click',()=>nudgePayoffControl(button.dataset.spin,Number(button.dataset.direction))));
for(const input of payoffInputs){
  input.addEventListener('change',()=>submitDashboardControls(input.id));
  input.addEventListener('keydown',event=>{
    if(event.key==='ArrowUp'||event.key==='ArrowDown'){event.preventDefault();nudgePayoffControl(input.id,event.key==='ArrowUp'?1:-1);}
    else if(event.key==='Enter'){event.preventDefault();submitDashboardControls(input.id);input.blur();}
  });
}
for(const id of ['start','end'])el(id).addEventListener('change',()=>submitDashboardControls(id));
el('asset-status').addEventListener('change',()=>{if(bridge)bridge.selectStatus(el('asset-status').value);});
el('asset').addEventListener('change',()=>{if(bridge)bridge.selectAsset(el('asset').value);});
if(window.qt&&window.QWebChannel){new QWebChannel(qt.webChannelTransport,channel=>{
  bridge=channel.objects.dashboard;bridge.updated.connect(render);bridge.analyticsUpdated.connect(receiveAnalytics);bridge.ready();
  bridge.commentResult.connect(commentResult);
});}else{text(el('status'),'Open deze pagina via de Asset Dashboard-tab in Portefeuille Viewer.');}
