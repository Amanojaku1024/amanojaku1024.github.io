const button = document.getElementById('copy-shortcut');
const code = document.getElementById('shortcut-code');
const status = document.getElementById('copy-status');
if (button && code && status) {
  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(code.textContent);
      button.textContent = '已複製 ✓';
      status.textContent = '已複製，貼到捷徑的「執行 Shell 工序指令」即可。';
    } catch {
      status.textContent = '無法自動複製，請選取上方內容後複製。';
    }
  });
}
