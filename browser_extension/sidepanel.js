/* The host sees ticker-only messages. Account data and keys stay in the local iframe. */
const $ = id => document.getElementById(id);
const origin = 'http://127.0.0.1:8765';
let windowId, ready=false, enabled=true, running=false, navigating=false, generation=0;
let target=null, lastApplied='', pending=null;
const send = data => $('desk').contentWindow.postMessage({channel:'moa-panel',...data},origin);
function notice(text) {
  $('status').textContent=text;
  if (ready) send({type:'status',enabled,text});
}
function loaded() {
  ready=true; $('offline').hidden=true; lastApplied=''; tick();
}
window.addEventListener('message', async event => {
  if (event.source !== $('desk').contentWindow || event.origin !== origin || event.data?.channel !== 'moa-panel') return;
  const m=event.data;
  if (m.type === 'ready') {loaded();return;}
  if (m.type === 'selected-result' && pending?.id === m.requestId) {
    if (m.ok) lastApplied=pending.symbol;
    pending=null;return;
  }
  if (m.type === 'toggle') {await toggle();return;}
  if (m.type === 'selected' && MoaSync.symbol(m.symbol) && enabled && target) {
    const seq=++generation; navigating=true;pending=null;lastApplied=m.symbol;
    try {
      const result=await chrome.runtime.sendMessage({type:'panel-select',windowId,tabId:target.tabId,path:target.path,symbol:m.symbol});
      if (seq===generation) notice(result?.error || `토스 ↔ 모아 · ${m.symbol}`);
    } catch (_) {notice('연결을 확인해 주세요.');}
    finally {navigating=false;}
  }
});
async function tick() {
  if (!ready) {send({type:'hello'});return;}
  if (running || navigating || windowId === undefined) return;
  running=true; const seq=generation;
  try {
    const result=await chrome.runtime.sendMessage({type:'panel-tick',windowId});
    if (seq!==generation) return;
    enabled=result.enabled !== false;
    $('sync').setAttribute('aria-pressed',String(enabled));
    $('sync').textContent=enabled ? '종목 연결 켜짐' : '종목 연결 꺼짐';
    target=result.tabId ? {tabId:result.tabId,path:result.path} : null;
    notice(result.error || result.text || '토스 탭에서 종목을 선택해 주세요.');
    if (enabled && MoaSync.symbol(result.symbol) && result.symbol!==lastApplied && (!pending || Date.now()-pending.at>2500)) {
      pending={id:crypto.randomUUID(),symbol:result.symbol,at:Date.now()};
      send({type:'select',symbol:result.symbol,requestId:pending.id});
    }
  } catch (_) {notice('확장을 새로고침하고 패널을 다시 열어 주세요.');}
  finally {running=false;}
}
async function toggle() {
  ++generation;pending=null;lastApplied='';
  await chrome.storage.local.set({panelSync:!enabled});await tick();
}
async function reload(settings=false) {
  await chrome.runtime.sendMessage({type:'panel-refresh'}).catch(()=>{});
  ready=false;pending=null;lastApplied='';++generation;
  $('offline').hidden=false;
  $('desk').src=origin+'/panel'+(settings ? '#settings' : '');
}
$('sync').addEventListener('click',toggle);
$('settings').addEventListener('click',()=>{ if(ready) send({type:'open-settings'}); else $('desk').src=origin+'/panel#settings'; });
$('reload').addEventListener('click',()=>reload());
$('retry').addEventListener('click',()=>reload());
$('close').addEventListener('click', async()=>{
  try {await chrome.sidePanel.close({windowId});}
  catch (_) {notice('Chrome 패널 위쪽의 닫기 버튼을 눌러 주세요.');}
});
chrome.windows.getCurrent().then(window=>{windowId=window.id;tick();});
setInterval(tick,1500);
