# youtube downloader

以 **Spotlight、Apple 捷徑與原生 macOS 視窗**操作的 YouTube／YouTube Music MP3 下載工具。日常使用不需要開啟 Terminal。

[專案介紹與下載](https://amanojaku1024.github.io/posts/youtube-downloader/) · [功能與分類規則](FEATURES.md) · [測試範圍](TEST_REPORT.md)

## 功能

- 單曲、播放清單與 YouTube Music 網址；單曲模式不會因網址帶清單參數而下載整份清單。
- 所有播放清單都選擇首數；一般清單可選全部，Mix 需指定 1–500 首。
- 使用現有分類、新增分類、依第幾首／範圍分配資料夾。
- 可依影片標題中的 Piano、鋼琴、ピアノ等字樣自動分類。這是文字規則，並非音訊辨識。
- MP3、高品質編碼、可取得的 metadata 與封面。
- 原生雙進度條、搜尋、失敗篩選、取消、結果報告與重試。
- launchd 背景佇列；關閉捷徑或進度視窗後，已提交任務繼續執行。
- 全域 Video ID 去重、SHA-256 精確檔案比對、已刪檔可重新取得；不依相似歌名合併不同版本。

## 安裝

適用 macOS。目前實測環境為 Apple Silicon、macOS 26.6；其他 macOS 版本尚未完成實機驗證。

前置需求為 [Homebrew](https://brew.sh/)、Python 3.10 以上，以及 Xcode Command Line Tools 的 Swift 編譯器。若尚未具備，請先依各工具的官方方式安裝；本安裝包不會替使用者同意系統授權。

1. 從專案介紹頁下載 ZIP 並解壓縮。
2. 雙擊 `install.command`。安裝程式檢查並透過 Homebrew 安裝缺少的 yt-dlp、ffmpeg／ffprobe、Deno，編譯原生視窗並設定使用者背景服務。**僅安裝維護階段使用 Terminal**。
3. 依 [SHORTCUT_SETUP.md](SHORTCUT_SETUP.md) 建立名為 `youtube downloader` 的捷徑，只需貼一行入口腳本，再開啟 Spotlight 顯示。
4. 首次執行時，依 macOS 提示允許指令稿、桌面檔案存取及通知。

公開版本提供可檢視的捷徑入口腳本與設定步驟；不包含綁定原開發環境簽章的捷徑備份或已編譯程式。

若系統阻擋下載的腳本執行，請先檢視原始碼，再依 macOS 的標準流程處理。安裝程式不會關閉 Gatekeeper 或修改 TCC 授權資料庫。

## 日常使用

按 `⌘ + Space` 搜尋 `youtube downloader` → 選單曲／播放清單 → 使用剪貼簿網址或輸入網址 → 選首數及分類 → 檢查摘要 → 開始下載。

音樂存放於 macOS 實際解析的 `桌面/音樂/分類/歌曲名稱.mp3`，不建立播放清單子資料夾。可以用 Cog 等播放器直接瀏覽資料夾。

程式、SQLite、任務、報告與暫存存放於 `~/Library/Application Support/MusicDownloader/`。使用者背景服務的識別名稱為 `com.wyw.musicdownloader.worker`。不會自動移動既有音樂。

關閉視窗不等於取消；要取消任務請重新開啟工具的「查看進度／重試／取消」。Mac 關機或登出時不會下載；重新登入後恢復未完成任務。

## 去重與失敗處理

共用 SQLite 索引檢查 Video ID 與有效音檔。檔案已消失時可重新下載；先以 ffprobe 驗證，再記錄成功。相同位元的檔案會透過 SHA-256 合併成功記錄，保留原有檔案；已有歌曲在其他分類時回報原位置，不搬動、不刪除。

未知舊檔與不同影片 ID 通常需先下載才能比對；不同編碼、標籤或封面的音檔，即使是同一演出，也不保證被識別為相同。Live、Cover、Remix 不會只因標題相近就被跳過。

單首失敗不會中斷整份清單。任務保存清單快照，重試沿用原首數與分類規則。私人、已刪除、需要登入或受 YouTube 驗證限制的內容可能無法取得。程式不會自行讀取瀏覽器 Cookie。

## 更新

沒有下載進行時，雙擊 `update.command` 更新 yt-dlp 與 Deno；結果記錄於工具私有資料夾的 `logs/update.log`。工程維護也可使用 `brew update` 與 `brew upgrade yt-dlp deno`，需要時另更新 ffmpeg。

## 開發與測試

無額外第三方 Python 套件；Python 標準函式庫搭配 AppKit／Swift 與外部下載工具。

```sh
MUSIC_DOWNLOADER_NO_NOTIFY=1 python3 -m unittest discover -s tests -v
```

測試使用隔離臨時目錄、模擬 YouTube 回應及自產短音源，不下載個人播放清單。詳細結果與未驗證範圍見 [TEST_REPORT.md](TEST_REPORT.md)。

## 專案檔案

- `music_downloader.py`：SQLite、佇列、去重、下載與原子檔案發布。
- `frontend.py`／`native_ui.swift`：設定流程與原生視窗。
- `progress_status.py`：進度解析與狀態轉接。
- `install.py`／`install.command`：安裝及背景服務。
- `tests/`：隔離測試與原生介面測試工具。

yt-dlp、ffmpeg、Deno、Homebrew 與 Cog 均為各自獨立的第三方專案；此原始碼包不捆綁上述工具或音樂檔案。
