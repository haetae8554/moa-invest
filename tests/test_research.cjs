const test = require('node:test');
const assert = require('node:assert/strict');
const {preferences,allocation,newsUrl} = require('../order_ui/static/research.js');
const fs=require('node:fs');
const vm=require('node:vm');

function screen(saved={}) {
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
    fetch(path,options){return new Promise(resolve=>calls.push({path,options,resolve}));}
  });
  function descendants(root){return [root,...(root.children||[]).flatMap(descendants)];}
  const all=()=>descendants(ids.get('research-tools'));
  return {win,ids,calls,writes,timers,popups,
    toggle(title,checked){const input=all().find(e=>e.attributes?.['aria-label']===`${title} 켜기`);input.checked=checked;input.events.change();},
    newsButton(){return ids.get('research-news-body').children.find(e=>e.tag==='button');},
    autoNews(checked){const label=ids.get('research-news-body').children.find(e=>e.tag==='label');const check=label.children[0];check.checked=checked;check.events.change();},
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
    assert.equal(body.children[0].children[0].textContent,'50');
  }
});
test('news auto-follow reuses explicit window, detaches opener, and stops when disabled',async()=>{
  const h=screen({enabled:{fear:false,chart:false}});
  h.win.MoaResearch.select('NVDA');h.autoNews(true);
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
