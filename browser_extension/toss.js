(() => {
  const P = MoaSync;
  let last = '', running = false, retryAt = 0;
  function scan() {
    return {path:P.stockPath(location.href)};
  }
  async function tick(force = false) {
    if (running) return;
    running = true;
    try {
      const state = await chrome.runtime.sendMessage({type:'toss-config'});
      if (!state?.enabled) { last = ''; retryAt=0; return; }
      const data = scan(), signature = JSON.stringify(data);
      if (force || signature !== last || (retryAt && Date.now() >= retryAt)) {
        last = signature;
        retryAt=0;
        const result=await chrome.runtime.sendMessage({type:'toss-route', ...data});
        if (result?.retry) last='';
        if (result?.retryAfterMs) retryAt=Date.now()+Math.max(30000,result.retryAfterMs);
      }
    } catch (_) { /* Extension reload/disconnection: never interact with orders. */ }
    finally { running = false; }
  }
  chrome.runtime.onMessage.addListener((message, _sender, respond) => {
    if (message?.type === 'inspect') {
      respond(scan());
    } else if (message?.type === 'select' && P.validPath(message.path)) {
      if (P.stockPath(location.href) !== message.path) {
        // Only stock navigation anchors are eligible. Never click form controls.
        const anchor = [...document.querySelectorAll('a[href*="/stocks/"]')]
          .find(node => P.stockPath(node.href) === message.path && node.getClientRects().length && !node.target);
        respond({ok:true});
        if (anchor) anchor.click();
        else location.assign(new URL(message.path, location.origin).href);
      } else respond({ok:true});
    }
  });
  setInterval(tick, 1200);
  tick();
})();
