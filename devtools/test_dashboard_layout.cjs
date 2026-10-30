const assert=require('node:assert/strict');
const fs=require('node:fs');
const engine=require('../portefeuille_viewer/ui/web/asset_dashboard_layout_engine.js');
for(const mode of ['desktop','laptop']){
  let value=engine.defaults(mode);assert.ok(engine.valid(value));
  const original=JSON.stringify(value);
  let seed=9823;
  for(let i=0;i<1200;i++){
    seed=(seed*1664525+1013904223)>>>0;
    const id=engine.ids[seed%engine.ids.length];
    try{value=engine.place(value,id,{x:seed%220,y:(seed>>>5)%350,w:40+(seed>>>9)%200,h:30+(seed>>>13)%140});}
    catch(error){assert.match(error.message,/te hoog/);}
    assert.ok(engine.valid(value));
  }
  assert.equal(JSON.stringify(engine.defaults(mode)),original);
}
assert.notDeepEqual(engine.defaults('laptop'),engine.defaults('desktop'));
assert.equal(engine.valid({version:1,blocks:[]}),false);
if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify(engine.defaults('desktop')));
console.log('Dashboard layout: 2400 moves/resizes, collision handling, defaults and immutability OK');

const old=engine.defaults('desktop');old.version=1;old.blocks.forEach(b=>{b.x/=10;b.w/=10;b.y/=10;b.h/=10;});
assert.deepEqual(engine.normalize(old),engine.defaults('desktop'));
const fine=engine.place(engine.defaults('desktop'),'quantity',{w:69});
assert.equal(fine.blocks.find(b=>b.id==='quantity').w,69);

const vertical=engine.place(engine.defaults("desktop"),"quantity",{h:99});
assert.equal(vertical.blocks.find(b=>b.id==="quantity").h,99);

// Content-driven position stack: reserve the saved band and shift everything below on growth.
const base=engine.normalize({version:3,blocks:[
  {id:'puts',x:100,y:0,w:140,h:50},{id:'calls',x:100,y:50,w:140,h:50},{id:'holdings',x:100,y:100,w:140,h:50},
  {id:'indicator',x:0,y:0,w:100,h:50},{id:'payoff_table',x:0,y:50,w:100,h:100},
  {id:'price',x:0,y:150,w:80,h:100},{id:'result',x:80,y:150,w:80,h:100},{id:'quantity',x:160,y:150,w:80,h:100},
  {id:'payoff',x:0,y:250,w:80,h:100},{id:'test_orders',x:0,y:350,w:240,h:80},
  {id:'market',x:0,y:430,w:120,h:60},{id:'earnings',x:120,y:430,w:120,h:60}
]});
assert.ok(engine.valid(base));
const before=JSON.stringify(base),grown=engine.flowPositions(base,200),small=engine.flowPositions(base,40);
for(const id of ['price','result','quantity']){
  assert.equal(grown.blocks.find(b=>b.id===id).y,base.blocks.find(b=>b.id===id).y+50);
  assert.equal(small.blocks.find(b=>b.id===id).y,base.blocks.find(b=>b.id===id).y);
}
assert.equal(engine.flowPositions(base,0).blocks.some(b=>b.id==='puts'),false);
assert.equal(JSON.stringify(base),before);
const moved=engine.place(base,'puts',{x:110,w:130,y:0});
assert.ok(engine.valid(moved));
for(const id of ['puts','calls','holdings'])assert.equal(moved.blocks.find(b=>b.id===id).w,130);
console.log('Auto-height positions: stacking, growth, empty state and saved-layout isolation OK');

const edge=engine.place(base,"puts",{x:239});
assert.equal(edge.blocks.find(b=>b.id==="puts").w,140);
assert.equal(edge.blocks.find(b=>b.id==="puts").x,100);

const rectangle={id:'payoff',x:40,y:100,w:80,h:120};
assert.deepEqual(engine.resizeEdges(rectangle,'w',10,0),{x:50,w:70});
assert.deepEqual(engine.resizeEdges(rectangle,'nw',10,20),{x:50,w:70,y:120,h:100});
assert.deepEqual(engine.resizeEdges(rectangle,'se',10,20),{w:90,h:140});
assert.deepEqual(engine.resizeEdges(rectangle,'ne',10,-20),{w:90,y:80,h:140});
assert.deepEqual(engine.resizeEdges(rectangle,'w',-100,0),{x:0,w:120});
assert.deepEqual(engine.resizeEdges({...rectangle,id:'puts'},'se',10,20),{w:90});
console.log('Border resizing: four directions, corners, fixed opposite edges and automatic height OK');

const flowed=engine.flowMinimumHeight(engine.defaults('laptop'),'asset_info',70);
assert.equal(flowed.blocks.find(b=>b.id==='asset_info').h,70);
assert.ok(engine.valid(flowed));
