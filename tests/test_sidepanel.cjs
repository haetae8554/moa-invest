const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const origin='http://127.0.0.1:8765';
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function deferred() {
  let resolve;
  const promise=new Promise(r=>resolve=r);
  return {promise,resolve};
}
function panel({ensure=async()=>({ok:true}),tick=async()=>({enabled:true,symbol:'GOOW',tabId:3,path:'/stocks/test/order'})}={}) {
  const elements=new Map(),listeners={},sent=[],calls=[],frames=[];
  let poll;
  function element(id) {
    const handlers={};
    const node={hidden:false,textContent:'',handlers,
      addEventListener:(type,fn)=>handlers[type]=fn,
      setAttribute(){},removeAttribute(name){delete this[name];},
      cloneNode:()=>element(id),replaceWith:next=>elements.set(id,next)};
    if(id==='desk') {
      node.actualOrigin='chrome-extension://test';
      node.contentWindow={postMessage(message,target){
        assert.equal(target,node.actualOrigin,'must not message a blank or failed frame');
        sent.push({message,target,frame:node});
      }};
      frames.push(node);
    }
    return node;
  }
  const get=id=>{
    if(!elements.has(id))elements.set(id,element(id));
    return elements.get(id);
  };
  const context=vm.createContext({document:{getElementById:get},
    window:{addEventListener:(type,fn)=>listeners[type]=fn},
    chrome:{runtime:{sendMessage:async message=>{calls.push(message);return message.type==='panel-tick'?tick():{};}},
      windows:{getCurrent:async()=>({id:1})},storage:{local:{set:async()=>{}}},
      sidePanel:{close:async()=>{}}},
    MoaSync:{symbol:value=>typeof value==='string'&&/^[A-Z]{1,5}$/.test(value)},
    MoaLauncher:{ensure},crypto:{randomUUID:()=>String(sent.length)},
    setInterval:fn=>{poll=fn;}});
  vm.runInContext(fs.readFileSync('browser_extension/sidepanel.js','utf8'),context);
  function message(data,{frame=get('desk'),source=frame.contentWindow,eventOrigin=origin}={}) {
    return listeners.message({source,origin:eventOrigin,data:{channel:'moa-panel',...data}});
  }
  function ready(frame=get('desk')) {
    frame.actualOrigin=origin;
    return message({type:'ready'},{frame});
  }
  return {get,frames,sent,calls,ready,message,poll:()=>poll(),click:id=>get(id).handlers.click()};
}

test('blank, loading and failed frames receive no polling messages',async()=>{
  const launch=deferred(),p=panel({ensure:()=>launch.promise});
  await flush();
  await p.poll();await p.poll();
  assert.equal(p.get('desk').src,undefined);
  launch.resolve({ok:false,text:'Install the helper'});
  await flush();
  assert.equal(p.get('desk').src,origin+'/panel');
  await p.poll();await p.poll();
  assert.equal(p.sent.length,0);
  assert.equal(p.calls.filter(m=>m.type==='panel-tick').length,0);
  assert.equal(p.get('offline').hidden,false);
});

test('only a ready message from the exact child and local origin starts sync',async()=>{
  const p=panel();await flush();
  await p.message({type:'ready'},{eventOrigin:'chrome-extension://test'});
  await p.message({type:'ready'},{source:{}});
  await p.poll();assert.equal(p.sent.length,0);
  await p.ready();await flush();
  assert.equal(p.get('offline').hidden,true);
  assert.equal(p.sent.find(x=>x.message.type==='select').message.symbol,'GOOW');
  await p.click('settings');
  assert.equal(p.sent.at(-1).message.type,'open-settings');
  assert.ok(p.sent.every(x=>x.target===origin));
});

test('manual server can become ready without a native helper',async()=>{
  const p=panel({ensure:async()=>({ok:false,text:'Missing helper'})});
  await flush();await p.ready();await flush();
  assert.equal(p.get('offline').hidden,true);
  assert.ok(p.sent.some(x=>x.message.type==='select'));
});

test('retry replaces the frame and rejects delayed readiness from the old document',async()=>{
  const p=panel();await flush();await p.ready();await flush();
  const old=p.get('desk');p.sent.length=0;
  await p.click('retry');
  assert.notEqual(p.get('desk').contentWindow,old.contentWindow);
  await p.ready(old);await p.poll();
  assert.equal(p.sent.length,0);assert.equal(p.get('offline').hidden,false);
  await p.ready();await flush();
  assert.equal(p.get('offline').hidden,true);
});

test('a pending old sync response cannot message a replacement blank frame',async()=>{
  const response=deferred(),p=panel({tick:()=>response.promise});
  await flush();await p.ready();
  await p.click('reload');
  response.resolve({enabled:true,symbol:'GOOW',tabId:3});await flush();
  assert.equal(p.sent.length,0);
  await p.ready();await flush();
  assert.ok(p.sent.some(x=>x.message.type==='select'));
});

test('overlapping launches cannot overwrite the latest settings navigation',async()=>{
  const launches=[deferred(),deferred()];let count=0;
  const p=panel({ensure:()=>launches[count++].promise});
  await flush();const old=p.get('desk');
  const settings=p.click('settings');await flush();
  launches[1].resolve({ok:true});await settings;await flush();
  assert.equal(p.get('desk').src,origin+'/panel#settings');
  launches[0].resolve({ok:true});await flush();
  assert.equal(old.src,undefined);
  assert.equal(p.get('desk').src,origin+'/panel#settings');
});

test('duplicate ready does not reset an acknowledged selection',async()=>{
  const p=panel();await flush();await p.ready();await flush();
  const selected=p.sent.find(x=>x.message.type==='select').message;
  await p.message({type:'selected-result',requestId:selected.requestId,ok:true});
  await p.ready();await p.poll();await flush();
  assert.equal(p.sent.filter(x=>x.message.type==='select').length,1);
});

test('HTML leaves initial navigation to the installed message receiver',()=>{
  const html=fs.readFileSync('browser_extension/sidepanel.html','utf8');
  assert.doesNotMatch(html.match(/<iframe\b[^>]*>/)[0],/\ssrc\s*=/);
});
