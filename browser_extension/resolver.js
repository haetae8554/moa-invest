/* Public stock metadata only. Never sends account credentials or cookies. */
(() => {
  const P = typeof module !== 'undefined' ? require('./protocol.js') : MoaSync;
  function parse(payload, key, by) {
    const item=payload?.result;
    const symbol=P.symbol(item?.symbol), code=item?.code;
    if (!symbol || typeof code !== 'string' || !/^[A-Za-z0-9_-]{1,40}$/.test(code)) throw new Error('종목 정보 응답을 확인할 수 없어요.');
    if ((by === 'symbol' && symbol !== key) || (by === 'code' && code !== key)) throw new Error('조회한 종목과 응답이 달라 연결을 멈췄어요.');
    return {symbol,path:`/stocks/${code}/order`};
  }
  function create({fetch:request,read,write,now=Date.now}) {
    let blockedUntil=0;
    let blockedMessage='';
    const ttl=24*60*60*1000;
    async function resolve(key,by) {
      if (!['symbol','code'].includes(by) || typeof key !== 'string' ||
          (by === 'symbol' ? P.symbol(key) !== key : !/^[A-Za-z0-9_-]{1,40}$/.test(key))) throw new Error('올바른 종목 식별자가 필요해요.');
      const stored=await read();
      const entries=(Array.isArray(stored) ? stored : []).filter(row=>P.symbol(row?.symbol) === row?.symbol && P.validPath(row?.path) && Number.isFinite(row.checkedAt) && now()-row.checkedAt < ttl && row.checkedAt <= now());
      const matches=entries.filter(row=>by === 'symbol' ? row.symbol === key : row.path === `/stocks/${key}/order`);
      if (matches.length === 1) return matches[0];
      if (now() < blockedUntil) {
        const error=new Error(blockedMessage || '자동 종목 조회가 잠시 중단됐어요. 잠시 후 다시 선택해 주세요.');
        error.requiresRefresh=blockedUntil === Infinity;throw error;
      }
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),6000);
      try {
        const response=await request(`https://wts-info-api.tossinvest.com/api/v2/stock-infos/code-or-symbol/${encodeURIComponent(key)}`,
          {method:'GET',credentials:'omit',redirect:'error',headers:{Accept:'application/json'},signal:controller.signal});
        if (!response.ok) {
          const error=new Error(`토스 종목 자동 조회 실패 (${response.status}). 확장 권한과 토스 연결을 확인해 주세요.`);
          error.requiresRefresh=[401,403,429].includes(response.status);throw error;
        }
        const result={...parse(await response.json(),key,by),checkedAt:now()};
        const updated=entries.filter(row=>row.symbol !== result.symbol && row.path !== result.path);
        updated.push(result);await write(updated.slice(-1000));
        return result;
      } catch (error) {
        blockedUntil=error.requiresRefresh ? Infinity : now()+30000;
        blockedMessage=error.message;
        if (error.name === 'AbortError') throw new Error('종목 자동 조회 시간이 초과됐어요. 잠시 후 다시 선택해 주세요.');
        throw error;
      } finally {clearTimeout(timer);}
    }
    return {resolve,clear:async()=>{blockedUntil=0;blockedMessage='';await write([]);}};
  }
  const api={create,parse};
  if (typeof module !== 'undefined') module.exports=api;
  else globalThis.MoaStockResolver=api;
})();
