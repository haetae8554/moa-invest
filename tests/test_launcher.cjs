const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function launcher(sendNativeMessage) {
  const context=vm.createContext({chrome:{runtime:{sendNativeMessage}}});
  vm.runInContext(fs.readFileSync('browser_extension/launcher.js','utf8'),context);
  return ()=>vm.runInContext('MoaLauncher.ensure()',context);
}
test('native request is fixed and concurrent starts are coalesced',async()=>{
  const calls=[];let resolve;
  const ensure=launcher((name,message)=>{calls.push({name,message});return new Promise(r=>resolve=r);});
  const first=ensure(),second=ensure();
  assert.equal(first,second);assert.equal(calls.length,1);
  assert.equal(calls[0].name,'com.moa_invest.launcher');
  assert.equal(JSON.stringify(calls[0].message),'{"action":"ensure-server"}');
  resolve({ok:true,secret:'must-not-pass-through'});
  assert.equal(JSON.stringify(await first),'{"ok":true}');
});
test('missing native host, busy port and failed launch provide safe recovery text',async()=>{
  for(const code of ['port-busy','start-failed','missing']) {
    const ensure=launcher(async()=>{if(code==='missing')throw Error('synthetic-sensitive');return {ok:false,code,details:'synthetic-sensitive'};});
    const result=await ensure();assert.equal(result.ok,false);assert.ok(result.text);
    assert.doesNotMatch(JSON.stringify(result),/synthetic-sensitive/);
    assert.match(result.text,code==='missing' ? /install-extension.bat/ : code==='port-busy' ? /8765/ : /Python/);
  }
});
test('new tab action always creates a launcher tab rather than activating an existing tab',async()=>{
  const handlers={},created=[],elements=new Map();
  const el=id=>{if(!elements.has(id))elements.set(id,{value:'',options:[],addEventListener:(event,fn)=>{handlers[id+':'+event]=fn;},replaceChildren(){},append(){}});return elements.get(id);};
  const context=vm.createContext({document:{getElementById:el},window:{close(){}},chrome:{runtime:{getURL:path=>'chrome-extension://test/'+path,sendMessage:async()=>({tabs:[],cacheCount:0})},windows:{getCurrent:async()=>({id:7})},tabs:{create:async value=>created.push(value),query:()=>{throw Error('must not search existing tabs');}}}});
  vm.runInContext(fs.readFileSync('browser_extension/popup.js','utf8'),context);
  await Promise.resolve();await handlers['open-tab:click']();
  assert.equal(created[0].url,'chrome-extension://test/launch.html');assert.equal(created[0].windowId,7);
});
test('only extension UI pages load launcher, with no content-script command bridge',()=>{
  const manifest=JSON.parse(fs.readFileSync('browser_extension/manifest.json','utf8'));
  assert.ok(manifest.permissions.includes('nativeMessaging'));
  assert.ok(manifest.content_scripts.every(entry=>!entry.js.includes('launcher.js')));
  assert.equal(manifest.externally_connectable,undefined);
  assert.doesNotMatch(fs.readFileSync('browser_extension/background.js','utf8'),/sendNativeMessage|connectNative/);
});
