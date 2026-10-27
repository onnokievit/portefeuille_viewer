/* Local canvas charts. No CDN, network requests or third-party runtime. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fmt = v => v == null ? '—' : Number(v).toLocaleString('nl-NL', {maximumFractionDigits: 2});
  const finite = v => typeof v === 'number' && Number.isFinite(v);
  let analytics = null, range = null;
  const charts = [];

  class Chart {
    constructor(id, kind) {
      this.canvas = $(id); this.kind = kind; this.hover = null; this.drag = null;
      this.tip = this.canvas.parentElement.querySelector('.tooltip');
      this.canvas.addEventListener('wheel', e => {
        if (kind === 'payoff' || !analytics?.history.length) return;
        e.preventDefault();
        const n = analytics.history.length, [a,b] = bounds(n), old = b-a;
        const size = Math.min(n, Math.max(Math.min(8,n), Math.round(old * (e.deltaY > 0 ? 1.2 : .8))));
        const rect = this.canvas.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (e.clientX-rect.left-65)/(rect.width-80)));
        const start = Math.max(0, Math.min(n-size, Math.round(a+(old-size)*ratio)));
        range = [start,start+size]; drawAll();
      }, {passive:false});
      this.canvas.addEventListener('pointerdown', e => {
        if (kind === 'payoff' || !analytics?.history.length) return;
        this.drag = {x:e.clientX, range:bounds(analytics.history.length)};
        this.canvas.setPointerCapture(e.pointerId);
      });
      this.canvas.addEventListener('pointerup', () => {this.drag=null;});
      this.canvas.addEventListener('pointercancel', () => {this.drag=null;});
      this.canvas.addEventListener('pointermove', e => {
        const rect=this.canvas.getBoundingClientRect();
        if (this.drag) {
          const [a,b]=this.drag.range, n=analytics.history.length;
          const dx=Math.round((this.drag.x-e.clientX)/(rect.width-80)*(b-a));
          const start=Math.max(0,Math.min(n-(b-a),a+dx));
          range=[start,start+b-a];drawAll();return;
        }
        this.hover={x:e.clientX-rect.left,y:e.clientY-rect.top};this.draw();
      });
      this.canvas.addEventListener('pointerleave',()=>{this.hover=null;this.tip.style.display='none';this.draw();});
      this.canvas.addEventListener('dblclick',()=>{range=null;drawAll();});
      new ResizeObserver(()=>this.draw()).observe(this.canvas);
    }

    draw() {
      const canvas=this.canvas, rect=canvas.getBoundingClientRect(), w=rect.width, h=rect.height;
      if (!w || !h) return;
      const dpr=window.devicePixelRatio||1;
      canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
      const c=canvas.getContext('2d');c.scale(dpr,dpr);
      // Keep only the space needed by the axes; the payoff panel has no outer header/footer.
      const left=65,right=w-(this.kind==='payoff'?8:16),top=this.kind==='payoff'?6:12,bottom=h-(this.kind==='payoff'?23:27);
      c.font='10px system-ui';c.fillStyle='#97acc7';
      const p=analytics?.payoff;
      let rows=this.kind==='payoff'?(p?.steps||[]).map((x,i)=>({x,i})):analytics?.history||[];
      if (this.kind!=='payoff') {const [a,b]=bounds(rows.length);rows=rows.slice(a,b);}
      if (!rows.length) {c.fillText('Geen gegevens beschikbaar',left,Math.max(30,h/2));return;}
      const series=this.kind==='payoff'?[9,2,'without']:this.kind==='price'?['close']:this.kind==='quantity'?['quantity']:['result'];
      const get=(r,key)=>this.kind==='payoff'?(key==='without'?p.values[9][r.i]-p.values[2][r.i]:p.values[key][r.i]):r[key];
      const values=[];
      for(const r of rows) {
        for(const key of series) {const v=get(r,key);if(finite(v))values.push(v);}
        if(this.kind==='price')for(const key of ['low','high','open'])if(finite(r[key]))values.push(r[key]);
      }
      if(!values.length){c.fillText('Geen gegevens beschikbaar',left,h/2);return;}
      let lo=Math.min(...values),hi=Math.max(...values),margin=(hi-lo||Math.abs(hi)*.02||1)*.08;
      lo-=margin;hi+=margin;
      const y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
      const x=i=>left+(rows.length===1?.5:i/(rows.length-1))*(right-left);
      c.textAlign='right';
      for(let i=0;i<4;i++){const v=lo+(hi-lo)*i/3,yy=y(v);c.strokeStyle='#28394e';c.beginPath();c.moveTo(left,yy);c.lineTo(right,yy);c.stroke();c.fillStyle='#97acc7';c.fillText(fmt(v),left-7,yy+3);}
      c.textAlign='center';
      for(let i=0;i<Math.min(5,rows.length);i++){
        const index=Math.round(i*(rows.length-1)/Math.max(1,Math.min(5,rows.length)-1));
        c.textAlign=i===0?'left':i===Math.min(5,rows.length)-1?'right':'center';
        c.fillStyle='#97acc7';c.fillText(this.kind==='payoff'?fmt(rows[index].x):rows[index].date,x(index),h-7);
      }
      c.save();c.beginPath();c.rect(left,top,right-left,bottom-top);c.clip();
      if(this.kind==='price') {
        const width=Math.max(1,Math.min(10,(right-left)/rows.length*.65));
        rows.forEach((r,i)=>{
          if(!finite(r.close))return;
          c.strokeStyle=c.fillStyle=finite(r.open)&&r.close<r.open?'#f394a3':'#74dfbb';
          if([r.open,r.high,r.low].every(finite)){
            c.beginPath();c.moveTo(x(i),y(r.high));c.lineTo(x(i),y(r.low));c.stroke();
            c.fillRect(x(i)-width/2,Math.min(y(r.open),y(r.close)),width,Math.max(1,Math.abs(y(r.close)-y(r.open))));
          }else{c.beginPath();c.arc(x(i),y(r.close),2.3,0,2*Math.PI);c.fill();}
        });
      } else {
        const colors=this.kind==='payoff'?['#74dfbb','#f394a3','#a7b6cd']:this.kind==='quantity'?['#7dabf3']:['#e8b96a'];
        series.forEach((key,si)=>{
          c.strokeStyle=colors[si];c.lineWidth=1.7;c.beginPath();let previous=null;
          rows.forEach((r,i)=>{const v=get(r,key);if(!finite(v)){previous=null;return;}
            if(previous===null)c.moveTo(x(i),y(v));
            else if(this.kind==='quantity'){c.lineTo(x(i),y(previous));c.lineTo(x(i),y(v));}
            else c.lineTo(x(i),y(v));previous=v;
          });c.stroke();
          if(rows.length===1&&finite(get(rows[0],key))){c.fillStyle=colors[si];c.beginPath();c.arc(x(0),y(get(rows[0],key)),2.5,0,7);c.fill();}
        });
      }
      if(this.kind==='payoff'&&finite(p.price)){
        const start=rows[0].x,end=rows[rows.length-1].x;
        const marker=left+(p.price-start)/(end-start||1)*(right-left);
        c.strokeStyle='#7998bd';c.setLineDash([4,4]);c.beginPath();c.moveTo(marker,top);c.lineTo(marker,bottom);c.stroke();c.setLineDash([]);
      }
      if(this.hover&&this.hover.x>=left&&this.hover.x<=right){
        const i=Math.max(0,Math.min(rows.length-1,Math.round((this.hover.x-left)/(right-left)*(rows.length-1))));
        const r=rows[i];c.strokeStyle='#91a9c8';c.beginPath();c.moveTo(x(i),top);c.lineTo(x(i),bottom);c.stroke();
        let text=this.kind==='payoff'?'Koers '+fmt(r.x)+'\nTotaal '+fmt(get(r,9))+' EUR\nOpen opties '+fmt(get(r,2))+' EUR':r.date;
        if(this.kind==='price')text+='\nO '+fmt(r.open)+' · H '+fmt(r.high)+'\nL '+fmt(r.low)+' · C '+fmt(r.close)+(r.live?'\nActuele snapshot':'');
        if(this.kind==='result')text+='\nResultaat '+fmt(r.result)+' EUR'+(r.live?' · actuele snapshot':'');
        if(this.kind==='quantity')text+='\nAantal '+fmt(r.quantity);
        this.tip.textContent=text;this.tip.style.display='block';this.tip.style.left=Math.max(0,Math.min(w-240,this.hover.x+10))+'px';this.tip.style.top='10px';
      }else this.tip.style.display='none';
      c.restore();
    }
  }
  function bounds(n){if(!range)return[0,n];const end=Math.min(n,range[1]);return[Math.max(0,Math.min(range[0],Math.max(0,end-1))),end];}
  function drawAll(){charts.forEach(chart=>chart.draw());}
  function payoffTable(p){
    const container=$('payoff-table');container.replaceChildren();if(!p?.steps)return;
    const table=document.createElement('table'),head=document.createElement('tr');
    const corner=document.createElement('th');corner.textContent='Eindkoers';head.append(corner);
    p.steps.forEach((step,i)=>{const th=document.createElement('th');th.textContent=fmt(step);if(i===p.current_col)th.className='current';head.append(th);});
    const thead=document.createElement('thead');thead.append(head);table.append(thead);const body=document.createElement('tbody');
    p.labels.forEach((label,r)=>{const tr=document.createElement('tr');if(r===9)tr.className='total';const th=document.createElement('th');th.textContent=label;tr.append(th);
      p.values[r].forEach((v,i)=>{const td=document.createElement('td');td.textContent=Number(v).toLocaleString('nl-NL',{maximumFractionDigits:0});if(v<0)td.classList.add('negative');if(i===p.current_col)td.classList.add('current');tr.append(td);});body.append(tr);});table.append(body);container.append(table);
  }
  window.clearAnalytics=asset=>{analytics={asset,payoff:{},history:[]};range=null;payoffTable({});$('payoff-status').textContent='Berekening laden…';$('history-status').textContent='Historie laden…';drawAll();};
  window.receiveAnalytics=raw=>{
    const next=JSON.parse(raw);if(next.asset!==current?.asset)return;
    if(next.error){$('payoff-status').textContent=next.error;$('history-status').textContent=next.error;return;}
    analytics=next;payoffTable(next.payoff);$('payoff-status').textContent=next.payoff.steps?'EUR · '+next.payoff.price_source:'Geen referentiekoers beschikbaar';
    $('history-status').textContent=next.history.length?next.history.length+' punten · '+next.history[0].date+' t/m '+next.history[next.history.length-1].date:'Geen historie beschikbaar binnen deze periode';drawAll();
  };
  document.addEventListener('DOMContentLoaded',()=>{
    for(const [id,kind]of [['payoff-chart','payoff'],['price-chart','price'],['quantity-chart','quantity'],['result-chart','result']])charts.push(new Chart(id,kind));
  });
})();
