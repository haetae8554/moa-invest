/* Only selected ticker/status cross the extension iframe boundary. */
(() => {
  if (location.pathname !== '/panel' || window.parent === window) return;
  document.body.classList.add('panel-mode');
  document.querySelector('.brand').href='/panel';
  const origin = 'chrome-extension://kidibaplcnnchoajokdjnalihnlhhibl';
  window.addEventListener('message', event => {
    const m=event.data;
    if (event.source === window.parent && event.origin === origin && m?.channel === 'moa-panel') {
      if (m.type === 'hello') parent.postMessage({channel:'moa-panel',type:'ready'},origin);
      if (m.type === 'open-settings') document.getElementById('guide-button').click();
      if (m.type === 'select' && typeof m.symbol === 'string' && /^[A-Z][A-Z0-9.-]{0,19}$/.test(m.symbol) && typeof m.requestId === 'string' && m.requestId.length < 80)
        window.postMessage({channel:'moa-symbol-sync',source:'extension',type:'select',symbol:m.symbol,requestId:m.requestId}, location.origin);
      if (m.type === 'status') window.postMessage({channel:'moa-symbol-sync',source:'extension',type:'status',connected:true,paired:true,enabled:m.enabled === true,text:String(m.text || '').slice(0,180)}, location.origin);
    }
    if (event.source === window && event.origin === location.origin && m?.channel === 'moa-symbol-sync' && m.source === 'page') {
      if (m.type === 'selected' && typeof m.symbol === 'string' && /^[A-Z][A-Z0-9.-]{0,19}$/.test(m.symbol)) parent.postMessage({channel:'moa-panel',type:'selected',symbol:m.symbol},origin);
      if (m.type === 'toggle') parent.postMessage({channel:'moa-panel',type:'toggle'},origin);
      if (m.type === 'selected-result') parent.postMessage({channel:'moa-panel',type:'selected-result',requestId:m.requestId,ok:m.ok === true,retry:m.retry === true},origin);
    }
  });
  parent.postMessage({channel:'moa-panel',type:'ready'},origin);
})();
