/* Local canvas charts. No CDN, network requests or third-party runtime. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fmt = v => v == null ? 'â€”' : Number(v).toLocaleString('nl-NL', {maximumFractionDigits: 2});
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
      const theme=getComputedStyle(document.documentElement);
      const colour=name=>theme.getPropertyValue('--chart-'+name).trim();
      const palette={axis:colour('axis'),grid:colour('grid'),green:colour('green'),red:colour('red'),neutral:colour('neutral'),quantity:colour('quantity'),result:colour('result'),marker:colour('marker'),crosshair:colour('crosshair')};
      const dpr=window.devicePixelRatio||1;
      const pixelWidth=Math.round(w*dpr),pixelHeight=Math.round(h*dpr);
      if(canvas.width!==pixelWidth)canvas.width=pixelWidth;
      if(canvas.height!==pixelHeight)canvas.height=pixelHeight;
      const c=canvas.getContext('2d');c.setTransform(1,0,0,1,0,0);c.clearRect(0,0,canvas.width,canvas.height);c.setTransform(dpr,0,0,dpr,0,0);
      // Keep only the space needed by the axes; the payoff panel has no outer header/footer.
      const distribution=this.kind==='payoff'?analytics?.payoff?.distribution:null;
      const left=65,right=w-(this.kind==='payoff'?(distribution?55:8):16),top=this.kind==='payoff'?6:12,bottom=h-(this.kind==='payoff'?23:27);
      c.font='10px system-ui';c.fillStyle=palette.axis;
      const p=analytics?.payoff;
      const priceText=v=>finite(v)?v.toLocaleString('nl-NL',{minimumFractionDigits:p?.decimals??current?.payoff_controls?.decimals??2,maximumFractionDigits:p?.decimals??current?.payoff_controls?.decimals??2}):'â€”';
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
      let lo=Math.min(...values),hi=Math.max(...values),ticks,axisStep;
      if(this.kind==='payoff'){
        const axis=DashboardAxes.payoff(lo,hi,bottom-top);lo=axis.min;hi=axis.max;ticks=axis.ticks;axisStep=axis.step;
      }else{
        const axis=DashboardAxes.scale(lo,hi,this.kind);lo=axis.min;hi=axis.max;ticks=axis.ticks;axisStep=axis.step;
      }
      const y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
      const first=rows[0].x,last=rows[rows.length-1].x,span=(last-first)||1;
      const priceX=value=>left+(value-first+span*.02)/(span*1.04)*(right-left);
      const x=i=>this.kind==='payoff'?priceX(rows[i].x):left+(rows.length===1?.5:i/(rows.length-1))*(right-left);
      c.textAlign='right';
      for(const v of ticks){
        const yy=y(v),zero=v===0;
        c.lineWidth=this.kind==='payoff'?(zero?1:.5):zero?1.25:.5;
        c.strokeStyle=zero?(this.kind==='payoff'?colour('payoff-zero'):palette.marker):palette.grid;c.beginPath();c.moveTo(left,yy);c.lineTo(right,yy);c.stroke();
        c.fillStyle=palette.axis;c.fillText(DashboardAxes.format(v,axisStep),left-7,yy+3);
      }
      c.lineWidth=1;
      c.textAlign='center';
      if(this.kind==='payoff'){
        const axis=DashboardAxes.ticksWithin(first-span*.02,last+span*.02);
        for(const value of axis.ticks)c.fillText(DashboardAxes.format(value,axis.step),priceX(value),h-7);
      }else for(let i=0;i<Math.min(5,rows.length);i++){
        const index=Math.round(i*(rows.length-1)/Math.max(1,Math.min(5,rows.length)-1));
        c.textAlign=i===0?'left':i===Math.min(5,rows.length)-1?'right':'center';
        c.fillStyle=palette.axis;c.fillText(this.kind==='payoff'?Number(rows[index].x).toLocaleString('nl-NL',{minimumFractionDigits:p.decimals??2,maximumFractionDigits:p.decimals??2}):rows[index].date,x(index),h-7);
      }
      if(distribution){
        const axis=DashboardAxes.ticksWithin(0,distribution.maximum);
        c.textAlign='left';
        for(const value of axis.ticks)c.fillText(DashboardAxes.format(value,axis.step),right+5,bottom-value/distribution.maximum*(bottom-top)+3);
        c.save();c.translate(w-6,(top+bottom)/2);c.rotate(-Math.PI/2);c.textAlign='center';c.fillText('Verdeling %',0,0);c.restore();
      }
      c.save();c.beginPath();c.rect(left,top,right-left,bottom-top);c.clip();
      if(distribution){
        const dy=value=>bottom-value/distribution.maximum*(bottom-top);
        const width=distribution.width*.92/(span*1.04)*(right-left);
        for(const [period,fill,stroke] of [['24','rgba(120,190,255,.5)','rgba(120,190,255,.5)'],['12','rgba(181,75,216,.33)','rgba(181,75,216,.51)']]){
          c.fillStyle=fill;c.strokeStyle=stroke;c.lineWidth=.6;
          distribution.centers.forEach((value,i)=>{const height=bottom-dy(distribution.series[period][i]);c.fillRect(priceX(value)-width/2,bottom-height,width,height);c.strokeRect(priceX(value)-width/2,bottom-height,width,height);});
        }
        for(const [period,color] of [['6','#f08c2e'],['3','#4f7cf7']]){
          c.strokeStyle=color;c.lineWidth=1.2;c.setLineDash([5,3]);c.beginPath();
          distribution.centers.forEach((value,i)=>{const xx=priceX(value),yy=dy(distribution.series[period][i]);if(i)c.lineTo(xx,yy);else c.moveTo(xx,yy);});c.stroke();
        }
        c.setLineDash([]);
      }
      if(this.kind==='price') {
        const width=Math.max(1,Math.min(10,(right-left)/rows.length*.65));
        rows.forEach((r,i)=>{
          if(!finite(r.close))return;
          c.strokeStyle=c.fillStyle=finite(r.open)&&r.close<r.open?palette.red:palette.green;
          if([r.open,r.high,r.low].every(finite)){
            c.beginPath();c.moveTo(x(i),y(r.high));c.lineTo(x(i),y(r.low));c.stroke();
            c.fillRect(x(i)-width/2,Math.min(y(r.open),y(r.close)),width,Math.max(1,Math.abs(y(r.close)-y(r.open))));
          }else{c.beginPath();c.arc(x(i),y(r.close),2.3,0,2*Math.PI);c.fill();}
        });
      } else {
        const colors=this.kind==='payoff'?[palette.green,palette.red,palette.neutral]:this.kind==='quantity'?[palette.quantity]:[palette.result];
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
        const marker=priceX(p.price);
        c.strokeStyle=palette.marker;c.setLineDash([4,4]);c.beginPath();c.moveTo(marker,top);c.lineTo(marker,bottom);c.stroke();c.setLineDash([]);
      }
      if(this.hover&&this.hover.x>=left&&this.hover.x<=right){
        const i=Math.max(0,Math.min(rows.length-1,Math.round(((this.hover.x-left)/(right-left)*(this.kind==='payoff'?1.04:1)-(this.kind==='payoff'?.02:0))*(rows.length-1))));
        const r=rows[i];c.strokeStyle=palette.crosshair;c.beginPath();c.moveTo(x(i),top);c.lineTo(x(i),bottom);c.stroke();
        let text=this.kind==='payoff'?'Koers '+Number(r.x).toLocaleString('nl-NL',{minimumFractionDigits:p.decimals??2,maximumFractionDigits:p.decimals??2})+'\nTotaal '+fmt(get(r,9))+' EUR\nOpen opties '+fmt(get(r,2))+' EUR':r.date;
        if(this.kind==='price')text+='\nO '+priceText(r.open)+' Â· H '+priceText(r.high)+'\nL '+priceText(r.low)+' Â· C '+priceText(r.close)+(r.live?'\nActuele snapshot':'');
        if(this.kind==='result')text+='\nResultaat '+fmt(r.result)+' EUR'+(r.live?' Â· actuele snapshot':'');
        if(this.kind==='quantity')text+='\nAantal '+fmt(r.quantity);
        this.tip.textContent=text;this.tip.style.display='block';this.tip.style.left=Math.max(0,Math.min(w-240,this.hover.x+10))+'px';this.tip.style.top='10px';
      }else this.tip.style.display='none';
      c.restore();
    }
  }
  function bounds(n){if(!range)return[0,n];const end=Math.min(n,range[1]);return[Math.max(0,Math.min(range[0],Math.max(0,end-1))),end];}
  function drawAll(){charts.forEach(chart=>chart.draw());}
  function payoffTable(p){
    const container=$('payoff-table');let table=container.querySelector('table');
    if(!table){
      table=document.createElement('table');const thead=document.createElement('thead'),head=document.createElement('tr'),body=document.createElement('tbody');
      thead.append(head);table.append(thead,body);container.append(table);
    }
    const labels=p?.labels||['Open aandelen','Open sprinters','Open opties','Gesloten aandelen','Gesloten sprinters','Gesloten opties','Dividend','Totaal zonder fees','Fees','Totaal'];
    const count=p?.steps?.length||17,head=table.tHead.rows[0],body=table.tBodies[0];
    while(head.cells.length<count+1)head.append(document.createElement('th'));
    while(head.cells.length>count+1)head.lastChild.remove();
    if(head.cells[0].textContent!=='Eindkoers')head.cells[0].textContent='Eindkoers';
    for(let i=0;i<count;i++){
      const cell=head.cells[i+1],value=p?.steps?Number(p.steps[i]).toLocaleString('nl-NL',{minimumFractionDigits:p.decimals??2,maximumFractionDigits:p.decimals??2}):'â€”',cls=i===p?.current_col?'current':'';
      if(cell.textContent!==value)cell.textContent=value;if(cell.className!==cls)cell.className=cls;
    }
    while(body.rows.length<labels.length){const row=document.createElement('tr');row.append(document.createElement('th'));body.append(row);}
    labels.forEach((label,r)=>{
      const row=body.rows[r],cls=r===9?'total':'';if(row.className!==cls)row.className=cls;
      if(row.cells[0].textContent!==label)row.cells[0].textContent=label;
      while(row.cells.length<count+1)row.append(document.createElement('td'));
      while(row.cells.length>count+1)row.lastChild.remove();
      for(let i=0;i<count;i++){
        const cell=row.cells[i+1],v=p?.values?.[r]?.[i],value=v==null?'â€”':Number(v).toLocaleString('nl-NL',{maximumFractionDigits:0});
        const cls=(v<0?'negative ':'')+(i===p?.current_col?'current':'');
        if(cell.textContent!==value)cell.textContent=value;if(cell.className!==cls)cell.className=cls;
      }
    });
  }
  window.clearAnalytics=asset=>{
    analytics={asset,payoff:{},history:[]};range=null;payoffTable({});
    $('payoff-status').textContent='Geen asset geselecteerd';$('history-status').textContent='Geen historie';drawAll();
  };
  window.receiveAnalytics=raw=>{
    const next=JSON.parse(raw);if(next.asset!==current?.asset)return;
    // Base fields and analytic values for an asset appear in the same paint.
    commitDashboard(next.asset);
    if(next.error){
      analytics={asset:next.asset,payoff:{},history:[]};payoffTable({});drawAll();
      $('payoff-status').textContent=next.error;$('history-status').textContent=next.error;return;
    }
    const switched=analytics?.asset!==next.asset;
    const payoffChanged=switched||JSON.stringify(analytics?.payoff)!==JSON.stringify(next.payoff);
    const historyChanged=switched||JSON.stringify(analytics?.history)!==JSON.stringify(next.history);
    if(switched)range=null;
    analytics=next;if(payoffChanged)payoffTable(next.payoff);
    $('payoff-status').textContent=next.payoff.steps?'EUR Â· '+next.payoff.price_source:'Geen referentiekoers beschikbaar';
    $('history-status').textContent=next.history.length?next.history.length+' punten Â· '+next.history[0].date+' t/m '+next.history[next.history.length-1].date:'Geen historie beschikbaar binnen deze periode';
    for(const chart of charts)if(chart.kind==='payoff'?payoffChanged:historyChanged)chart.draw();
  };
  window.addEventListener('dashboard-theme-changed',drawAll);
  document.addEventListener('DOMContentLoaded',()=>{
    for(const [id,kind]of [['payoff-chart','payoff'],['price-chart','price'],['quantity-chart','quantity'],['result-chart','result']])charts.push(new Chart(id,kind));
  });
})();
