/* Offline demonstration only. No fetch, Chrome APIs, credentials or real orders. */
const DemoPlan = (()=>{
  const scale=1000000n;
  function units(value, places) {
    if(typeof value !== 'string' || !new RegExp(`^\\d{1,10}(?:\\.\\d{1,${places}})?$`).test(value)) throw Error('양수와 올바른 소수 자릿수를 입력해 주세요.');
    const [whole,fraction='']=value.split('.');
    const result=BigInt(whole)*10n**BigInt(places)+BigInt(fraction.padEnd(places,'0'));
    if(result<=0n || result>1000000000n*10n**BigInt(places)) throw Error('입력 범위를 확인해 주세요.');
    return result;
  }
  function plan(value,basis,side,priceCents) {
    if(!['AMOUNT','QUANTITY'].includes(basis) || !['BUY','SELL'].includes(side) || !Number.isSafeInteger(priceCents) || priceCents<=0) throw Error('올바른 계산 조건이 필요해요.');
    const quantity=basis==='QUANTITY', price=BigInt(priceCents);
    const total=units(value,quantity ? 6 : 2);
    const quantitySell=quantity && side==='SELL';
    const amount=quantity ? (total*price+scale-1n)/scale : total;
    const chunk=quantitySell ? 900n*scale/price : 900n;
    if(chunk<1n) throw Error('이 가격으로는 예시 수량을 계산할 수 없어요.');
    const target=quantitySell ? total : amount;
    return {count:((target+chunk-1n)/chunk).toString(),full:(target/chunk).toString(),remainder:(target%chunk).toString(),chunk:chunk.toString(),quantity:quantitySell,amount:amount.toString()};
  }
  return {plan};
})();
if(typeof module !== 'undefined') module.exports=DemoPlan;
if(typeof document !== 'undefined') {
  const stocks=[{symbol:'AAPL',price:20000,shares:'2',value:400},{symbol:'MSFT',price:40000,shares:'2',value:800},{symbol:'SGOV',price:10000,shares:'5',value:500}];
  const $=id=>document.getElementById(id);
  let selected=stocks[0], side='BUY';
  const usd=cents=>'$'+(Number(cents)/100).toFixed(2);
  function render() {
    $('value-label').textContent=selected.symbol+' · '+($('basis').value==='AMOUNT' ? '총주문금액' : '총주문수량');
    for(const button of document.querySelectorAll('[data-side]')) {const active=button.dataset.side===side;button.classList.toggle('selected',active);button.setAttribute('aria-pressed',String(active));}
    for(const button of document.querySelectorAll('[data-symbol]')) button.classList.toggle('selected',button.dataset.symbol===selected.symbol);
    try {
      const p=DemoPlan.plan($('value').value,$('basis').value,side,selected.price);
      const format=value=>p.quantity ? `${Number(value)/1000000}주` : usd(value);
      const parts=[];
      if(p.full!=='0') parts.push(`${format(p.chunk)} × ${p.full}회`);
      if(p.remainder!=='0') parts.push(`마지막 ${format(p.remainder)}`);
      $('plan').textContent=`${selected.symbol} ${side==='BUY' ? '매수' : '매도'} 예시 · ${p.count}회\n${parts.join(' + ')}\n예시 총금액 ${usd(p.amount)}`;
      $('plan').style.whiteSpace='pre-line';
    } catch(error) {$('plan').textContent=error.message;}
  }
  for(const stock of stocks) {
    const button=document.createElement('button');button.className='holding';button.dataset.symbol=stock.symbol;
    const title=document.createElement('span');title.textContent=stock.symbol;
    const shares=document.createElement('small');shares.textContent=stock.shares+'주 · 가상 보유';title.append(shares);
    const value=document.createElement('span');value.textContent=usd(stock.value*100);
    const price=document.createElement('em');price.textContent='예시 가격 '+usd(stock.price);value.append(price);
    button.append(title,value);button.addEventListener('click',()=>{selected=stock;render();});$('holdings').append(button);
  }
  for(const button of document.querySelectorAll('[data-side]')) button.addEventListener('click',()=>{side=button.dataset.side;render();});
  $('basis').addEventListener('change',()=>{$('value').value=$('basis').value==='QUANTITY' ? '1' : '100.00';render();});
  $('calculate').addEventListener('click',render);$('value').addEventListener('input',render);render();
}
