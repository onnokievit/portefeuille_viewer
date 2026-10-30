/* Pure scale logic, shared by the three time charts and executable in Node tests. */
((root) => {
  'use strict';
  const clean=value=>Number(Number(value).toPrecision(13));
  function scale(min,max,kind){
    if(!Number.isFinite(min)||!Number.isFinite(max))throw new Error('Invalid axis range');
    if(min>max)[min,max]=[max,min];
    const integer=kind==='quantity';
    if(integer){min=Math.min(0,min);max=Math.max(0,max);}
    if(min===max){
      if(integer){min=0;max=1;}
      else{const padding=Math.max(Math.abs(min)*.05,1);min-=padding;max+=padding;}
    }
    const exponent=Math.floor(Math.log10((max-min)/6));
    for(let power=exponent-1;power<=exponent+5;power++){
      for(const multiple of [1,1.25,2,2.5,5,10]){
        const step=clean(multiple*10**power);
        if(integer&&(step<1||!Number.isInteger(step)))continue;
        // Seven ticks = six equal intervals. Start/end are exact multiples.
        let lower=Math.ceil(max/step-1e-10)-6;
        const upper=Math.floor(min/step+1e-10);
        if(kind==='price'&&min>=0)lower=Math.max(0,lower);
        if(lower>upper)continue;
        let start=Math.max(lower,Math.min(upper,Math.round((min+max)/(2*step)-3)));
        if(integer&&min===0){if(6*step<max)continue;start=0;}
        if(integer&&max===0){if(-6*step>min)continue;start=-6;}
        const ticks=Array.from({length:7},(_,i)=>clean((start+i)*step));
        return{min:ticks[0],max:ticks[6],step,ticks};
      }
    }
    throw new Error('Axis range cannot be represented');
  }
  function decimals(step){
    for(let n=0;n<=8;n++)if(Math.abs(step*10**n-Math.round(step*10**n))<1e-8)return n;
    return 8;
  }
  function format(value,step){
    return (Object.is(value,-0)?0:value).toLocaleString('nl-NL',{
      maximumFractionDigits:decimals(step),minimumFractionDigits:0,
    });
  }
  function ticksWithin(min,max,intervals=6){
    const raw=(max-min)/intervals, power=10**Math.floor(Math.log10(raw));
    const step=[1,2,5,10].map(n=>n*power).find(n=>n>=raw)||10*power;
    const ticks=[];
    for(let i=Math.ceil(min/step);i<=Math.floor(max/step);i++)ticks.push(clean(i*step));
    return {min,max,step,ticks};
  }
  function payoff(min,max,height){
    if(min===max){const span=Math.max(Math.abs(min)*.05,1);min-=span/2;max+=span/2;}
    // Each side occupies 5% of the final plot height: remaining data span = 90%.
    const margin=(max-min)/18;
    const intervals=Number.isFinite(height)?Math.max(3,Math.floor(height/40)):6;
    return ticksWithin(min-margin,max+margin,intervals);
  }
  function payoffX(value,steps,left,right){
    const n=steps.length;
    if(n<2)return (left+right)/2;
    let interval=-1;
    for(let i=0;i<n-1;i++)if(steps[i+1]>steps[i]){
      interval=i;if(value<=steps[i+1])break;
    }
    if(interval<0)return (left+right)/2;
    const fraction=(value-steps[interval])/(steps[interval+1]-steps[interval]);
    return left+(interval+.5+fraction)/n*(right-left);
  }
  const api={scale,format,ticksWithin,payoff,payoffX};root.DashboardAxes=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
