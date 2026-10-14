(() => {
  const P = MoaSync;
  if (P.kind(location.href) !== 'moa') return;
  const pending = new Map();
  const post = data => window.postMessage({channel:'moa-symbol-sync', source:'extension', ...data}, location.origin);
  function state() {
    return {symbol:P.symbol(document.getElementById('symbol')?.value)};
  }
  function select(symbol) {
    return new Promise(resolve => {
      const requestId = crypto.randomUUID();
      const timer = setTimeout(() => {pending.delete(requestId);resolve({ok:false,error:'모아를 새로고침해 주세요.'});},2000);
      pending.set(requestId, result => {clearTimeout(timer);pending.delete(requestId);resolve(result);});
      post({type:'select', symbol, requestId});
    });
  }
  window.addEventListener('message', async event => {
    const message = event.data;
    if (event.source !== window || event.origin !== location.origin || message?.channel !== 'moa-symbol-sync' || message.source !== 'page') return;
    if (message.type === 'selected-result') {pending.get(message.requestId)?.({ok:message.ok === true,retry:message.retry === true,error:message.error});return;}
    try {
      if (message.type === 'selected' && P.symbol(message.symbol)) {
        const result = await chrome.runtime.sendMessage({type:'moa-select',symbol:P.symbol(message.symbol)});
        if (result?.error) post({type:'status',connected:true,paired:true,enabled:true,text:result.error});
      } else if (message.type === 'toggle') {
        await chrome.runtime.sendMessage({type:'toggle'}); await status();
      }
    } catch (_) {post({type:'status',connected:false,enabled:false,text:'확장을 다시 연결해 주세요'});}
  });
  chrome.runtime.onMessage.addListener((message, _sender, respond) => {
    if (message?.type === 'inspect') respond(state());
    else if (message?.type === 'select' && P.symbol(message.symbol)) {
      select(P.symbol(message.symbol)).then(respond); return true;
    } else if (message?.type === 'status') {post(message);respond({ok:true});}
  });
  async function status() {
    try {
      const result = await chrome.runtime.sendMessage({type:'moa-status'});
      post({type:'status', connected:true, paired:Boolean(result?.paired), enabled:Boolean(result?.enabled),text:result?.text || '확장 메뉴에서 두 탭을 연결해 주세요'});
    } catch (_) {post({type:'status',connected:false,enabled:false,text:'확장을 다시 연결해 주세요'});}
  }
  status(); setInterval(status,5000);
})();
