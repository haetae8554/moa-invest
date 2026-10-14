/* Browser adapter only: all pricing, validation and order execution live in Python. */
const $ = id => document.getElementById(id);
let side = 'BUY';
let basis = 'AMOUNT';
let historyBusy = false;
let setup = null;
let preview = null;
let busy = false;
let revision = 0;
let toastTimer;
let balanceRevision = 0;
let modeUpdating = false;
const usd = value => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'}).format(Number(value));
function toast(message) {
  $('toast').textContent = message;
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {$('toast').hidden = true;}, 9000);
}
async function api(path, body) {
  const headers = {'X-Requested-With':'fractional-buy'};
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    headers['X-CSRF-Token'] = setup?.csrfToken || '';
  }
  const response = await fetch(path, {method:body === undefined ? 'GET' : 'POST', headers,
    body:body === undefined ? undefined : JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '요청에 실패했어요.');
  return result;
}
function invalidate() {
  revision += 1;
  preview = null;
  $('review').close();
  $('price').textContent = '—';
  $('quantity').textContent = '—';
  $('stock-name').textContent = '주문할 종목을 입력해 주세요';
  $('stock-caption').textContent = '전체 주문 규모를 정하면 분할 계획을 보여드려요.';
  updateAmount();
  renderSelectedHolding();
  updateSubmit();
}
// This bridge accepts a ticker only. Broker/account/order operations are never exposed.
let symbolSyncConnected = false;
let symbolSyncEnabled = false;
let symbolSyncPaired = false;
let symbolSyncSeen = 0;
const syncTicker = value => typeof value === 'string' && /^[A-Z][A-Z0-9.-]{0,19}$/.test(value.trim().toUpperCase()) ? value.trim().toUpperCase() : null;
const postSymbolSync = data => window.postMessage({channel:'moa-symbol-sync',source:'page',...data},location.origin);
function publishSymbol() {
  const symbol=syncTicker($('symbol').value);
  if (symbol && !busy) postSymbolSync({type:'selected',symbol});
}
function selectSymbol(symbol, external=false) {
  if (busy || !syncTicker(symbol)) return false;
  const same=$('symbol').value.trim().toUpperCase() === symbol;
  $('symbol').value=symbol;
  if (!same) invalidate();
  if (external) { $('holding-search').value=''; $('holding-currency').value='USD'; }
  renderHoldings();
  if (external) [...$('holdings-list').children].find(row=>row.dataset.symbol === symbol)?.scrollIntoView({block:'nearest'});
  else publishSymbol();
  return true;
}
window.addEventListener('message',event=>{
  const message=event.data;
  if (event.source !== window || event.origin !== location.origin || message?.channel !== 'moa-symbol-sync' || message.source !== 'extension') return;
  if (message.type === 'select' && typeof message.requestId === 'string' && message.requestId.length < 80) {
    const symbol=syncTicker(message.symbol);
    const ok=Boolean(symbol && selectSymbol(symbol,true));
    postSymbolSync({type:'selected-result',requestId:message.requestId,ok,retry:busy,
      error:ok ? null : busy ? '모아 처리 완료 후 종목을 연결해요…' : '올바른 미국주식 티커가 필요해요.'});
  } else if (message.type === 'status') {
    symbolSyncSeen=Date.now(); symbolSyncConnected=message.connected === true; symbolSyncEnabled=message.enabled === true; symbolSyncPaired=message.paired === true;
    $('symbol-sync-toggle').textContent=symbolSyncConnected ? !symbolSyncPaired ? '종목 연결 설정' : symbolSyncEnabled ? '종목 연결 켜짐' : '종목 연결 꺼짐' : '토스 종목 연결';
    $('symbol-sync-toggle').parentElement.classList.toggle('connected',symbolSyncConnected && symbolSyncEnabled);
    $('symbol-sync-status').textContent=typeof message.text === 'string' ? message.text.slice(0,180) : '';
  }
});
$('symbol-sync-toggle').addEventListener('click',()=>{
  if (symbolSyncConnected && symbolSyncPaired) postSymbolSync({type:'toggle'});
  else $('symbol-sync-guide').showModal();
});
setInterval(()=>{
  if (symbolSyncConnected && Date.now()-symbolSyncSeen > 16000) {
    symbolSyncConnected=false;symbolSyncEnabled=false;
    $('symbol-sync-toggle').textContent='토스 종목 연결';
    $('symbol-sync-toggle').parentElement.classList.remove('connected');
    $('symbol-sync-status').textContent='확장 연결을 확인해 주세요';
  }
},5000);
function splitText(split, quantity = false) {
  const unit = quantity ? `${Number(split.perOrder)}주` : usd(split.perOrder);
  const parts = [];
  if (split.fullOrderCount) parts.push(`${unit} × ${split.fullOrderCount.toLocaleString()}회`);
  if (Number(split.remainder) > 0) parts.push(`마지막 ${quantity ? Number(split.remainder)+'주' : usd(split.remainder)}`);
  return parts.join(' + ');
}
function updateAmount() {
  const amount = Number($('amount').value);
  const valid = Number.isFinite(amount) && amount > 0;
  const qty = basis === 'QUANTITY';
  const label = side === 'BUY' ? '매수' : '매도';
  $('amount-label').textContent = qty ? '총주문수량' : '총주문금액';
  $('amount-prefix').textContent = qty ? '#' : '$';
  $('amount-unit').textContent = qty ? '주' : 'USD';
  $('amount').step = qty ? '0.000001' : '0.01';
  $('amount').min = qty ? '0.000001' : '0.01';
  $('total-label').textContent = `총 ${label} ${qty ? '수량' : '금액'}`;
  $('total').textContent = valid ? (qty ? `${amount.toLocaleString(undefined,{maximumFractionDigits:6})}주` : usd(amount)) : '—';
  $('order-method').textContent = `시장가 · ${qty && side === 'SELL' ? '수량' : '금액'} ${label}`;
  $('amount-hint').textContent = !qty ? '$9씩 나누고 마지막 주문에 남은 금액을 넣어요.' : side === 'BUY' ? '현재가로 총금액을 계산한 뒤 $9씩 매수해요. 실제 매수 수량은 달라질 수 있어요.' : '매번 현재가로 약 $9에 해당하는 수량을 계산해요. 주문 수량 합계는 입력한 총수량과 같아요.';
  if (valid && !qty) {
    const cents = Math.round(amount * 100);
    const split = {fullOrderCount:Math.floor(cents / 900), remainder:(cents % 900)/100, perOrder:9};
    $('split-count').textContent = `${Math.ceil(cents/900).toLocaleString()}회`;
    $('split-plan').textContent = splitText(split);
  } else {
    $('split-count').textContent = qty ? '미리보기에서 확인' : '—';
    $('split-plan').textContent = qty ? '현재가를 조회하면 분할 계획을 확인할 수 있어요.' : '전체 주문 금액을 입력해 주세요.';
  }
  document.querySelectorAll('[data-amount]').forEach((button,index) => {
    const value = (qty ? [0.1, 0.5, 1, 5] : [27, 90, 300, 900])[index];
    button.dataset.amount = value; button.textContent = qty ? `${value}주` : `$${value}`;
    button.classList.toggle('selected', value === amount);
  });
  for (const [key, value] of [['side',side], ['basis',basis]]) document.querySelectorAll(`[data-${key}]`).forEach(button => {
    const selected = button.dataset[key] === value;
    button.classList.toggle('selected', selected); button.setAttribute('aria-pressed', String(selected));
  });
}
function ready() {
  const connected = Boolean(setup?.configured && $('account').value);
  $('preview-button').disabled = !connected || busy;
  $('broker-orders').disabled = !connected || busy;
  $('mode-toggle').disabled = !setup || busy || modeUpdating;
  $('preview-button').textContent = busy ? '처리하고 있어요…' : connected ? '주문 미리보기' : '계좌 연결 후 미리보기';
}
function renderMode() {
  if (!setup) return;
  $('mode').textContent = setup.executionEnabled ? '실주문 모드' : '미리보기 전용';
  $('mode').classList.toggle('live', setup.executionEnabled);
  $('mode-toggle').setAttribute('aria-checked', String(setup.executionEnabled));
  $('mode-toggle').textContent = modeUpdating ? '변경 중…' : setup.executionEnabled ? '실주문 끄기' : '실주문 켜기';
  if (setup.configured) $('connection-copy').textContent = `${setup.credentialSource}에서 연결했어요. ` + (setup.executionEnabled ? '최종 확인 후 실제 주문이 전송돼요.' : '현재는 미리보기 전용이에요.');
  ready(); updateSubmit();
}
async function syncMode() {
  if (!setup || busy || modeUpdating) return;
  try {
    const mode = await api('/api/execution-mode');
    if (!setup || modeUpdating || mode.modeRevision < setup.modeRevision) return;
    if (mode.modeRevision !== setup.modeRevision) invalidate();
    Object.assign(setup, mode); renderMode();
  } catch (error) { /* Keep the last known state; submit always checks server state. */ }
}
function updateSubmit() {
  const expired = !preview || Date.now() >= preview.expiresTimestamp * 1000;
  $('submit-order').disabled = busy || expired || !setup?.executionEnabled || !$('ack').checked;
  $('submit-order').textContent = busy ? '전송 중… 다시 누르지 마세요' : `분할 ${preview?.side === 'SELL' ? '매도' : '매수'} 시작`;
  if (preview) $('expiry').textContent = expired ? '미리보기가 만료됐어요. 닫고 다시 확인해 주세요.' : `확인 가능 시간 ${Math.max(0, Math.ceil(preview.expiresTimestamp - Date.now()/1000))}초`;
}
async function balances() {
  const selected = $('account').value;
  const request = ++balanceRevision;
  $('balance').replaceChildren(document.createTextNode('—'));
  if (!selected) return;
  try {
    const data = await api(`/api/balances?account=${encodeURIComponent(selected)}`);
    if (request !== balanceRevision || selected !== $('account').value) return;
    $('balance').textContent = usd(data.buyingPowerUSD);
    const unit = document.createElement('small'); unit.textContent = 'USD'; $('balance').append(unit);
  } catch (error) { if (request === balanceRevision) toast(error.message); }
}
async function connect() {
  if (busy) return;
  $('connect').disabled = true;
  invalidate();
  setup = null;
  clearHoldings();
  ready();
  $('mode').textContent = '연결 확인 중';
  try {
    setup = await api('/api/setup');
    renderMode();
    $('account').replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = ''; placeholder.textContent = setup.configured ? '계좌 선택' : '계좌 연결이 필요해요';
    $('account').append(placeholder);
    for (const account of setup.accounts) {
      const option = document.createElement('option'); option.value = account.accountSeq; option.textContent = account.label;
      $('account').append(option);
    }
    $('account').value = setup.selectedAccountSeq;
    $('account').disabled = !setup.configured;
    if (!$('account').value) $('holdings-list').replaceChildren(detailLine('', '계좌를 연결하면 보유 종목을 표시해요.'));
    $('connection-title').textContent = !setup.configured ? '계좌를 연결하면 바로 시작할 수 있어요' : setup.accounts.length ? '토스증권 계좌가 연결됐어요' : '주문 가능한 계좌가 없어요';
    $('connection-copy').textContent = !setup.configured ? 'API 키를 설정한 뒤 계좌와 실제 시세를 확인해 주세요.' : `${setup.credentialSource}에서 연결했어요. ` + (setup.executionEnabled ? '최종 확인 후 실제 주문이 전송돼요.' : '현재는 미리보기 전용이에요.');
    ready(); updateAmount(); await Promise.allSettled([balances(), refreshHoldings()]);
  } catch (error) {
    $('mode').textContent = '연결 실패';
    $('connection-title').textContent = '계좌 연결을 확인해 주세요';
    $('connection-copy').textContent = error.message;
    $('account').disabled = true;
    $('holdings-list').replaceChildren(detailLine('', '계좌 연결을 확인한 뒤 새로고침해 주세요.'));
    toast(error.message);
  } finally { $('connect').disabled = false; ready(); }
}
function detailLine(label, value) {
  const row = document.createElement('p');
  row.textContent = `${label}  ${value}`;
  return row;
}
function showPreview(data) {
  preview = data;
  const label = data.side === 'BUY' ? '매수' : '매도';
  $('stock-name').textContent = data.stockName;
  $('stock-caption').textContent = `${data.symbol} · 미국주식 · USD`;
  $('price').textContent = usd(data.lastPrice);
  $('quantity').textContent = `${data.exactQuantity ? data.targetQuantity : data.estimatedQuantity}주`;
  $('split-count').textContent = `${data.split.orderCount.toLocaleString()}회${data.exactQuantity ? ' 예상' : ''}`;
  $('split-plan').textContent = splitText(data.split, data.exactQuantity);
  $('review-title').textContent = `${data.stockName} 분할 ${label}`;
  $('review-summary').replaceChildren(
    detailLine('계좌', data.accountLabel), detailLine('종목', data.symbol),
    detailLine(data.basis === 'QUANTITY' ? '목표 수량' : '총주문금액', data.basis === 'QUANTITY' ? `${data.targetQuantity}주` : usd(data.totalOrderAmount)),
    detailLine('예상 총금액', usd(data.totalOrderAmount)),
    detailLine('분할 계획', splitText(data.split, data.exactQuantity)),
    detailLine('주문 횟수', `${data.split.orderCount.toLocaleString()}회${data.exactQuantity ? ' 예상 · 시세에 따라 변동' : ''}`),
    detailLine('주문 방식', `시장가 · ${data.exactQuantity ? '수량' : '금액'} ${label}`),
  );
  const warningText = data.warnings.map(w => w.message || w.description || w.title || w.code || JSON.stringify(w)).join('\n');
  $('warnings').textContent = [data.quantityNotice, data.feeNotice, warningText].filter(Boolean).join('\n');
  $('ack').checked = false;
  $('execution-note').textContent = setup.executionEnabled ? '순차 전송해요. 일부 주문만 접수될 수 있으며 접수와 체결 완료는 달라요.' : '현재 미리보기 전용이에요. 실주문 모드를 켠 뒤 새로 미리보기해 주세요.';
  updateSubmit(); $('review').showModal();
}
async function history() {
  if (historyBusy) return;
  historyBusy = true; $('refresh-history').disabled = true;
  try {
    const [data, legacy] = await Promise.all([api('/api/batches/history'), api('/api/history')]);
    const container = $('history-list'); container.replaceChildren();
    if (!data.items.length && !legacy.items.length) {
      const empty = document.createElement('div'); empty.className = 'empty-state';
      const title = document.createElement('strong'); title.textContent = '아직 전송한 주문이 없어요';
      const text = document.createElement('p'); text.textContent = '분할 주문을 시작하면 접수 진행 상황이 표시돼요.';
      empty.append(title,text); container.append(empty);
    }
    const labels = {RUNNING:'순차 전송 중', STOPPING:'중단 요청 중', STOPPED:'남은 주문 중단', SUBMITTED:'모두 접수', UNKNOWN:'결과 확인 필요', INTERRUPTED:'실행 중단 · 확인 필요', SUBMITTING:'전송 결과 확인 필요', REJECTED:'거절로 중단'};
    for (const item of [...data.items, ...legacy.items]) {
      const p = item.preview; const batch = Boolean(item.batchId);
      const row = document.createElement('div'); row.className = 'history-row';
      const meta = document.createElement('div'); meta.className = 'history-meta';
      const title = document.createElement('strong');
      title.textContent = `${p.symbol} · ${p.side === 'SELL' ? '매도' : '매수'} · ${p.basis === 'QUANTITY' ? p.targetQuantity+'주' : usd(p.totalOrderAmount || p.orderAmount)}`;
      const progress = document.createElement('p');
      progress.textContent = batch ? `${item.submittedOrderCount.toLocaleString()}건 접수 / ${p.split.orderCount.toLocaleString()}건 계획${p.exactQuantity ? ' (예상)' : ''} · ${p.exactQuantity ? item.submittedQuantity+'주' : usd(item.submittedAmount)} 접수 요청` : '이전 단건 주문';
      const text = document.createElement('p'); text.textContent = item.message || item.result?.message || '토스증권 주문 내역에서 체결 상태를 확인해 주세요.';
      meta.append(title,progress,text);
      const state = document.createElement('span'); state.className = 'history-state' + (['UNKNOWN','INTERRUPTED','SUBMITTING'].includes(item.state) ? ' unknown' : ''); state.textContent = labels[item.state] || item.state;
      row.append(meta,state);
      if (batch && ['RUNNING','STOPPING'].includes(item.state)) {
        const stop = document.createElement('button'); stop.className = 'stop-button'; stop.textContent = '남은 주문 중단'; stop.disabled = item.state === 'STOPPING';
        stop.addEventListener('click', async () => {
          stop.disabled = true;
          try { const result = await api('/api/batches/stop', {batchId:item.batchId}); toast(result.message); }
          catch (error) { toast(error.message); }
          finally { history(); }
        }); row.append(stop);
      }
      container.append(row);
    }
  } catch (error) { $('history-list').textContent = `주문 기록을 불러오지 못했어요. ${error.message}`; }
  finally { historyBusy = false; $('refresh-history').disabled = false; }
}
let portfolio = null;
let holdingsRequest = 0;
let holdingsPending = false;
let holdingMetric = 'value';
const decimalFormat = value => value === null || value === undefined ? '—' : new Intl.NumberFormat('en-US',{maximumFractionDigits:6}).format(Number(value));
const moneyFormat = (value, currency='USD') => value === null || value === undefined ? '—' : new Intl.NumberFormat(currency === 'KRW' ? 'ko-KR' : 'en-US',{style:'currency',currency,minimumFractionDigits:currency === 'USD' ? 2 : 0,maximumFractionDigits:currency === 'USD' ? (Math.abs(Number(value)) > 0 && Math.abs(Number(value)) < 1 ? 4 : 2) : 0}).format(Number(value));
function profitText(amount, rate, currency) {
  if (amount === null || amount === undefined) return '손익 정보 없음';
  return `${Number(amount)>0 ? '+' : ''}${moneyFormat(amount,currency)}${rate === null || rate === undefined ? '' : ' ('+(Math.abs(Number(rate))*100).toFixed(2)+'%)'}`;
}
function profitClass(node, value) {
  node.classList.toggle('gain', value !== null && Number(value)>0);
  node.classList.toggle('loss', value !== null && Number(value)<0);
}
function clearHoldings() {
  holdingsRequest += 1; holdingsPending = false; portfolio = null;
  $('portfolio-total').textContent = '—'; $('portfolio-profit').textContent = '—';
  profitClass($('portfolio-profit'), null);
  $('holdings-list').replaceChildren(detailLine('', '보유 종목을 불러오고 있어요.'));
  $('selected-holding').hidden = true;
}
function selectedHolding() {
  return portfolio?.items.find(item => item.symbol.toUpperCase() === $('symbol').value.trim().toUpperCase() && item.orderable);
}
function renderSelectedHolding() {
  const item = selectedHolding();
  $('selected-holding').hidden = !item;
  if (!item) {
    if (!preview) {
      const ticker=syncTicker($('symbol').value);
      $('stock-name').textContent = ticker || '종목을 선택해 주세요';
      $('stock-caption').textContent = ticker ? '미리보기에서 종목 정보와 시세를 조회해요.' : '내 종목을 누르거나 티커를 입력해 주세요.';
      $('price').textContent = '—';
    }
    return;
  }
  $('stock-name').textContent = item.name;
  $('stock-caption').textContent = `${item.symbol} · 보유 종목`;
  $('price').textContent = moneyFormat(item.lastPrice);
  $('selected-quantity').textContent = `${decimalFormat(item.quantity)}주`;
  $('selected-average').textContent = moneyFormat(item.averagePurchasePrice);
}
function renderHoldings() {
  if (!portfolio) return;
  const currency = $('holding-currency').value;
  const summary = portfolio.summary[currency];
  $('portfolio-total').textContent = moneyFormat(summary.marketValue,currency);
  $('portfolio-profit').textContent = summary.count ? profitText(summary.profitLoss,summary.profitLossRate,currency) : '보유 종목 없음';
  profitClass($('portfolio-profit'),summary.profitLoss);
  const query = $('holding-search').value.trim().toLocaleLowerCase();
  const rows = portfolio.items.filter(item => item.currency === currency && (!query || `${item.symbol} ${item.name}`.toLocaleLowerCase().includes(query)));
  const sort = $('holding-sort').value;
  rows.sort((a,b) => sort === 'name' ? a.name.localeCompare(b.name,'ko') : (Number(b[sort === 'profit' ? 'profitLossRate' : 'marketValue'] ?? -Infinity) - Number(a[sort === 'profit' ? 'profitLossRate' : 'marketValue'] ?? -Infinity)) || a.symbol.localeCompare(b.symbol));
  const list=$('holdings-list');
  // Avoid replacing a focused row while snapshots refresh in the background.
  const focused=document.activeElement?.dataset?.symbol;
  list.replaceChildren();
  if (!rows.length) {
    const text=document.createElement('p'); text.className='list-message';
    text.textContent=query ? '검색한 보유 종목이 없어요.' : '이 통화의 보유 종목이 없어요.'; list.append(text);
  }
  for (const item of rows) {
    const row=document.createElement('button'); row.type='button'; row.className='holding-row'; row.dataset.symbol=item.symbol;
    row.setAttribute('aria-label',`${item.name} ${item.symbol} ${decimalFormat(item.quantity)}주${item.orderable ? ' 주문 종목 선택' : ' 국내주식 조회 전용'}`);
    const selected = item.symbol.toUpperCase() === $('symbol').value.trim().toUpperCase();
    row.classList.toggle('selected', selected); row.setAttribute('aria-pressed',String(selected));
    row.disabled=!item.orderable;
    const meta=document.createElement('span'); meta.className='holding-meta';
    const name=document.createElement('strong'); name.textContent=item.name; name.title=`${item.name} (${item.symbol})`;
    const quantity=document.createElement('span'); quantity.textContent=`${item.name !== item.symbol ? item.symbol+' · ' : ''}${decimalFormat(item.quantity)}주`;
    meta.append(name,quantity);
    const values=document.createElement('span'); values.className='holding-values';
    const value=document.createElement('strong'); value.textContent=moneyFormat(holdingMetric === 'value' ? item.marketValue : item.lastPrice,currency);
    const profit=document.createElement('span'); profit.textContent=profitText(item.profitLoss,item.profitLossRate,currency); profitClass(profit,item.profitLoss);
    values.append(value,profit); row.append(meta,values);
    row.addEventListener('click',() => {
      if (busy) return;
      selectSymbol(item.symbol);
      if (matchMedia('(max-width: 619px)').matches) $('symbol').focus({preventScroll:false});
    }); list.append(row);
  }
  if (focused) Array.from(list.children).find(row=>row.dataset.symbol===focused)?.focus({preventScroll:true});
  document.querySelectorAll('[data-metric]').forEach(button => {
    const active=button.dataset.metric===holdingMetric; button.classList.toggle('selected',active); button.setAttribute('aria-pressed',String(active));
  });
  $('holdings-updated').textContent=`${currency} 기준 · 수수료 전 · ${new Date(portfolio.asOf).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',second:'2-digit'})} 조회`;
  renderSelectedHolding();
}
async function refreshHoldings() {
  if (holdingsPending || !$('account').value || !setup?.configured) return;
  const request=++holdingsRequest, account=$('account').value;
  holdingsPending=true; $('refresh-holdings').disabled=true;
  try {
    const result=await api(`/api/holdings?account=${encodeURIComponent(account)}`);
    if (request!==holdingsRequest || account!==$('account').value) return;
    portfolio=result; renderHoldings();
  } catch (error) {
    if (request!==holdingsRequest) return;
    portfolio=null; $('portfolio-total').textContent='—'; $('portfolio-profit').textContent='—';
    profitClass($('portfolio-profit'),null); $('selected-holding').hidden=true;
    $('holdings-list').replaceChildren(detailLine('보유 종목 조회 실패',error.message));
    $('holdings-updated').textContent='새로고침으로 다시 조회할 수 있어요.';
  } finally {
    if (request===holdingsRequest) {holdingsPending=false; $('refresh-holdings').disabled=false;}
  }
}
$('refresh-holdings').addEventListener('click',refreshHoldings);
$('holding-search').addEventListener('input',renderHoldings);
$('holding-currency').addEventListener('change',renderHoldings);
$('holding-sort').addEventListener('change',renderHoldings);
document.querySelectorAll('[data-metric]').forEach(button=>button.addEventListener('click',()=>{holdingMetric=button.dataset.metric;renderHoldings();}));
$('order-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const version = revision;
  busy = true; ready();
  try {
    const data = await api('/api/batches/preview', {symbol:$('symbol').value, value:$('amount').value, accountSeq:$('account').value, side, basis});
    if (version === revision) showPreview(data);
  } catch (error) { toast(error.message); }
  finally { busy = false; ready(); updateSubmit(); }
});
$('submit-order').addEventListener('click', async () => {
  if (busy || !preview || $('submit-order').disabled) return;
  busy = true; ready(); updateSubmit();
  try {
    const result = await api('/api/batches/start', {batchId:preview.batchId, acknowledged:$('ack').checked});
    $('review').close(); preview = null; toast(result.message || '분할 주문을 시작했어요. 아래 주문 기록에서 진행 상황을 확인해 주세요.');
  } catch (error) {
    // A lost browser response must never offer an automatic retry.
    $('review').close(); preview = null;
    toast(`${error.message} 주문 기록을 확인해 주세요.`);
  } finally { busy = false; ready(); updateSubmit(); await history(); await Promise.allSettled([balances(), refreshHoldings()]); }
});
document.querySelectorAll('[data-side]').forEach(button => button.addEventListener('click', () => {
  side = button.dataset.side; invalidate(); updateAmount();
}));
document.querySelectorAll('[data-basis]').forEach(button => button.addEventListener('click', () => {
  if (basis === button.dataset.basis) return;
  basis = button.dataset.basis; $('amount').value = basis === 'QUANTITY' ? '1' : '90'; invalidate(); updateAmount();
}));
$('account').addEventListener('change', () => { clearHoldings(); invalidate(); ready(); balances(); refreshHoldings(); });
$('symbol').addEventListener('input', () => { invalidate(); renderHoldings(); });
$('symbol').addEventListener('change', publishSymbol);
$('amount').addEventListener('input', () => { invalidate(); updateAmount(); });
document.querySelectorAll('[data-amount]').forEach(button => button.addEventListener('click', () => {
  $('amount').value = button.dataset.amount; invalidate(); updateAmount();
}));
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => {
  if (!busy) $(button.dataset.close).close();
}));
$('review').addEventListener('cancel', event => { if (busy) event.preventDefault(); });
let credentialState = null;
let credentialSaving = false;
async function openCredentials() {
  if (credentialSaving) return;
  $('credential-form').reset();
  $('save-credentials').disabled = true;
  $('credential-status').textContent = '저장 상태 확인 중…';
  $('guide').showModal();
  try {
    credentialState = await api('/api/credentials');
    $('save-credentials').disabled = !credentialState.supported;
    $('credential-status').textContent = !credentialState.supported ? '화면에서 키 저장은 Windows에서 지원해요.' : credentialState.needsRecovery ? '이전 저장이 완료되지 않았어요. 키를 다시 등록하면 복구할 수 있어요.' : credentialState.configured ? `${credentialState.source} 사용 중 · 저장된 키는 다시 표시하지 않아요.` : '아직 등록된 키가 없어요.';
  } catch (_) { $('credential-status').textContent = '서버를 업데이트하고 다시 실행해 주세요.'; }
}
$('guide-button').addEventListener('click', openCredentials);
$('guide').addEventListener('close', () => $('credential-form').reset());
$('guide').addEventListener('cancel', event => {if (credentialSaving) event.preventDefault();});
$('credential-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (credentialSaving || !credentialState?.supported) return;
  credentialSaving = true; busy = true; invalidate(); ready();
  $('save-credentials').disabled = true;
  $('save-credentials').textContent = '연결 확인 중…';
  $('credential-status').textContent = '계좌 연결을 확인하고 이 PC에 저장하고 있어요.';
  let payload = {clientId:$('client-id').value, clientSecret:$('client-secret').value, expectedRevision:credentialState.revision};
  $('credential-form').reset();
  try {
    const response = await fetch('/api/credentials', {method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'fractional-buy','X-CSRF-Token':credentialState.csrfToken},body:JSON.stringify(payload)});
    payload = null;
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '저장에 실패했어요.');
    $('guide').close(); toast('API 키를 저장했어요. 실주문은 꺼진 상태로 연결돼요.');
  } catch (error) {
    $('credential-status').textContent = error.message;
    credentialState = await api('/api/credentials').catch(() => null);
  } finally {
    payload = null; credentialSaving = false; busy = false;
    $('credential-form').reset();
    $('save-credentials').textContent = '연결 확인 후 저장';
    $('save-credentials').disabled = !credentialState?.supported;
    await connect();
  }
});
if (location.hash === '#settings') openCredentials();
window.addEventListener('hashchange', () => {if (location.hash === '#settings') openCredentials();});
$('ack').addEventListener('change', updateSubmit);
$('connect').addEventListener('click', connect);
$('mode-toggle').addEventListener('click', async () => {
  if (!setup || busy || modeUpdating) return;
  const enabled = !setup.executionEnabled;
  const expectedRevision = setup.modeRevision;
  modeUpdating = true; busy = true; invalidate(); renderMode();
  try {
    const mode = await api('/api/execution-mode', {enabled, expectedRevision});
    Object.assign(setup, mode);
    toast(enabled ? '실주문 모드를 켰어요. 새 미리보기 후 분할 주문을 시작할 수 있어요.' : '미리보기 전용으로 변경했어요. 남은 분할 주문을 중단해요. 이미 전송한 주문은 취소되지 않아요.');
  } catch (error) { toast(`모드 변경을 확인하지 못했어요. ${error.message}`); }
  finally { modeUpdating = false; busy = false; renderMode(); await syncMode(); }
});
$('refresh-history').addEventListener('click', history);
$('broker-orders').addEventListener('click', async () => {
  $('broker-orders').disabled = true;
  $('broker-result').textContent = '주문 내역을 조회하고 있어요…';
  try {
    const data = await api(`/api/orders?account=${encodeURIComponent($('account').value)}&status=${$('order-status').value}`);
    const rows = Array.isArray(data.orders) ? data.orders : data.orders.orders || data.orders.items;
    if (!Array.isArray(rows)) throw new Error('주문 내역 응답 형식을 확인할 수 없어요.');
    $('broker-result').replaceChildren();
    if (!rows.length) $('broker-result').textContent = '해당 상태의 주문이 없어요.';
    for (const row of rows) $('broker-result').append(detailLine(`${row.symbol} · ${row.side} · ${row.status}`, `주문번호 ${row.orderId}`));
  } catch (error) { $('broker-result').textContent = error.message; }
  finally { ready(); }
});
setInterval(updateSubmit, 1000);
setInterval(syncMode, 5000);
setInterval(history, 2500);
window.addEventListener('focus', syncMode);
connect(); history();
setInterval(() => { if (!document.hidden && setup?.configured) refreshHoldings(); }, 30000);
