/* Extension pages only. No page/content-script message can request native commands. */
const MoaLauncher = (()=>{
  let pending;
  async function start() {
    try {
      const result=await chrome.runtime.sendNativeMessage('com.moa_invest.launcher',{action:'ensure-server'});
      if(result?.ok === true) return {ok:true};
      return {ok:false,text:result?.code === 'port-busy'
        ? '8765 포트에서 이전 서버 또는 다른 프로그램이 실행 중이에요. 진행 중인 주문을 확인한 뒤 서버를 업데이트해 주세요.'
        : '서버를 시작하지 못했어요. Python 3.11 이상과 프로젝트 폴더를 확인한 뒤 연결 도구를 다시 등록해 주세요.'};
    } catch (_) {
      return {ok:false,text:'자동 실행 연결이 필요해요. 프로젝트 폴더의 install-extension.bat을 한 번 실행하고 다시 연결해 주세요.'};
    }
  }
  return {ensure:()=>pending || (pending=start().finally(()=>{pending=null;}))};
})();
