/* Optional research cards. Settings only are persisted; holdings stay in memory. */
(() => {
  'use strict';
  const IDS = ['fear', 'news', 'portfolio', 'chart'];
  const TITLES = {fear:'공포·탐욕', news:'종목 뉴스', portfolio:'보유 비중', chart:'이동평균'};
  const KEY = 'moa.research.v1';
  function preferences(raw) {
    const value = raw && typeof raw === 'object' ? raw : {};
    const order = [...new Set((Array.isArray(value.order) ? value.order : []).filter(id => IDS.includes(id)))];
    return {order:[...order, ...IDS.filter(id => !order.includes(id))],
      enabled:Object.fromEntries(IDS.map(id => [id, value.enabled?.[id] !== false])),
      wide:Object.fromEntries(IDS.map(id => [id, value.wide?.[id] === true])),
      position:value.position === 'bottom' ? 'bottom' : 'top', autoNews:value.autoNews === true};
  }
  function ticker(value) {
    const s = typeof value === 'string' ? value.trim().toUpperCase() : '';
    return /^[A-Z][A-Z0-9.-]{0,19}$/.test(s) ? s : '';
  }
  function newsUrl(symbol) { return ticker(symbol) ? `https://saveticker.com/news/search?q=${encodeURIComponent(ticker(symbol))}` : null; }
  function allocation(items, currency) {
    const rows = items.filter(row => row.currency === currency);
    const valid = key => rows.every(row => row[key] !== null && row[key] !== undefined && row[key] !== '' && Number.isFinite(Number(row[key])) && Number(row[key]) >= 0);
    const total = valid('marketValue') ? rows.reduce((sum, row) => sum + Number(row.marketValue), 0) : null;
    const purchase = valid('purchaseAmount') ? rows.reduce((sum, row) => sum + Number(row.purchaseAmount), 0) : null;
    return {total, purchase, rows:rows.map(row => ({...row, weight:total > 0 ? Number(row.marketValue) / total * 100 : null}))
      .sort((a,b) => (b.weight ?? -1) - (a.weight ?? -1))};
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports = {preferences, ticker, newsUrl, allocation}; return; }
  const $ = id => document.getElementById(id);
  let saved;
  try { saved = JSON.parse(localStorage.getItem(KEY)); } catch (_) {}
  let prefs = preferences(saved), portfolio = null, currency = 'USD', symbol = '';
  let newsWindow = null, lastNews = '', chartTimer, fearTimer, newsTimer, dragId;
  const requests = new Map();
  let chartValue = null, fearValue = null;
  const money = (n,c='USD') => n === null || n === undefined ? '—' : new Intl.NumberFormat('ko-KR',{style:'currency',currency:c,maximumFractionDigits:c==='USD'?2:0}).format(Number(n));
  const pct = n => `${Number(n)>0?'+':''}${Number(n).toFixed(1)}%`;
  const date = value => new Date(value).toLocaleString('ko-KR',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(prefs)); }
    catch (_) { $('research-status').textContent = '설정을 저장하지 못했어요. 이 화면에서만 적용돼요.'; }
  }
  function cancel(id) { requests.get(id)?.abort(); requests.delete(id); }
  async function request(id, path) {
    cancel(id);
    const controller = new AbortController(); requests.set(id, controller);
    try {
      const response = await fetch(path,{headers:{'X-Requested-With':'fractional-buy'},signal:controller.signal});
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || '조회하지 못했어요.');
      if (requests.get(id) !== controller || !prefs.enabled[id]) return null;
      return value;
    } finally { if (requests.get(id) === controller) requests.delete(id); }
  }
  function link(text, href) {
    const a=node('a',text,'research-link'); a.href=href; a.target='_blank'; a.rel='noopener noreferrer'; return a;
  }
  function spark(points, label) {
    const values=points.map(p=>p.value).filter(Number.isFinite);
    if (values.length<2) return node('span','');
    const ns='http://www.w3.org/2000/svg', svg=document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox','0 0 300 54'); svg.setAttribute('role','img'); svg.setAttribute('aria-label',label); svg.classList.add('research-spark');
    const lo=Math.min(...values), range=Math.max(...values)-lo || 1;
    const line=document.createElementNS(ns,'polyline');
    line.setAttribute('points', values.map((v,i)=>`${i/(values.length-1)*296+2},${50-(v-lo)/range*46}`).join(' '));
    svg.append(line); return svg;
  }
  function body(id) { return $(`research-${id}-body`); }
  function empty(id,text) { body(id).replaceChildren(node('p',text,'research-note')); }
  function renderFear() {
    const data=fearValue, target=body('fear'); target.replaceChildren();
    if (!data || data.score === undefined) target.append(node('p','지수를 불러오지 못했어요. 원본에서 확인해 주세요.','research-note'));
    else {
      const headline=node('div',undefined,'research-headline');
      headline.append(node('strong',Number(data.score).toFixed(0)),node('span',data.rating)); target.append(headline);
      const gauge=node('meter'); gauge.min=0;gauge.max=100;gauge.value=data.score;gauge.setAttribute('aria-label','공포·탐욕 지수'); target.append(gauge);
      const delta=data.previousClose === null ? '' : `전일 대비 ${data.score-data.previousClose>0?'+':''}${(data.score-data.previousClose).toFixed(1)} · `;
      target.append(node('p',`${delta}${date(data.asOf)} 기준`,'research-note'));
      target.append(spark(data.history,'공포·탐욕 지수 최근 추이'));
      if (data.stale || data.unavailable) target.append(node('p','이전 데이터 · 최신 값은 원본에서 확인','research-stale'));
    }
    target.append(link('CNN 원본 ↗','https://www.cnn.com/markets/fear-and-greed'));
    target.append(node('p','미국 시장 심리 · 실험적 연결','research-note'));
  }
  async function loadFear() {
    clearTimeout(fearTimer);
    if (!prefs.enabled.fear) return;
    try { const data=await request('fear','/api/research/fear-greed'); if(data) { fearValue=data; renderFear(); } }
    catch(error) { if(error.name!=='AbortError' && prefs.enabled.fear) { if(fearValue) fearValue={...fearValue,stale:true,unavailable:true}; renderFear(); } }
    finally { clearTimeout(fearTimer); if(prefs.enabled.fear) fearTimer=setTimeout(()=>{ if(!document.hidden) loadFear(); else fearTimer=setTimeout(loadFear,900000); },900000); }
  }
  function renderPortfolio() {
    if (!prefs.enabled.portfolio) return;
    if (!portfolio) { empty('portfolio','계좌를 연결하면 비중을 보여드려요.'); return; }
    const data=allocation(portfolio.items,currency), target=body('portfolio');
    target.replaceChildren();
    const totals=node('dl',undefined,'research-totals');
    for (const [title,value] of [['평가금',data.total],['매입금',data.purchase]]) {
      const row=node('div');row.append(node('dt',title),node('dd',money(value,currency)));totals.append(row);
    }
    target.append(totals);
    if (!data.rows.length) target.append(node('p','이 통화의 보유 종목이 없어요.','research-note'));
    if (data.total === null) target.append(node('p','일부 평가금이 없어 비중을 계산하지 않았어요.','research-note'));
    const list=node('div',undefined,'research-allocation');
    for(const row of data.rows) {
      const line=node('div',undefined,'research-weight'); const label=node('div');
      label.append(node('span',row.name || row.symbol),node('strong',row.weight===null?'—':`${row.weight.toFixed(1)}%`));
      const bar=node('meter');bar.min=0;bar.max=100;bar.value=row.weight??0;bar.setAttribute('aria-label',`${row.name || row.symbol} 비중`);
      if(row.weight===null) bar.hidden=true;
      line.append(label,bar);list.append(line);
    }
    target.append(list,node('p',`${currency} 보유 주식 기준 · 현금 제외 · ${date(portfolio.asOf)} 조회`,'research-note'));
  }
  function renderChart() {
    const data=chartValue;
    if(!data || data.symbol!==symbol) { empty('chart',symbol?'일봉을 불러오고 있어요.':'종목을 선택해 주세요.'); return; }
    const target=body('chart');target.replaceChildren();
    const headline=node('div',undefined,'research-headline');headline.append(node('strong',data.symbol),node('span',money(data.lastClose,data.currency)));target.append(headline);
    target.append(spark(data.history,'수정 일봉 가격 추이'));
    const table=node('table',undefined,'research-averages');
    const head=node('tr');for(const text of ['기간','평균 가격','가격 차이'])head.append(node('th',text));
    const thead=node('thead');thead.append(head);table.append(thead);
    const tbody=node('tbody');
    for(const item of data.averages) {
      const row=node('tr'); if(item.period===120) row.className='research-key-row';
      row.append(node('th',`${item.period}일`),node('td',item.value===null?'자료 부족':money(item.value,data.currency)),node('td',item.distancePct===null?'—':pct(item.distancePct)));tbody.append(row);
    }
    table.append(tbody);target.append(table,node('p',`${data.barDate} 일봉 기준 · 당일 봉은 변동 가능`,'research-note'));
    const detail=node('details'); detail.append(node('summary','120일선이란?'),node('p','최근 120거래일의 수정 종가 평균이에요. 가격 차이는 최신 일봉 가격과 평균의 거리예요.','research-note'));target.append(detail);
  }
  async function loadChart() {
    clearTimeout(chartTimer);
    if(!prefs.enabled.chart || !symbol) return;
    const requested=symbol;
    try { const data=await request('chart',`/api/research/chart?symbol=${encodeURIComponent(requested)}`); if(data && requested===symbol){chartValue=data;renderChart();} }
    catch(error) { if(error.name!=='AbortError' && prefs.enabled.chart && requested===symbol) empty('chart',error.message); }
  }
  function renderNews() {
    const target=body('news');target.replaceChildren();
    target.append(node('strong',symbol || '종목을 선택해 주세요.','research-symbol'));
    const open=node('button','뉴스 창 열기 ↗','quiet-button');open.type='button';open.disabled=!symbol;open.addEventListener('click',openNews);target.append(open);
    const label=node('label',undefined,'research-check');const check=node('input');check.type='checkbox';check.checked=prefs.autoNews;
    check.addEventListener('change',()=>{prefs.autoNews=check.checked;save();syncNews();});label.append(check,document.createTextNode('열린 창에 종목 자동 연결'));target.append(label);
    target.append(node('p','세이브티커에서 관련 뉴스를 확인해요.','research-note'));
    const status=node('p','', 'research-note');status.id='research-news-status';target.append(status);
  }
  function openNews() {
    const url=newsUrl(symbol);if(!url) return;
    try {
      if(!newsWindow || newsWindow.closed) {
        newsWindow=window.open('about:blank','_blank');
        if(!newsWindow) throw new Error('popup');
        // The external page never gets an opener into the account/order UI.
        newsWindow.opener=null;
      }
      newsWindow.location.href=url;lastNews=symbol;newsWindow.focus();
      $('research-news-status').textContent='뉴스 창을 연결했어요.';
    } catch(_) { newsWindow=null; $('research-news-status').textContent='팝업을 허용한 뒤 다시 열어 주세요.'; }
  }
  function syncNews() {
    if(!prefs.enabled.news || !prefs.autoNews || !symbol || symbol===lastNews || !newsWindow) return;
    try {
      if(newsWindow.closed) {newsWindow=null;return;}
      newsWindow.location.href=newsUrl(symbol);lastNews=symbol;
    } catch(_) { newsWindow=null; $('research-news-status').textContent='자동 연결이 끊겼어요. 뉴스 창을 다시 열어 주세요.'; }
  }
  function select(value) {
    const next=ticker(value);if(next===symbol) return;
    symbol=next;chartValue=null;cancel('chart');clearTimeout(chartTimer);clearTimeout(newsTimer);
    if(prefs.enabled.chart) {renderChart();if(symbol)chartTimer=setTimeout(loadChart,450);}
    if(prefs.enabled.news) {renderNews();newsTimer=setTimeout(syncNews,450);}
  }
  function layout() {
    for(const id of prefs.order) {
      const card=$(`research-${id}`);card.hidden=!prefs.enabled[id];card.classList.toggle('research-wide',prefs.wide[id]);$('research-cards').append(card);
    }
    const region=$('research-tools'), workspace=$('buy');
    if(prefs.position==='bottom') workspace.after(region);else workspace.before(region);
    $('research-empty').hidden=IDS.some(id=>prefs.enabled[id]);
  }
  function move(id,delta) {
    const visible=prefs.order.filter(key=>prefs.enabled[key]), index=visible.indexOf(id), other=visible[index+delta];
    if(!other)return;
    const a=prefs.order.indexOf(id), b=prefs.order.indexOf(other);[prefs.order[a],prefs.order[b]]=[prefs.order[b],prefs.order[a]];save();layout();
    $(`research-${id}`).querySelector(`[data-move="${delta}"]`).focus();
  }
  function toggle(id,enabled) {
    prefs.enabled[id]=enabled;save();layout();
    if(!enabled) {cancel(id);if(id==='fear')clearTimeout(fearTimer);if(id==='chart')clearTimeout(chartTimer);if(id==='news')clearTimeout(newsTimer);return;}
    if(id==='fear'){empty('fear','지수를 불러오고 있어요.');loadFear();}
    if(id==='chart'){renderChart();loadChart();}
    if(id==='portfolio')renderPortfolio();
    if(id==='news'){renderNews();syncNews();}
  }
  const region=node('section',undefined,'research-tools');region.id='research-tools';region.setAttribute('aria-label','투자 도구');
  const toolbar=node('div',undefined,'section-label');toolbar.append(node('h2','투자 도구'));
  const settings=node('details',undefined,'research-settings');settings.append(node('summary','도구 설정'));
  const options=node('div',undefined,'research-options');
  for(const id of IDS) {
    const label=node('label',undefined,'research-check'), check=node('input');check.type='checkbox';check.checked=prefs.enabled[id];check.setAttribute('role','switch');check.setAttribute('aria-label',`${TITLES[id]} 켜기`);
    check.addEventListener('change',()=>toggle(id,check.checked));label.append(check,document.createTextNode(TITLES[id]));options.append(label);
  }
  const placeLabel=node('label','도구 위치 '),place=node('select');place.setAttribute('aria-label','투자 도구 위치');
  for(const [value,text] of [['top','주문 위'],['bottom','주문 아래']]){const option=node('option',text);option.value=value;place.append(option);}place.value=prefs.position;
  place.addEventListener('change',()=>{prefs.position=place.value;save();layout();});placeLabel.append(place);options.append(placeLabel);
  settings.append(options);toolbar.append(settings);region.append(toolbar);
  const status=node('p','','research-note');status.id='research-status';status.setAttribute('role','status');region.append(status);
  const cards=node('div',undefined,'research-grid');cards.id='research-cards';region.append(cards);
  const emptyState=node('p','도구 설정에서 필요한 기능을 켜 주세요.','research-note');emptyState.id='research-empty';region.append(emptyState);
  $('buy').before(region);
  for(const id of IDS) {
    const card=node('article',undefined,'research-card');card.id=`research-${id}`;
    const head=node('div',undefined,'research-card-header'),title=node('h3',TITLES[id]);title.id=`research-title-${id}`;card.setAttribute('aria-labelledby',title.id);head.append(title);
    const controls=node('div',undefined,'research-card-controls');
    const handle=node('span','⠿','research-drag');handle.draggable=true;handle.title='끌어서 순서 변경';
    handle.addEventListener('dragstart',event=>{dragId=id;event.dataTransfer.setData('text/plain',id);event.dataTransfer.effectAllowed='move';});
    handle.addEventListener('dragend',()=>{dragId=null;});controls.append(handle);
    card.addEventListener('dragover',event=>{if(dragId)event.preventDefault();});
    card.addEventListener('drop',event=>{event.preventDefault();if(!dragId || dragId===id)return;const from=dragId;prefs.order=prefs.order.filter(key=>key!==from);prefs.order.splice(prefs.order.indexOf(id),0,from);dragId=null;save();layout();});
    for(const [delta,text] of [[-1,'↑'],[1,'↓']]) {const button=node('button',text);button.type='button';button.dataset.move=delta;button.setAttribute('aria-label',`${TITLES[id]} ${delta<0?'앞으로':'뒤로'} 이동`);button.addEventListener('click',()=>move(id,delta));controls.append(button);}
    const width=node('button','넓게');width.type='button';width.setAttribute('aria-label',`${TITLES[id]} 넓게 보기`);width.setAttribute('aria-pressed',String(prefs.wide[id]));width.addEventListener('click',()=>{prefs.wide[id]=!prefs.wide[id];width.setAttribute('aria-pressed',String(prefs.wide[id]));save();layout();});controls.append(width);
    head.append(controls);card.append(head);
    const content=node('div',undefined,'research-card-body');content.id=`research-${id}-body`;content.setAttribute('aria-live','polite');card.append(content);
    if(id==='fear'||id==='chart') {const refresh=node('button','새로고침','text-button research-refresh');refresh.type='button';refresh.addEventListener('click',id==='fear'?loadFear:loadChart);card.append(refresh);}
    cards.append(card);
  }
  window.MoaResearch={select,update(data,selectedCurrency){portfolio=data;currency=selectedCurrency;renderPortfolio();}};
  layout();renderPortfolio();renderNews();renderChart();
  if(prefs.enabled.fear){empty('fear','지수를 불러오고 있어요.');loadFear();}
  window.addEventListener('pagehide',()=>{clearTimeout(chartTimer);clearTimeout(fearTimer);clearTimeout(newsTimer);for(const id of requests.keys())cancel(id);});
})();
