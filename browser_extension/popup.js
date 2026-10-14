const $ = id=>document.getElementById(id);
let pair=null;
let currentWindowId;
chrome.windows.getCurrent().then(window=>{currentWindowId=window.id;});
async function request(message) {
  const result=await chrome.runtime.sendMessage(message);
  if (result?.error) throw new Error(result.error);
  return result;
}
async function load() {
  const result=await request({type:'list'}); pair=result.pair;
  for (const kind of ['toss','moa']) {
    const select=$(kind),previous=Number(select.value); select.replaceChildren();
    for (const tab of result.tabs.filter(tab=>tab.kind===kind)) {
      const option=document.createElement('option');option.value=tab.id;
      option.textContent=`${tab.title || kind} · 탭 ${tab.id}`;select.append(option);
    }
    const wanted=previous || pair?.[`${kind}Id`];
    if ([...select.options].some(option=>Number(option.value)===wanted)) select.value=wanted;
  }
  $('connect').disabled=!$('toss').value || !$('moa').value;
  $('pause').disabled=!pair;
  $('pause').textContent=pair?.enabled ? '연결 일시정지' : '연결 다시 켜기';
  $('mapping-count').textContent=`자동 조회한 종목 ${result.cacheCount}개 · 24시간 캐시`;
  $('status').textContent=pair?.text || '토스·모아를 새로고침하면 자동 연결돼요. 여러 탭을 열었다면 위에서 선택해 주세요.';
}
async function run(message) {
  document.querySelectorAll('button').forEach(button=>button.disabled=true);
  try {await request(message);await load();}
  catch(error){await load().catch(()=>{});$('status').textContent=error.message;}
  finally{for (const id of ['refresh','open-panel','close-panel','open-tab']) $(id).disabled=false;}
}
$('connect').addEventListener('click',()=>run({type:'pair',tossId:Number($('toss').value),moaId:Number($('moa').value)}));
$('pause').addEventListener('click',()=>run({type:'toggle'}));
$('refresh').addEventListener('click',()=>run({type:'refresh'}));
load().catch(error=>{$('status').textContent=error.message;});

$('open-panel').addEventListener('click',()=>{
  if (currentWindowId === undefined) return;
  chrome.sidePanel.open({windowId:currentWindowId}).then(()=>window.close()).catch(()=>{$('status').textContent='Chrome 141 이상에서 패널을 열어 주세요.';});
});
$('close-panel').addEventListener('click',()=>{
  if (currentWindowId === undefined) return;
  chrome.sidePanel.close({windowId:currentWindowId}).then(()=>window.close()).catch(()=>{$('status').textContent='열린 모아 패널이 없어요.';});
});
$('open-tab').addEventListener('click',async()=>{
  await chrome.tabs.create({url:chrome.runtime.getURL('launch.html'),windowId:currentWindowId});
  window.close();
});
