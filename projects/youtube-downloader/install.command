#!/bin/bash
set -eu
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
unset PYTHONHOME PYTHONPATH
project_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
if /usr/bin/env python3 "$project_dir/install.py"; then
  /usr/bin/osascript -e 'display dialog "下載程式與背景服務已安裝。請按 ⌘＋Space，輸入「youtube downloader」。捷徑若尚未建立，請依 SHORTCUT_SETUP.md 設定。" with title "youtube downloader" buttons {"好"} default button "好"'
else
  /usr/bin/osascript -e 'display dialog "安裝未完成，請查看此視窗的錯誤訊息。" with title "youtube downloader" buttons {"好"} default button "好"'
  exit 1
fi
