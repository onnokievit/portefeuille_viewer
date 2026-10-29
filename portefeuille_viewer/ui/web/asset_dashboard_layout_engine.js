/* Pure grid placement logic; shared with the deterministic Node checks. */
((root)=>{
  'use strict';
  const ids=['payoff','indicator','payoff_table','price','result','quantity','puts','calls','holdings','test_orders','market','earnings'];
  const copy=layout=>JSON.parse(JSON.stringify(layout));
  const columns=240;
  function normalize(layout){
    if([1,2].includes(layout?.version)&&Array.isArray(layout.blocks)){
      const horizontal=layout.version===1?10:1;
      return {version:3,blocks:layout.blocks.map(b=>({...b,x:b.x*horizontal,w:b.w*horizontal,y:b.y*10,h:b.h*10}))};
    }
    return layout;
  }
  const overlaps=(a,b)=>a.x<b.x+b.w&&b.x<a.x+a.w&&a.y<b.y+b.h&&b.y<a.y+a.h;
  function defaults(mode){
    const positions=mode==='laptop'?
      [[0,0,12,15],[12,0,12,5],[12,5,12,10],[0,15,8,10],[8,15,8,10],[16,15,8,10],[0,25,24,5],[0,30,24,5],[0,35,24,5],[0,40,24,8],[0,48,12,6],[12,48,12,6]]:
      [[0,0,7,16],[7,0,10,5],[7,5,10,11],[17,0,7,10],[17,10,7,10],[17,20,7,10],[0,16,17,5],[0,21,17,5],[0,26,17,5],[0,31,17,8],[0,39,12,6],[12,39,12,6]];
    return {version:3,blocks:ids.map((id,i)=>{const[x,y,w,h]=positions[i];return{id,x:x*10,y:y*10,w:w*10,h:h*10};})};
  }
  function valid(layout){
    if(layout?.version!==3||!Array.isArray(layout.blocks)||layout.blocks.length!==ids.length)return false;
    const seen=new Set();
    for(const b of layout.blocks){
      if(!ids.includes(b.id)||seen.has(b.id)||!['x','y','w','h'].every(k=>Number.isInteger(b[k])))return false;
      if(b.x<0||b.x>=columns||b.y<0||b.y>5000||b.w<40||b.w>columns||b.h<30||b.h>800||b.x+b.w>columns)return false;
      seen.add(b.id);
    }
    return !layout.blocks.some((a,i)=>layout.blocks.slice(i+1).some(b=>overlaps(a,b)));
  }
  const positionIds=['puts','calls','holdings'];
  function pack(placed,others){
    for(const block of others.sort((a,b)=>a.y-b.y||a.x-b.x)){
      let collision;
      while((collision=placed.find(b=>overlaps(block,b))))block.y=collision.y+collision.h;
      placed.push(block);
    }
  }
  function placePositions(layout,patch){
    const result=copy(normalize(layout)),anchor=result.blocks.find(b=>b.id==='puts');
    const w=Math.max(40,Math.min(columns,Math.round(patch.w??anchor.w)));
    const x=Math.max(0,Math.min(columns-w,Math.round(patch.x??anchor.x)));
    let y=Math.max(0,Math.min(5000,Math.round(patch.y??anchor.y)));
    const placed=[];
    for(const id of positionIds){
      const block=result.blocks.find(b=>b.id===id);
      Object.assign(block,{x,y,w});y+=block.h;placed.push(block);
    }
    pack(placed,result.blocks.filter(b=>!positionIds.includes(b.id)));
    if(!valid(result))throw new Error('Indeling is te hoog; verplaats het blok dichter naar boven');
    return result;
  }
  // Content height is display-only. Asset switches never rewrite saved positions.
  function flowPositions(layout,height){
    const source=copy(normalize(layout)),members=source.blocks.filter(b=>positionIds.includes(b.id));
    const anchor=members.find(b=>b.id==='puts'),reservedBottom=Math.max(...members.map(b=>b.y+b.h));
    const group={...anchor,h:Math.max(0,Math.ceil(height))};
    const extra=Math.max(0,group.y+group.h-reservedBottom);
    const others=source.blocks.filter(b=>!positionIds.includes(b.id));
    for(const block of others)if(block.y>=reservedBottom)block.y+=extra;
    pack(group.h?[group]:[],others);
    return {version:3,blocks:group.h?[group,...others]:others};
  }
  function place(layout,id,patch){
    if(id==='puts')return placePositions(layout,patch);
    const result=copy(normalize(layout)),moving=result.blocks.find(b=>b.id===id);
    if(!moving)throw new Error('Onbekend blok');
    Object.assign(moving,patch);
    moving.w=Math.max(40,Math.min(columns,Math.round(moving.w)));
    moving.h=Math.max(30,Math.min(800,Math.round(moving.h)));
    moving.x=Math.max(0,Math.min(columns-moving.w,Math.round(moving.x)));
    moving.y=Math.max(0,Math.min(5000,Math.round(moving.y)));
    // Keep the chosen position. Move colliding blocks down, in their old order.
    const placed=[moving];
    const others=result.blocks.filter(b=>b!==moving).sort((a,b)=>a.y-b.y||a.x-b.x);
    for(const block of others){
      let collision;
      while((collision=placed.find(b=>overlaps(block,b))))block.y=collision.y+collision.h;
      placed.push(block);
    }
    if(!valid(result))throw new Error('Indeling is te hoog; verplaats het blok dichter naar boven');
    return result;
  }
  const api={ids,columns,normalize,defaults,valid,place,flowPositions};root.DashboardLayoutEngine=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
