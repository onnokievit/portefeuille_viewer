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
require('node:assert/strict').equal(payoff.min,-12500);
require('node:assert/strict').equal(payoff.max,37500);
require('node:assert/strict').deepEqual(payoff.ticks,[-10000,0,10000,20000,30000]);

const detailed=legacy.payoff(-9000,2000,600);
require("node:assert/strict").equal(detailed.step,1000);
require("node:assert/strict").ok(detailed.ticks.includes(-11000));
require("node:assert/strict").ok(detailed.ticks.includes(2000));
require("node:assert/strict").ok(legacy.payoff(-9000,2000,240).ticks.length<detailed.ticks.length);
