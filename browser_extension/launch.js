async function openDesk() {
  document.getElementById('retry').disabled=true;
  document.getElementById('launch-status').textContent='모아 서버에 연결하고 있어요…';
  const result=await MoaLauncher.ensure();
  if(result.ok) location.replace('http://127.0.0.1:8765/');
  else document.getElementById('launch-status').textContent=result.text;
  document.getElementById('retry').disabled=false;
}
document.getElementById('retry').addEventListener('click',openDesk);
openDesk();
