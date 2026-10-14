importScripts('protocol.js','resolver.js');
const P=MoaSync;
const resolver=MoaStockResolver.create({fetch:(...args)=>fetch(...args),
  read:async()=>(await chrome.storage.local.get('stockCache')).stockCache || [],
  write:async stockCache=>chrome.storage.local.set({stockCache})});
let queue=Promise.resolve();
const messageTo=(tabId,message)=>chrome.tabs.sendMessage(tabId,message,{frameId:0});
const getPair=async()=>(await chrome.storage.session.get('pair')).pair || null;
const savePair=pair=>chrome.storage.session.set({pair});
async function pairTabs(pair) {
  if (!pair) throw new Error('토스와 모아를 같은 Chrome 창에 열어 주세요.');
  const [toss,moa]=await Promise.all([chrome.tabs.get(pair.tossId),chrome.tabs.get(pair.moaId)]);
  if (P.kind(toss.url) !== 'toss' || P.kind(moa.url) !== 'moa') throw new Error('연결한 탭 주소가 바뀌었어요. 두 탭을 다시 연결해 주세요.');
  return {toss,moa};
}
async function notice(pair,text) {
  pair.text=text;await savePair(pair);
  await messageTo(pair.moaId,{type:'status',connected:true,paired:true,enabled:pair.enabled,text}).catch(()=>{});
}
async function fromToss(pair,path) {
  const {toss}=await pairTabs(pair);
  if (!pair.enabled || path !== P.stockPath(toss.url)) return {ok:false};
  if (!P.validPath(path)) {await notice(pair,'토스에서 종목을 선택해 주세요');return {ok:false};}
  try {
    const stock=await resolver.resolve(path.split('/')[2],'code');
    // The user may have navigated while the public metadata was being fetched.
    if (P.stockPath((await pairTabs(pair)).toss.url) !== path) return {ok:false};
    const result=await messageTo(pair.moaId,{type:'select',symbol:stock.symbol});
    await notice(pair,result?.ok ? `토스 ↔ 모아 · ${stock.symbol}` : result?.error || '모아에서 종목을 변경하지 못했어요');
    return result;
  } catch(error) {
    await notice(pair,error.message || '자동 종목 조회 연결을 확인해 주세요');
    return {ok:false,...(error.requiresRefresh ? {} : {retryAfterMs:30000})};
  }
}
async function connectPair(tossId,moaId) {
  const next={tossId,moaId,enabled:true,text:'종목 자동 연결 중…'};
  const {toss}=await pairTabs(next);
  await Promise.all([messageTo(tossId,{type:'inspect'}),messageTo(moaId,{type:'inspect'})]);
  const old=await getPair();
  if (old && old.moaId !== moaId) await notice({...old,enabled:false},'다른 모아 탭에 연결했어요');
  await savePair(next);await fromToss(next,P.stockPath(toss.url));
  return next;
}
async function autoPair(sender) {
  if ((await chrome.storage.local.get('autoConnect')).autoConnect === false) return null;
  const tabs=(await chrome.tabs.query({windowId:sender.tab.windowId}));
  const toss=tabs.filter(tab=>P.kind(tab.url) === 'toss');
  const moa=tabs.filter(tab=>P.kind(tab.url) === 'moa');
  if (toss.length !== 1 || moa.length !== 1 || moa[0].id !== sender.tab.id) return null;
  try {return await connectPair(toss[0].id,moa[0].id);} catch (_) {return null;}
}
async function panelActive(windowId) {
  if (!Number.isInteger(windowId)) throw new Error('패널 창을 확인할 수 없어요.');
  const tabs=await chrome.tabs.query({windowId,active:true});
  const tab=tabs.find(tab=>P.kind(tab.url)==='toss');
  return tab || null;
}
async function handlePanel(message) {
  if (message.type === 'panel-refresh') {await resolver.clear();return {ok:true};}
  const enabled=(await chrome.storage.local.get('panelSync')).panelSync !== false;
  if (!enabled) return {enabled:false,text:'종목 연결 일시정지 · 주문 입력은 유지돼요'};
  const tab=await panelActive(message.windowId),path=P.stockPath(tab?.url);
  if (!tab || !path) return {enabled:true,text:'이 창의 토스 탭에서 종목을 선택해 주세요.'};
  if (message.type === 'panel-select') {
    if (message.tabId !== tab.id || message.path !== path || !P.symbol(message.symbol)) return {error:'토스 종목이 바뀌었어요. 다시 선택해 주세요.'};
    const stock=await resolver.resolve(P.symbol(message.symbol),'symbol');
    const current=await panelActive(message.windowId);
    if (current?.id!==tab.id || P.stockPath(current.url)!==path) return {error:'토스 탭이 변경되어 이동을 멈췄어요.'};
    if (path!==stock.path) await messageTo(tab.id,{type:'select',path:stock.path});
    return {ok:true};
  }
  const stock=await resolver.resolve(path.split('/')[2],'code');
  const current=await panelActive(message.windowId);
  if (current?.id!==tab.id || P.stockPath(current.url)!==path) return {enabled:true,text:'종목 변경 확인 중…'};
  // Panel mode takes over symbol selection; do not let an older paired tab echo.
  const pair=await getPair();
  if (pair?.enabled) await notice({...pair,enabled:false},'사이드 패널을 사용 중이에요. 탭 연결은 일시정지됐어요.');
  await chrome.storage.local.set({autoConnect:false});
  return {enabled:true,symbol:stock.symbol,tabId:tab.id,path,text:`토스 ↔ 모아 · ${stock.symbol}`};
}
async function handle(message,sender) {
  if (!message || sender.id !== chrome.runtime.id) return {ok:false};
  const popup=!sender.tab && sender.url === chrome.runtime.getURL('popup.html');
  const panel=!sender.tab && sender.url === chrome.runtime.getURL('sidepanel.html');
  if (panel && ['panel-tick','panel-select','panel-refresh'].includes(message.type)) return handlePanel(message);
  const source=sender.frameId === 0 && sender.tab ? P.kind(sender.url) : null;
  let pair=await getPair();
  if (popup) {
    if (message.type === 'list') {
      const tabs=(await chrome.tabs.query({})).filter(tab=>P.kind(tab.url));
      const cached=(await chrome.storage.local.get('stockCache')).stockCache || [];
      return {tabs:tabs.map(tab=>({id:tab.id,kind:P.kind(tab.url),title:tab.title})),pair,cacheCount:cached.length};
    }
    if (message.type === 'pair') {
      await connectPair(message.tossId,message.moaId);
      await chrome.storage.local.set({autoConnect:true});return {ok:true};
    }
    if (message.type === 'refresh') {
      await resolver.clear();
      if (pair?.enabled) await fromToss(pair,P.stockPath((await pairTabs(pair)).toss.url));
      return {ok:true};
    }
  }
  if (message.type === 'moa-status' && source === 'moa') {
    if (pair) {
      try {await pairTabs(pair);} catch (_) {await chrome.storage.session.remove('pair');pair=null;}
    }
    if (!pair) pair=await autoPair(sender);
    if (!pair || pair.moaId !== sender.tab.id) return {enabled:false,text:'같은 Chrome 창에 토스·모아를 열어 주세요. 탭이 여러 개면 확장 메뉴에서 선택하세요.'};
    return {paired:true,enabled:pair.enabled,text:pair.text};
  }
  const pairedMoa=source === 'moa' && pair?.moaId === sender.tab.id;
  const pairedToss=source === 'toss' && pair?.tossId === sender.tab.id;
  if (message.type === 'toggle' && (popup || pairedMoa)) {
    await pairTabs(pair);pair.enabled=!pair.enabled;
    await chrome.storage.local.set({autoConnect:pair.enabled});
    await notice(pair,pair.enabled ? '종목 연결 켜짐' : '종목 연결 일시정지');
    if (pair.enabled) await fromToss(pair,P.stockPath((await pairTabs(pair)).toss.url));
    return {ok:true};
  }
  if (message.type === 'toss-config' && source === 'toss') {
    if (!pairedToss || !pair.enabled) return {enabled:false};
    await pairTabs(pair);return {enabled:true};
  }
  if (message.type === 'toss-route' && pairedToss) return fromToss(pair,message.path);
  if (message.type === 'moa-select' && pairedMoa && pair.enabled) {
    await pairTabs(pair);
    const symbol=P.symbol(message.symbol);
    if (!symbol || (await messageTo(pair.moaId,{type:'inspect'})).symbol !== symbol) return {ok:false};
    try {
      const stock=await resolver.resolve(symbol,'symbol');
      const {toss}=await pairTabs(pair);
      if ((await messageTo(pair.moaId,{type:'inspect'})).symbol !== symbol) return {ok:false};
      if (P.stockPath(toss.url) === stock.path) {await notice(pair,`토스 ↔ 모아 · ${symbol}`);return {ok:true};}
      const result=await messageTo(pair.tossId,{type:'select',path:stock.path});
      await notice(pair,`토스에서 ${symbol} 여는 중…`);return result;
    } catch(error) {
      const text=error.message || '자동 종목 조회 연결을 확인해 주세요';
      await notice(pair,text);return {ok:false,error:text};
    }
  }
  return {ok:false};
}
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  queue=queue.then(()=>handle(message,sender)).then(respond,error=>respond({ok:false,error:error.message || '두 페이지를 새로고침해 주세요.'}));
  return true;
});
chrome.tabs.onRemoved.addListener(tabId=>{
  queue=queue.then(async()=>{
    const pair=await getPair();
    if (pair && [pair.moaId,pair.tossId].includes(tabId)) {
      await notice({...pair,enabled:false},'연결할 토스·모아 탭을 기다리고 있어요');
      await chrome.storage.session.remove('pair');
    }
  }).catch(()=>{});
});
