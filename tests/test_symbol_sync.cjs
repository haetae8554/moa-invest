const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const P=require('../browser_extension/protocol.js');
const Resolver=require('../browser_extension/resolver.js');

test('origins, tickers and stock paths are tightly scoped',()=>{
  assert.equal(P.kind('https://www.tossinvest.com/stocks/AMX0250724002/order'),'toss');
  assert.equal(P.kind('http://127.0.0.1:8765/#buy'),'moa');
  for(const url of ['https://tossinvest.com.evil.test/','http://tossinvest.com/','https://tossinvest.com:8888/', 'http://localhost:8766/','http://localhost:8765/api/setup','http://x@localhost:8765/']) assert.equal(P.kind(url),null);
  assert.equal(P.stockPath('https://tossinvest.com/stocks/AMX0250724002/order?x=1'),'/stocks/AMX0250724002/order');
  assert.equal(P.stockPath('https://tossinvest.com/account'),null);
  for(const value of ['//evil.test','/api/orders','/stocks/../order']) assert.equal(P.validPath(value),false);
  assert.equal(P.symbol(' brk.b '),'BRK.B');
  assert.equal(P.symbol('GOOW<script>'),null);
});
function background() {
  const local={},session={},sent=[],fetched=[];
  const tabs=new Map([[1,{id:1,active:true,windowId:10,url:'https://www.tossinvest.com/stocks/one/order'}],[2,{id:2,windowId:10,url:'http://127.0.0.1:8765/'}],[3,{id:3,windowId:10,url:'https://www.tossinvest.com/stocks/two/order'}]]);
  let listener,removed;
  const model={symbol:'GOOW',symbols:['GOOW','TLT'],links:[],busy:false,networkStatus:0,beforeFetch:null};
  const area=data=>({get:async key=>({[key]:data[key]}),set:async values=>Object.assign(data,values),remove:async key=>{delete data[key];}});
  const chrome={storage:{local:area(local),session:area(session)},runtime:{id:'test',getURL:path=>`chrome-extension://test/${path}`,onMessage:{addListener:fn=>{listener=fn;}}},tabs:{
    get:async id=>{if(!tabs.has(id))throw Error('closed');return {...tabs.get(id)};},query:async options=>[...tabs.values()].filter(tab=>(options.windowId === undefined || options.windowId === tab.windowId) && (!options.active || tab.active)),onRemoved:{addListener:fn=>{removed=fn;}},
    sendMessage:async(id,message)=>{
      if(!tabs.has(id))throw Error('closed');
      if(message.type==='inspect')return id===2 ? {symbol:model.symbol,symbols:model.symbols} : {path:P.stockPath(tabs.get(id).url),links:model.links};
      sent.push({id,...message});
      if(message.type==='select' && id===2){if(model.busy)return {ok:false,retry:true,error:'busy'};model.symbol=message.symbol;}
      if(message.type==='select' && id===1)tabs.get(1).url=`https://www.tossinvest.com${message.path}`;
      return {ok:true};
    }
  }};
  const context=vm.createContext({chrome,MoaSync:P,MoaStockResolver:Resolver,importScripts(){},fetch:async(url,options)=>{
    fetched.push({url,options});
    if (model.beforeFetch) await model.beforeFetch();
    const key=url.split('/').at(-1), row={one:{code:'one',symbol:'GOOW'},GOOW:{code:'one',symbol:'GOOW'},two:{code:'two',symbol:'TLT'},TLT:{code:'two',symbol:'TLT'}}[key];
    return {ok:!model.networkStatus && !!row,status:model.networkStatus || (row ? 200 : 404),json:async()=>({result:row})};
  }});
  vm.runInContext(fs.readFileSync('browser_extension/background.js','utf8'),context);
  const popup={id:'test',url:'chrome-extension://test/popup.html'};
  const sender=id=>({id:'test',tab:{...tabs.get(id)},url:tabs.get(id)?.url,frameId:0});
  const send=(message,source=popup)=>new Promise(resolve=>listener(message,source,resolve));
  const pair=()=>send({type:'pair',tossId:1,moaId:2});
  const cache=async(symbol='GOOW')=>{local.stockCache=[...(local.stockCache || []),{symbol,path:P.stockPath(tabs.get(1).url),checkedAt:Date.now()}];if(session.pair?.enabled)await send({type:'toss-route',path:P.stockPath(tabs.get(1).url)},sender(1));};
  return {model,local,session,sent,tabs,send,sender,pair,cache,removed,fetched};
}
test('cached metadata connects Toss to Moa; Moa selection navigates the paired Toss tab',async()=>{
  const h=background();
  await h.cache(); await h.pair();
  assert.equal(h.model.symbol,'GOOW');
  h.tabs.get(1).url='https://www.tossinvest.com/stocks/two/order';
  await h.cache('TLT'); assert.equal(h.model.symbol,'TLT');
  h.model.symbol='GOOW';
  await h.send({type:'moa-select',symbol:'GOOW'},h.sender(2));
  assert.equal(h.tabs.get(1).url,'https://www.tossinvest.com/stocks/one/order');
  assert.equal(h.tabs.get(3).url,'https://www.tossinvest.com/stocks/two/order');
  await h.send({type:'toss-route',path:'/stocks/one/order',links:[]},h.sender(1));
  assert.equal(h.session.pair.text,'토스 ↔ 모아 · GOOW');
  assert.ok(h.sent.every(message=>['select','status'].includes(message.type)));
});
test('unknown stock never guesses or navigates',async()=>{
  const h=background();h.tabs.get(1).url='https://www.tossinvest.com/stocks/unknown/order';await h.pair();
  assert.match(h.session.pair.text,/자동 조회 실패/);
  h.model.symbol='UNKNOWN';
  const result=await h.send({type:'moa-select',symbol:'UNKNOWN'},h.sender(2));
  assert.match(result.error,/자동 조회 실패/);
  assert.equal(h.sent.filter(message=>message.type==='select').length,0);
});
test('pause blocks both directions and resume applies the current Toss stock',async()=>{
  const h=background();await h.cache();await h.pair();await h.send({type:'toggle'});
  const count=h.sent.filter(message=>message.type==='select').length;
  h.model.symbol='TLT';
  await h.send({type:'moa-select',symbol:'TLT'},h.sender(2));
  await h.send({type:'toss-route',path:'/stocks/one/order',links:[]},h.sender(1));
  assert.equal(h.sent.filter(message=>message.type==='select').length,count);
  await h.send({type:'toggle'});assert.equal(h.model.symbol,'GOOW');
});
test('unpaired tabs, iframes and unrelated origins cannot change the connection',async()=>{
  const h=background();await h.cache();await h.pair();const before=JSON.stringify(h.session);
  await h.send({type:'toggle'},h.sender(3));
  await h.send({type:'toggle'},{...h.sender(2),frameId:1});
  await h.send({type:'pair',tossId:3,moaId:2},h.sender(2));
  await h.send({type:'toggle'},{...h.sender(2),url:'https://evil.test'});
  assert.equal(JSON.stringify(h.session),before);
});
test('stale routes and stale input are ignored; busy Moa asks for retry',async()=>{
  const h=background();await h.cache();await h.pair();h.model.busy=true;
  const result=await h.send({type:'toss-route',path:'/stocks/one/order',links:[]},h.sender(1));
  assert.equal(result.retry,true);
  const count=h.sent.length;
  await h.send({type:'toss-route',path:'/stocks/old/order',links:[]},h.sender(1));
  await h.send({type:'moa-select',symbol:'TLT'},h.sender(2));
  assert.equal(h.sent.length,count);
});
test('changed or closed paired tabs stop forwarding',async()=>{
  const h=background();await h.cache();await h.pair();
  h.tabs.get(2).url='https://evil.test';
  const result=await h.send({type:'toss-route',path:'/stocks/one/order',links:[]},h.sender(1));
  assert.match(result.error,/주소/);
  h.removed(1);
  await h.send({type:'list'}); // Drain the serialized event queue.
  assert.equal(h.session.pair,undefined);
});

test('uncached ticker and route resolve automatically without any manual mapping',async()=>{
  const h=background();await h.pair();
  assert.equal(h.model.symbol,'GOOW');assert.equal(h.fetched.length,1);
  h.model.symbol='TLT';await h.send({type:'moa-select',symbol:'TLT'},h.sender(2));
  assert.equal(h.tabs.get(1).url,'https://www.tossinvest.com/stocks/two/order');
  assert.equal(h.fetched.length,2);
  await h.send({type:'toss-route',path:'/stocks/two/order'},h.sender(1));
  assert.equal(h.fetched.length,2); // The reverse lookup reuses verified metadata.
  for (const call of h.fetched) {
    assert.equal(new URL(call.url).origin,'https://wts-info-api.tossinvest.com');
    assert.equal(call.options.credentials,'omit');assert.equal(call.options.method,'GET');
    assert.equal(call.options.redirect,'error');assert.deepEqual(Object.keys(call.options.headers),['Accept']);
  }
});
test('one Toss and one Moa in the same window pair automatically, ambiguity stays unpaired',async()=>{
  const h=background();
  await h.send({type:'moa-status'},h.sender(2));assert.equal(h.session.pair,undefined);
  h.tabs.get(3).windowId=20;
  const result=await h.send({type:'moa-status'},h.sender(2));
  assert.equal(result.paired,true);assert.equal(h.session.pair.tossId,1);
  await h.send({type:'toggle'});delete h.session.pair;
  await h.send({type:'moa-status'},h.sender(2));assert.equal(h.session.pair,undefined);
});
test('HTTP failure never guesses a symbol and repeated polling respects cooldown',async()=>{
  const h=background();h.model.networkStatus=403;await h.pair();
  assert.match(h.session.pair.text,/403/);assert.equal(h.fetched.length,1);
  for (let i=0;i<3;i++) await h.send({type:'toss-route',path:'/stocks/one/order'},h.sender(1));
  assert.equal(h.fetched.length,1);assert.equal(h.sent.filter(row=>row.type==='select').length,0);
  h.model.networkStatus=0;await h.send({type:'refresh'});
  assert.equal(h.model.symbol,'GOOW');assert.equal(h.fetched.length,2);
});
test('navigation changing during metadata request discards the old selection',async()=>{
  const h=background();h.model.symbol='TLT';
  h.model.beforeFetch=async()=>{h.tabs.get(1).url='https://www.tossinvest.com/stocks/two/order';};
  await h.pair();assert.equal(h.model.symbol,'TLT');
  assert.equal(h.sent.filter(row=>row.type==='select').length,0);
});
test('metadata validates exact identity, supports dotted tickers and expires cache',async()=>{
  assert.deepEqual(Resolver.parse({result:{code:'USCODE',symbol:'BRK.B'}},'BRK.B','symbol'),{path:'/stocks/USCODE/order',symbol:'BRK.B'});
  assert.throws(()=>Resolver.parse({result:{code:'OTHER',symbol:'GOOW'}},'REQUESTED','code'));
  assert.throws(()=>Resolver.parse({result:{code:'ok',symbol:'GOF'}},'GOOW','symbol'));
  assert.throws(()=>Resolver.parse({result:{code:'../evil',symbol:'GOOW'}},'GOOW','symbol'));
  assert.throws(()=>Resolver.parse({result:{code:'A005930',symbol:'005930'}},'A005930','code'));
  let time=100000000,rows=[{path:'/stocks/old/order',symbol:'GOOW',checkedAt:0}],calls=0;
  const resolver=Resolver.create({now:()=>time,read:async()=>rows,write:async value=>{rows=value;},fetch:async()=>{calls++;return {ok:true,json:async()=>({result:{code:'new',symbol:'GOOW'}})};}});
  assert.equal((await resolver.resolve('GOOW','symbol')).path,'/stocks/new/order');assert.equal(calls,1);
  await resolver.resolve('new','code');assert.equal(calls,1);
  time+=86400001;await resolver.resolve('GOOW','symbol');assert.equal(calls,2);
});

function app() {
  const nodes=new Map(),listeners={},posts=[],requests=[];
  function node(){return {value:'',textContent:'',children:[],dataset:{},handlers:{},classList:{toggle(){},remove(){}},parentElement:{classList:{toggle(){},remove(){}}},addEventListener(name,fn){this.handlers[name]=fn;},setAttribute(){},append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},close(){this.open=false;},showModal(){this.open=true;},focus(){}};}
  const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
  const window={addEventListener:(type,fn)=>{listeners[type]=fn;},postMessage:message=>posts.push(message)};
  const context=vm.createContext({window,location:{origin:'http://127.0.0.1:8765'},document:{getElementById:get,querySelectorAll:()=>[],createElement:node,createTextNode:()=>node()},Intl,Date,console,setTimeout(){},clearTimeout(){},setInterval(){},fetch:(path,options)=>{requests.push({path,options});return new Promise(()=>{});},matchMedia:()=>({matches:false})});
  vm.runInContext(fs.readFileSync('order_ui/static/app.js','utf8'),context);
  const send=data=>listeners.message({source:window,origin:'http://127.0.0.1:8765',data:{channel:'moa-symbol-sync',source:'extension',requestId:'test',...data}});
  return {get,context,posts,requests,send,listeners,window};
}
test('incoming selection closes stale preview, keeps amount/side, and sends no order requests',()=>{
  const h=app();h.get('symbol').value='TLT';h.get('amount').value='90';h.get('review').open=true;
  vm.runInContext("preview={expiresTimestamp:9999999999};side='SELL';",h.context);
  const before=h.requests.length;h.send({type:'select',symbol:'GOOW'});
  assert.equal(h.get('symbol').value,'GOOW');assert.equal(h.get('review').open,false);
  assert.equal(vm.runInContext('preview',h.context),null);assert.equal(vm.runInContext('side',h.context),'SELL');
  assert.equal(h.get('amount').value,'90');assert.equal(h.requests.length,before);
  assert.equal(h.posts.at(-1).ok,true);assert.equal(h.posts.filter(message=>message.type==='selected').length,0);
});
test('same selection preserves preview; processing defers new selection',()=>{
  const h=app();h.get('symbol').value='GOOW';h.get('review').open=true;
  vm.runInContext('preview={expiresTimestamp:9999999999};',h.context);
  h.send({type:'select',symbol:'GOOW'});assert.equal(h.get('review').open,true);
  vm.runInContext('busy=true;',h.context);h.send({type:'select',symbol:'TLT'});
  assert.equal(h.get('symbol').value,'GOOW');assert.equal(h.posts.at(-1).ok,false);assert.equal(h.posts.at(-1).retry,true);
});
test('invalid selection and foreign page messages cannot alter the ticker',()=>{
  const h=app();h.get('symbol').value='GOOW';
  h.send({type:'select',symbol:'GOOW<script>'});assert.equal(h.get('symbol').value,'GOOW');
  h.listeners.message({source:h.window,origin:'https://tossinvest.com',data:{channel:'moa-symbol-sync',source:'extension',type:'select',symbol:'TLT',requestId:'test'}});
  assert.equal(h.get('symbol').value,'GOOW');
});

const panelSender={id:'test',url:'chrome-extension://test/sidepanel.html'};
test('panel follows active Toss without a Moa tab and never receives account data',async()=>{
  const h=background();h.tabs.delete(2);
  const state=await h.send({type:'panel-tick',windowId:10},panelSender);
  assert.equal(state.symbol,'GOOW');assert.equal(state.tabId,1);
  assert.deepEqual(Object.keys(state).sort(),['enabled','path','symbol','tabId','text']);
  const next=await h.send({type:'panel-select',windowId:10,tabId:1,path:state.path,symbol:'TLT'},panelSender);
  assert.equal(next.ok,true);assert.equal(h.tabs.get(1).url,'https://www.tossinvest.com/stocks/two/order');
  assert.ok(h.fetched.every(request=>request.url.startsWith('https://wts-info-api.tossinvest.com/')));
});
test('panel ignores untrusted senders, paused sync and a changed active tab',async()=>{
  const h=background();
  const request={type:'panel-select',windowId:10,tabId:1,path:'/stocks/one/order',symbol:'TLT'};
  await h.send(request,h.sender(1));assert.equal(h.fetched.length,0);
  h.local.panelSync=false;
  assert.equal((await h.send(request,panelSender)).enabled,false);
  assert.equal(h.fetched.length,0);
  h.local.panelSync=true;
  h.model.beforeFetch=async()=>{h.tabs.get(1).active=false;h.tabs.get(3).active=true;};
  assert.ok((await h.send(request,panelSender)).error);
  assert.equal(h.sent.filter(message=>message.type==='select').length,0);
});
test('panel mode pauses paired Moa tabs to prevent selection feedback',async()=>{
  const h=background();await h.pair();
  await h.send({type:'panel-tick',windowId:10},panelSender);
  assert.equal(h.session.pair.enabled,false);assert.equal(h.local.autoConnect,false);
});

test('panel iframe bridge trusts only the fixed extension parent and sends ticker-only data',()=>{
  const manifest=JSON.parse(fs.readFileSync('browser_extension/manifest.json','utf8'));
  const hash=require('node:crypto').createHash('sha256').update(Buffer.from(manifest.key,'base64')).digest('hex').slice(0,32);
  const id=[...hash].map(c=>String.fromCharCode(97+parseInt(c,16))).join('');
  const origin='chrome-extension://'+id;
  assert.ok(fs.readFileSync('order_ui/extension.py','utf8').includes(origin));
  let listener,opened=0;const local=[],parentMessages=[];
  const parent={postMessage:(message,target)=>parentMessages.push({message,target})};
  const win={parent,addEventListener:(_,fn)=>{listener=fn;},postMessage:message=>local.push(message)};
  const context=vm.createContext({window:win,parent,location:{pathname:'/panel',origin:'http://127.0.0.1:8765'},document:{body:{classList:{add(){}}},querySelector:()=>({}),getElementById:()=>({click(){opened++;}})}});
  vm.runInContext(fs.readFileSync('order_ui/static/panel-bridge.js','utf8'),context);
  const data={channel:'moa-panel',type:'select',symbol:'TLT',requestId:'r',clientSecret:'must-not-cross'};
  listener({source:parent,origin:'https://www.tossinvest.com',data});
  listener({source:{},origin,data});assert.equal(local.length,0);
  listener({source:parent,origin,data});assert.equal(local.length,1);assert.equal(local[0].symbol,'TLT');assert.equal(local[0].clientSecret,undefined);
  listener({source:parent,origin,data:{channel:'moa-panel',type:'open-settings'}});assert.equal(opened,1);
  listener({source:win,origin:'http://127.0.0.1:8765',data:{channel:'moa-symbol-sync',source:'page',type:'selected',symbol:'AAPL',account:'must-not-cross'}});
  assert.equal(parentMessages.at(-1).message.symbol,'AAPL');assert.equal(parentMessages.at(-1).message.account,undefined);
  assert.ok(parentMessages.every(m=>m.target===origin));
});
