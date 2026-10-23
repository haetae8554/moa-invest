const test = require('node:test');
const assert = require('node:assert/strict');
const {preferences,allocation,newsTarget,newsUrl} = require('../order_ui/static/research.js');
const fs=require('node:fs');
const vm=require('node:vm');

const relations={GOOW:{kind:'stock',symbol:'GOOGL',name:'알파벳 A',newsQuery:'GOOGL'},
  QDTE:{kind:'index',symbol:'NDX',name:'나스닥100',newsQuery:'나스닥100'},
  XDTE:{kind:'index',symbol:'SPX',name:'S&P 500',newsQuery:'S&P 500'}};

function screen(saved={},metadataFailure=false) {
  const ids=new Map(), timers=new Map(), calls=[], writes=[], popups=[];let seq=0;
  class Element {
    constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.events={};this.hidden=false;this.classList={toggle(){},add(){}};}
    set id(value){this._id=value;ids.set(value,this);}get id(){return this._id;}
    append(...children){this.children.push(...children);}before(){}after(){}focus(){}
    replaceChildren(...children){this.children=children;}
    setAttribute(key,value){this.attributes[key]=value;}
    addEventListener(key,fn){this.events[key]=fn;}
    dataset={};
  }
  const buy=new Element('div');buy.id='buy';
  const document={hidden:false,getElementById:id=>ids.get(id),createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag),createTextNode:text=>({textContent:text})};
  const localStorage={getItem:()=>JSON.stringify(saved),setItem:(_,value)=>writes.push(JSON.parse(value))};
  const win={addEventListener(){},open(url){const result={closed:false,focus(){},opener:win};let href=url;
    result.location={get href(){return href;},set href(value){assert.equal(result.opener,null);href=value;}};popups.push(result);return result;}};
  vm.runInNewContext(fs.readFileSync('order_ui/static/research.js','utf8'),{
    window:win,document,localStorage,AbortController,Intl,Date,console,
    setTimeout(fn,ms){const id=++seq;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},
    fetch(path,options){
      if(path==='/api/research/symbols')return Promise.resolve({ok:!metadataFailure,json:async()=>metadataFailure?{error:'metadata unavailable'}:relations});
      return new Promise(resolve=>calls.push({path,options,resolve}));
    }
  });
  function descendants(root){return [root,...(root.children||[]).flatMap(descendants)];}
  const all=()=>descendants(ids.get('research-tools'));
  return {win,ids,calls,writes,timers,popups,
    text(id){return descendants(ids.get(id)).map(e=>e.textContent||'').join(' ');},
    chartBasis(value){const input=ids.get('research-chart-basis');input.value=value;input.events.change();},
    newsBasis(value){const input=ids.get('research-news-basis');input.value=value;input.events.change();},
    fearSource(value){const input=ids.get('research-fear-source');input.value=value;input.events.change();},
    toggle(title,checked){const input=all().find(e=>e.attributes?.['aria-label']===`${title} 켜기`);input.checked=checked;input.events.change();},
    newsButton(){return ids.get('research-news-body').children.find(e=>e.tag==='button'&&e.textContent==='뉴스 창 열기 ↗');},
    autoNews(checked){const check=descendants(ids.get('research-news-body')).find(e=>e.tag==='input'&&e.type==='checkbox');check.checked=checked;check.events.change();},
    async run(ms){for(const [id,timer] of [...timers])if(timer.ms===ms){timers.delete(id);await timer.fn();}}
  };
}
test('settings roundtrip preserves every independent toggle, order, width and placement',()=>{
  const value={enabled:{fear:false,news:true,portfolio:false,chart:true},order:['chart','news','fear','portfolio'],wide:{chart:true},position:'bottom',autoNews:true};
  const result=preferences(JSON.parse(JSON.stringify(preferences(value))));
  assert.deepEqual(result.enabled,value.enabled);assert.deepEqual(result.order,value.order);
  assert.equal(result.wide.chart,true);assert.equal(result.position,'bottom');assert.equal(result.autoNews,true);
});
test('malformed settings cannot inject cards or duplicate the layout',()=>{
  assert.deepEqual(preferences({order:['news','news','<script>']}).order,['news','fear','portfolio','chart']);
  assert.equal(preferences(null).autoNews,false);assert.equal(preferences({position:'bad'}).position,'top');
  assert.equal(preferences(null).chartBasis,'underlying');
  assert.equal(preferences({chartBasis:'self'}).chartBasis,'self');
  assert.equal(preferences({chartBasis:'evil'}).chartBasis,'underlying');
  assert.equal(preferences({fearSource:'crypto',newsBasis:'evil'}).fearSource,'auto');
  assert.equal(preferences(null).newsBasis,'underlying');
});

function chartResponse(selectedSymbol,symbol,basis='underlying') {
  return {selectedSymbol,symbol,basis,underlying:selectedSymbol!==symbol||selectedSymbol==='GOOW'?{symbol:'GOOGL',name:'알파벳 A'}:null,
    lastClose:'200',currency:'USD',barDate:'2026-10-23',history:[],averages:[{period:120,value:'140.5',distancePct:'42.35'}]};
}

test('chart labels underlying prices explicitly and self switch persists without changing selection',async()=>{
  const h=screen({enabled:{fear:false}});
  h.win.MoaResearch.select('GOOW');const pending=h.run(450);
  assert.match(h.calls[0].path,/symbol=GOOW&basis=underlying$/);
  h.calls[0].resolve({ok:true,json:async()=>chartResponse('GOOW','GOOGL')});await pending;
  assert.match(h.text('research-chart-body'),/선택 GOOW → 지표 GOOGL · 알파벳 A/);
  assert.match(h.text('research-chart-body'),/주문 종목은 GOOW로 유지/);
  assert.match(h.text('research-chart-body'),/\$140\.50/);
  h.chartBasis('self');assert.match(h.calls[1].path,/symbol=GOOW&basis=self$/);
  h.calls[1].resolve({ok:true,json:async()=>chartResponse('GOOW','GOOW','self')});
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(h.text('research-chart-body'),/GOOW 자체 가격 기준/);
  assert.equal(h.writes.at(-1).chartBasis,'self');
  assert.match(h.text('research-news-body'),/GOOW/);
  const restored=screen(h.writes.at(-1));
  assert.equal(restored.ids.get('research-chart-basis').value,'self');
});

test('changing chart basis or selection discards late results and never falls back on failure',async()=>{
  const h=screen({enabled:{fear:false}});
  h.win.MoaResearch.select('GOOW');const old=h.run(450);
  h.chartBasis('self');assert.equal(h.calls[0].options.signal.aborted,true);
  h.calls[1].resolve({ok:true,json:async()=>chartResponse('GOOW','GOOW','self')});
  await new Promise(resolve=>setImmediate(resolve));
  const current=h.ids.get('research-chart-body').children;
  h.calls[0].resolve({ok:true,json:async()=>chartResponse('GOOW','GOOGL')});await old;
  assert.equal(h.ids.get('research-chart-body').children,current);
  h.chartBasis('underlying');
  h.win.MoaResearch.select('AVGW');assert.equal(h.calls[2].options.signal.aborted,true);
  const latest=h.run(450);
  h.calls[3].resolve({ok:false,json:async()=>({error:'AVGO 일봉 데이터를 확인할 수 없습니다.'})});await latest;
  h.calls[2].resolve({ok:true,json:async()=>chartResponse('GOOW','GOOGL')});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.text('research-chart-body'),' AVGO 일봉 데이터를 확인할 수 없습니다.');
  assert.equal(h.calls.length,4);
});
test('allocation separates currencies and never uses only the filtered visible rows',()=>{
  const rows=[{symbol:'A',currency:'USD',marketValue:'60',purchaseAmount:'50'}, {symbol:'B',currency:'USD',marketValue:'40',purchaseAmount:'30'}, {symbol:'C',currency:'KRW',marketValue:'10000',purchaseAmount:'9000'}];
  const result=allocation(rows,'USD');assert.equal(result.total,100);assert.equal(result.purchase,80);
  assert.deepEqual(result.rows.map(r=>r.weight),[60,40]);assert.equal(allocation(rows,'KRW').rows[0].weight,100);
});
test('missing price, empty portfolio and zero total never masquerade as 100 percent',()=>{
  for(const value of [null,undefined,'','  ',true,false,[],'NaN','-1']) {
    const result=allocation([{currency:'USD',marketValue:value},{currency:'USD',marketValue:'10'}],'USD');
    assert.equal(result.total,null);assert.ok(result.rows.every(r=>r.weight===null));
  }
  assert.deepEqual(allocation([],'USD'),{total:0,purchase:0,rows:[]});
  assert.equal(allocation([{currency:'USD',marketValue:'0'}],'USD').rows[0].weight,null);
  const overflow=allocation([{currency:'USD',marketValue:'1e308'},{currency:'USD',marketValue:'1e308'}],'USD');
  assert.equal(overflow.total,null);assert.ok(overflow.rows.every(r=>r.weight===null));
});
test('external research links only carry validated public tickers',()=>{
  assert.equal(newsUrl(' nvda '),'https://saveticker.com/news/search?q=NVDA');
  for(const value of ['https://evil.test','NVDA&account=123','<script>','',null]) assert.equal(newsUrl(value),null);
});
test('disabled cards make no requests after reload or symbol selection; enabling only chart loads chart',()=>{
  const h=screen({enabled:{fear:false,news:false,portfolio:false,chart:false}});
  h.win.MoaResearch.select('NVDA');assert.equal(h.calls.length,0);assert.equal(h.timers.size,0);
  h.toggle('이동평균',true);assert.equal(h.calls.length,1);assert.match(h.calls[0].path,/chart\?symbol=NVDA/);
  h.toggle('이동평균',false);assert.equal(h.calls[0].options.signal.aborted,true);
  assert.equal(h.ids.get('research-chart').hidden,true);assert.equal(h.writes.at(-1).enabled.chart,false);
});
test('turning off a pending CNN card discards its response and stops refresh',async()=>{
  const h=screen();assert.equal(h.calls.length,1);
  h.toggle('공포·탐욕',false);
  assert.equal(h.calls[0].options.signal.aborted,true);
  h.calls[0].resolve({ok:true,json:async()=>({score:99})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.ids.get('research-fear').hidden,true);assert.equal(h.timers.size,0);
});
test('superseded CNN errors cannot overwrite a newer result or reset its refresh timer',async()=>{
  for(const parseFails of [false,true]) {
    const h=screen();
    h.toggle('공포·탐욕',false);h.toggle('공포·탐욕',true);
    h.calls[1].resolve({ok:true,json:async()=>({score:50,rating:'중립',previousClose:null,asOf:'2026-10-17T00:00:00Z',history:[]})});
    await new Promise(resolve=>setImmediate(resolve));
    const body=h.ids.get('research-fear-body'), children=body.children, timerIds=[...h.timers.keys()];
    h.calls[0].resolve({ok:false,json:async()=>{if(parseFails)throw new SyntaxError('invalid JSON');return {error:'old error'};}});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(body.children,children);assert.deepEqual([...h.timers.keys()],timerIds);
    assert.equal(body.children.find(e=>e.className==='research-headline').children[0].textContent,'50');
  }
});

test('news uses original stock or index queries and encodes ampersands as query data',()=>{
  assert.equal(newsUrl('GOOW','underlying',relations),newsUrl('GOOGL'));
  assert.equal(newsTarget('QDTE','underlying',relations).label,'나스닥100');
  assert.equal(new URL(newsUrl('QDTE','underlying',relations)).searchParams.get('q'),'나스닥100');
  const spx=new URL(newsUrl('XDTE','underlying',relations));
  assert.equal(spx.searchParams.get('q'),'S&P 500');assert.equal([...spx.searchParams].length,1);
  assert.equal(newsUrl('QDTE','self',relations),newsUrl('QDTE'));
  assert.equal(newsUrl('NVDA','underlying',relations),newsUrl('NVDA'));
  assert.equal(newsUrl('GOOW','underlying',null),null);
  assert.equal(newsUrl('GOOW','underlying',{GOOW:{kind:'stock',newsQuery:'https://evil.test'}}),null);
});

test('mapped news window follows original and index; switching to product is independent of chart',async()=>{
  const h=screen({enabled:{fear:false,chart:false},autoNews:true});
  h.win.MoaResearch.select('GOOW');await new Promise(resolve=>setImmediate(resolve));await h.run(450);
  h.newsButton().events.click();
  assert.equal(h.popups[0].location.href,newsUrl('GOOGL'));
  assert.match(h.text('research-news-body'),/GOOW → 뉴스 GOOGL/);
  h.win.MoaResearch.select('QDTE');await h.run(450);
  assert.equal(new URL(h.popups[0].location.href).searchParams.get('q'),'나스닥100');
  h.newsBasis('self');assert.equal(h.popups[0].location.href,newsUrl('QDTE'));
  assert.equal(h.writes.at(-1).newsBasis,'self');assert.equal(h.writes.at(-1).chartBasis,'underlying');
  h.newsBasis('underlying');assert.equal(new URL(h.popups[0].location.href).searchParams.get('q'),'나스닥100');
});

test('missing news mapping disables original lookup rather than silently using product ticker',async()=>{
  const h=screen({enabled:{fear:false,chart:false}},true);h.win.MoaResearch.select('GOOW');
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.newsButton().disabled,true);assert.match(h.text('research-news-body'),/연결 정보를 불러오지 못/);
  h.newsButton().events.click();assert.equal(h.popups.length,0);
  h.newsBasis('self');assert.equal(h.newsButton().disabled,false);
  h.newsButton().events.click();assert.equal(h.popups[0].location.href,newsUrl('GOOW'));
});

test('index reference ETF is explicitly labelled and is never presented as index points',async()=>{
  const h=screen({enabled:{fear:false,news:false}});h.win.MoaResearch.select('QDTE');const pending=h.run(450);
  const value={...chartResponse('QDTE','QQQ'),underlying:{kind:'index',symbol:'NDX',name:'나스닥100',chartProxy:true}};
  h.calls[0].resolve({ok:true,json:async()=>value});await pending;
  assert.match(h.text('research-chart-body'),/기초지수 나스닥100/);
  assert.match(h.text('research-chart-body'),/참고 ETF QQQ/);
  assert.match(h.text('research-chart-body'),/지수 자체 값이나 QDTE 가격이 아니/);
});

test('alternative sentiment discloses a different methodology and source switch discards old response',async()=>{
  const h=screen({enabled:{news:false}});
  h.fearSource('feargreedchart');assert.equal(h.calls[0].options.signal.aborted,true);
  assert.match(h.calls[1].path,/source=feargreedchart$/);
  h.calls[1].resolve({ok:true,json:async()=>({provider:'feargreedchart',providerName:'FearGreedChart 미국시장 심리',score:36,rating:'공포',previousClose:null,asOf:'2026-10-23T20:00:00Z',asOfLabel:'제공사 응답 시각',history:[],fallback:{httpStatus:418}})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(h.text('research-fear-body'),/CNN과 다른 5개 지표/);
  assert.match(h.text('research-fear-body'),/HTTP 418/);
  assert.match(h.text('research-fear-body'),/제공사 응답 시각/);
  const children=h.ids.get('research-fear-body').children;
  h.calls[0].resolve({ok:true,json:async()=>({score:99})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.ids.get('research-fear-body').children,children);
  assert.equal(h.writes.at(-1).fearSource,'feargreedchart');
});
test('news auto-follow reuses explicit window, detaches opener, and stops when disabled',async()=>{
  const h=screen({enabled:{fear:false,chart:false}});
  h.win.MoaResearch.select('NVDA');h.autoNews(true);
  await new Promise(resolve=>setImmediate(resolve));
  await h.run(450);assert.equal(h.popups.length,0);
  h.newsButton().events.click();assert.equal(h.popups.length,1);
  assert.equal(h.popups[0].location.href,newsUrl('NVDA'));
  h.win.MoaResearch.select('MSFT');await h.run(450);
  assert.equal(h.popups.length,1);assert.equal(h.popups[0].location.href,newsUrl('MSFT'));
  h.toggle('종목 뉴스',false);h.win.MoaResearch.select('AAPL');await h.run(450);
  assert.equal(h.popups[0].location.href,newsUrl('MSFT'));
  h.toggle('종목 뉴스',true);assert.equal(h.popups[0].location.href,newsUrl('AAPL'));
  h.autoNews(false);h.win.MoaResearch.select('NVDA');await h.run(450);
  assert.equal(h.popups[0].location.href,newsUrl('AAPL'));
});
