# 公開版本測試範圍

公開包發布前於 2026-11-16（Asia/Taipei）重新執行隔離測試：**115 項全部通過，21.097 秒**。

測試環境：Apple Silicon、macOS 26.6、Python 3.14、yt-dlp、ffmpeg／ffprobe。

驗證範圍包含：單首與清單、中文路徑、分類建立、Video ID 去重、重跑清單跳過、刪檔後重新取得、部分失敗繼續、多程序鎖、SQLite 完整性、相同位元 SHA-256、同名保護、取消與重試、worker 中斷恢復、磁碟不足、ffmpeg 缺失、壞檔拒絕、原子檔案發布、Mix 首數、區間分配、標題鋼琴規則、進度解析、JSON 原生協定、提交摘要／返回編輯、前端避免直接存取 Desktop。

音訊整合測試使用自產短音源與 localhost HTTP，交給真正 yt-dlp／ffmpeg 輸出 MP3，驗證 metadata、封面與暫存清理。其餘 YouTube 回應使用模擬程序。

本機開發期間另曾以原生視窗實際操作首數、分類、區間、摘要返回修改及進度篩選，最後取消，未由這些測試新增下載任務。

限制：自動測試不代表所有 YouTube 網址皆能成功下載；未驗證全新使用者首次安裝、真實 iCloud Desktop 完整下載、所有 macOS 版本，以及 Spotlight 搜尋後按 Return 的完整流程。公開包不含個人任務資料、實際下載紀錄或原開發者的捷徑簽章備份。

執行方式：

```sh
MUSIC_DOWNLOADER_NO_NOTIFY=1 python3 -m unittest discover -s tests -v
```
