const assert = require('node:assert/strict');
const {scale,format} = require('../portefeuille_viewer/ui/web/asset_dashboard_axes.js');

for(const [min,max,kind]of [[0,500,'quantity'],[-40,540,'quantity'],[-540,-40,'quantity'],
  [0,0,'quantity'],[1,2,'quantity'],[-18930.8,16383.26,'result'],[0,500,'result'],
  [0,10000,'result'],[157.44,785.42,'price'],[1.0712,1.0893,'price'],[100,100,'price']]){
  const a=scale(min,max,kind);
  assert.equal(a.ticks.length,7);
  assert.ok(a.min<=min&&a.max>=max,JSON.stringify({min,max,a}));
  assert.ok(a.step>0);
  a.ticks.slice(1).forEach((tick,i)=>assert.ok(Math.abs(tick-a.ticks[i]-a.step)<1e-7));
  if(kind==='quantity'){assert.ok(a.ticks.includes(0));assert.ok(a.ticks.every(Number.isInteger));}
}
assert.deepEqual(scale(0,500,'quantity').ticks,[0,100,200,300,400,500,600]);
assert.equal(format(10000,2000),'10.000');
assert.equal(format(500,100),'500');
assert.equal(format(-0,100),'0');
assert.equal(format(1.075,.0025),'1,075');
// Broad deterministic ranges: guarantee coverage and an explicit zero tick.
for(let i=1;i<=500;i++){
  const min=-i*13.7,max=i*17.3;
  for(const kind of ['quantity','result','price']){
    const a=scale(min,max,kind);
    assert.ok(a.min<=min+1e-8&&a.max>=max-1e-8);
    assert.equal(a.ticks.length,7);
    assert.ok(a.ticks.includes(0));
    if(kind==='quantity')assert.ok(a.ticks.every(Number.isInteger));
  }
}
console.log('Dashboard axes: seven rounded ticks, range coverage, quantity zero and formatting OK');

const legacy=require('../portefeuille_viewer/ui/web/asset_dashboard_axes.js');
const payoff=legacy.payoff(-10000,30000);
assert.ok(Math.abs((-10000-payoff.min)/(payoff.max-payoff.min)-.05)<1e-12);
assert.ok(Math.abs((payoff.max-30000)/(payoff.max-payoff.min)-.05)<1e-12);
require('node:assert/strict').deepEqual(payoff.ticks,[-10000,0,10000,20000,30000]);

const detailed=legacy.payoff(-9000,2000,600);
require("node:assert/strict").equal(detailed.step,1000);
require("node:assert/strict").ok(detailed.ticks.includes(-9000));
require("node:assert/strict").ok(detailed.ticks.includes(2000));
require("node:assert/strict").ok(legacy.payoff(-9000,2000,240).ticks.length<detailed.ticks.length);

for(const [min,max]of [[-15000,2500],[-500,-100],[100,101],[-.1,.02]]){
  const axis=legacy.payoff(min,max,600);
  assert.ok(Math.abs((min-axis.min)/(axis.max-axis.min)-.05)<1e-10);
  assert.ok(Math.abs((axis.max-max)/(axis.max-axis.min)-.05)<1e-10);
}
assert.ok(legacy.payoff(0,0,400).min<0&&legacy.payoff(0,0,400).max>0);

for(const steps of [[84,86,88,90,92],[234.07,239.65,245.22,250.79],[1.001,1.002,1.004]]){
  steps.forEach((value,i)=>assert.ok(Math.abs(legacy.payoffX(value,steps,94,900)-(94+(i+.5)/steps.length*806))<1e-8));
}
assert.equal(legacy.payoffX(100,[100,100],94,900),497);
assert.equal(legacy.payoffX(83,[84,86,88,90,92],100,600),100);
assert.equal(legacy.payoffX(93,[84,86,88,90,92],100,600),600);
