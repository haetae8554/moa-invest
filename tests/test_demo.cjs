const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {plan}=require('../browser_extension/demo.js');
test('demo divides cents exactly with final remainder',()=>{
  assert.deepEqual(plan('100.00','AMOUNT','BUY',20000),{count:'12',full:'11',remainder:'100',chunk:'900',quantity:false,amount:'10000'});
  assert.equal(plan('0.01','AMOUNT','SELL',20000).remainder,'1');
  assert.equal(plan('18','AMOUNT','SELL',20000).remainder,'0');
});
test('quantity buy budgets cents upward; sell preserves microshare total',()=>{
  assert.equal(plan('0.000001','QUANTITY','BUY',20000).amount,'1');
  const p=plan('1','QUANTITY','SELL',20000);
  assert.equal(p.count,'23');assert.equal(p.chunk,'45000');
  assert.equal(BigInt(p.chunk)*BigInt(p.full)+BigInt(p.remainder),1000000n);
  const q=plan('0.123456','QUANTITY','SELL',99999);
  assert.equal(BigInt(q.chunk)*BigInt(q.full)+BigInt(q.remainder),123456n);
});
test('invalid, overprecision and unbounded inputs fail without loops',()=>{
  for(const value of ['NaN','Infinity','-1','0','1e9','1.001','1000000001',null,true,'<script>']) assert.throws(()=>plan(value,'AMOUNT','BUY',20000));
  assert.throws(()=>plan('1.0000001','QUANTITY','SELL',20000));
  assert.throws(()=>plan('1','INVALID','SELL',20000));
  assert.throws(()=>plan('1','AMOUNT','BUY',0));
});
test('offline demo has no network, native bridge or persistence',()=>{
  const html=fs.readFileSync('browser_extension/demo.html','utf8');
  const js=fs.readFileSync('browser_extension/demo.js','utf8').replace(/\/\*[^]*?\*\//g,'');
  assert.match(html,/connect-src 'none'/);assert.match(html,/frame-src 'none'/);assert.match(html,/가상 데이터/);
  assert.doesNotMatch(js,/\b(fetch|XMLHttpRequest|WebSocket|chrome|localStorage|sessionStorage)\b/);
  assert.doesNotMatch(html,/launcher\.js|sidepanel\.js|https?:\/\//);
});
