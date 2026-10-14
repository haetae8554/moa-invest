/* Shared validation; no broker API or order data is part of this protocol. */
(() => {
  function symbol(value) {
    if (typeof value !== 'string') return null;
    const result = value.trim().toUpperCase();
    return /^[A-Z][A-Z0-9.-]{0,19}$/.test(result) ? result : null;
  }
  function kind(value) {
    try {
      const url = new URL(value);
      if (url.username || url.password) return null;
      if (url.protocol === 'https:' && !url.port && ['tossinvest.com','www.tossinvest.com'].includes(url.hostname)) return 'toss';
      if (url.protocol === 'http:' && url.port === '8765' && ['127.0.0.1','localhost'].includes(url.hostname) && url.pathname === '/') return 'moa';
    } catch (_) { /* Not a URL. */ }
    return null;
  }
  function stockPath(value) {
    if (kind(value) !== 'toss') return null;
    const match = new URL(value).pathname.match(/^\/stocks\/([A-Za-z0-9_-]{1,40})(?:\/|$)/);
    return match ? `/stocks/${match[1]}/order` : null;
  }
  function validPath(value) {
    return typeof value === 'string' && /^\/stocks\/[A-Za-z0-9_-]{1,40}\/order$/.test(value);
  }
  const api = {symbol, kind, stockPath, validPath};
  if (typeof module !== 'undefined') module.exports = api;
  else globalThis.MoaSync = api;
})();
