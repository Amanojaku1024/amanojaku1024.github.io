# 建立 youtube downloader 捷徑

先完成 `install.command` 安裝，再操作 Apple「捷徑」App：

1. 新增捷徑，命名為 **youtube downloader**。
2. 加入「執行 Shell 工序指令」（Run Shell Script），貼上以下一行，不勾選管理員身分：

   ```sh
   /bin/bash "$HOME/Library/Application Support/MusicDownloader/launcher.sh" ui
   ```

3. 在捷徑詳細資訊開啟「在 Spotlight 中顯示」。

入口腳本也存於 `shortcut_shell.sh`。接下來按 ⌘ + Space 搜尋名稱，即可進入原生操作視窗。

如果希望第一層選單也由捷徑本身顯示，可使用「從選單中選擇」，加入以下三個分支，各放一個 Shell 動作：

| 分支 | Shell 內容 |
| --- | --- |
| 下載單首 | `/bin/bash "$HOME/Library/Application Support/MusicDownloader/launcher.sh" ui single` |
| 下載整份播放清單 | `/bin/bash "$HOME/Library/Application Support/MusicDownloader/launcher.sh" ui playlist` |
| 查看進度／重試／取消 | `/bin/bash "$HOME/Library/Application Support/MusicDownloader/launcher.sh" ui status` |

若系統提示允許執行指令稿，請在捷徑的進階設定開啟相關選項。桌面檔案與通知權限由使用者在系統提示中授權。

若 Spotlight 一般搜尋沒有顯示捷徑，可嘗試 ⌘ + 3 的動作篩選，或直接在捷徑 App 執行。不同 macOS 版本與搜尋索引狀態可能影響結果；公開下載包尚未在全新帳號上驗證 Spotlight 搜尋與首次授權流程。

[Apple：從 Spotlight 執行捷徑](https://support.apple.com/guide/shortcuts-mac/run-a-shortcut-from-spotlight-apd8d2af91df/mac)
