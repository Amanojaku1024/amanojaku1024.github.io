#!/bin/bash
set -eu
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
support_dir="$HOME/Library/Application Support/MusicDownloader"
mkdir -p "$support_dir/logs"
update_log="$support_dir/logs/update.log"
if ! brew_bin="$(command -v brew)"; then
  /usr/bin/osascript -e 'display dialog "找不到 Homebrew，請先重新安裝下載工具。" with title "youtube downloader 更新" buttons {"好"} default button "好"'
  exit 1
fi
if "$brew_bin" update >"$update_log" 2>&1 && "$brew_bin" upgrade yt-dlp deno >>"$update_log" 2>&1; then
  /usr/bin/osascript -e 'display dialog "yt-dlp 與 JavaScript 執行工具已更新。可以重新執行 youtube downloader。" with title "youtube downloader 更新" buttons {"好"} default button "好"'
else
  /usr/bin/osascript -e 'display dialog "更新失敗，請檢查網路。技術詳情位於 Library/Application Support/MusicDownloader/logs/update.log。" with title "youtube downloader 更新" buttons {"好"} default button "好"'
  exit 1
fi
