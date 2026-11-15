#!/usr/bin/env python3
"""Native macOS dialogs for the MusicDownloader shortcut; stdlib only.

All user data is passed as argv or JSON stdin, never executable AppleScript/Shell.
The Shortcuts workflow supplies a mode through its native Choose from Menu action.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from urllib.parse import parse_qs, urlsplit

from music_downloader import UserError, is_mix_url, normalize_url, validate_options


class UserCancelled(Exception):
    pass


class FrontendError(Exception):
    pass


def native_binary() -> Path:
    return Path(__file__).with_name("NativeUI.app") / "Contents/MacOS/MusicDownloaderUI"


def native_dialog(kind: str, prompt: str, default: str = "", choices=None,
                  title: str = "youtube downloader") -> str:
    process = subprocess.run([str(native_binary()), "dialog"],
        input=json.dumps({"kind": kind, "title": title, "prompt": prompt,
                          "default": default, "choices": choices or []}, ensure_ascii=False),
        text=True, capture_output=True)
    try:
        result = json.loads(process.stdout)
        if not isinstance(result, dict):
            raise ValueError("Invalid native response")
    except ValueError as exc:
        raise FrontendError("無法開啟原生視窗，請重新安裝介面元件。") from exc
    if result.get("cancelled"):
        raise UserCancelled()
    if process.returncode or result.get("error"):
        raise FrontendError(result.get("error") or "原生視窗暫時無法回應，請再試一次。")
    return str(result.get("value", ""))


def show_progress(job_id: str | None = None) -> bool:
    binary = native_binary()
    if not binary.is_file():
        return False
    app = Path(__file__).resolve().parent
    home = app.parent
    args = [str(binary), "progress", "--home", str(home), "--python", sys.executable,
            "--engine", str(app / "progress_status.py")]
    if job_id:
        args += ["--job", job_id]
    # The viewer is independent of the shortcut and the download worker.
    log_dir = home / "logs"
    log_dir.mkdir(exist_ok=True)
    with (log_dir / "ui.log").open("ab") as log:
        subprocess.Popen(args, stdout=log, stderr=log, start_new_session=True)
    return True


def applescript(source: str, *args: str) -> str:
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", source, "--", *map(str, args)],
        text=True, capture_output=True,
    )
    if result.returncode:
        if "(-128)" in result.stderr or "User canceled" in result.stderr:
            raise UserCancelled()
        raise FrontendError("無法顯示 macOS 視窗。請從「捷徑」App 再試一次。")
    return result.stdout.rstrip("\n")


def choose(prompt: str, choices: list[str]) -> str:
    if not choices:
        raise FrontendError("目前沒有可選擇的項目。")
    if native_binary().is_file():
        return native_dialog("choose", prompt, choices=choices)
    result = applescript('''on run argv
        activate
        set picked to choose from list (items 2 thru -1 of argv) with title "youtube downloader" with prompt (item 1 of argv) OK button name "選擇" cancel button name "取消"
        if picked is false then error number -128
        return item 1 of picked
    end run''', prompt, *choices)
    return result


def ask(prompt: str, default: str = "") -> str:
    if native_binary().is_file():
        return native_dialog("ask", prompt, default)
    return applescript('''on run argv
        activate
        set answer to display dialog (item 1 of argv) default answer (item 2 of argv) with title "youtube downloader" buttons {"取消", "繼續"} default button "繼續" cancel button "取消"
        return text returned of answer
    end run''', prompt, default)


def message(text: str, title: str = "youtube downloader") -> None:
    if native_binary().is_file():
        native_dialog("message", text, title=title)
        return
    applescript('''on run argv
        activate
        display dialog (item 1 of argv) with title (item 2 of argv) buttons {"好"} default button "好"
    end run''', text, title)


def notify(text: str) -> None:
    applescript('''on run argv
        display notification (item 1 of argv) with title "youtube downloader"
    end run''', text)


def backend(*args: str, payload: dict | None = None):
    process = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("music_downloader.py")), *args],
        input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
        capture_output=True, text=True, timeout=30,
    )
    if process.returncode:
        try:
            data = json.loads(process.stdout)
            problem = data.get("error") or data.get("message")
        except (ValueError, AttributeError):
            problem = None
        raise FrontendError(problem or "操作未完成。請使用「查看進度／重試／取消」查看結果，或參閱記錄檔。")
    try:
        return json.loads(process.stdout)
    except ValueError as exc:
        raise FrontendError("下載程式回傳的資料不完整，請重新安裝程式。") from exc


def valid_url(text: str, mode: str) -> str | None:
    """Extract only a supported canonical-looking YouTube URL, without network IO."""
    candidates = re.findall(r"https?://[^\s<>\"']+", text.strip())
    if not candidates and text.strip().startswith(("youtube.com/", "www.youtube.com/", "music.youtube.com/", "youtu.be/")):
        candidates = ["https://" + text.strip()]
    for candidate in candidates:
        candidate = candidate.rstrip("。.,，;)）]}")
        try:
            parsed = urlsplit(candidate)
            if parsed.username or parsed.password or parsed.port not in (None, 443, 80):
                continue
            host = (parsed.hostname or "").lower()
            if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}:
                continue
            query = parse_qs(parsed.query)
            if mode == "playlist":
                playlist = query.get("list", [""])[0]
                if re.fullmatch(r"[A-Za-z0-9_-]{2,200}", playlist):
                    try:
                        normalize_url(candidate, mode)
                    except UserError:
                        continue
                    return candidate
            else:
                video = query.get("v", [""])[0]
                if host.endswith("youtu.be"):
                    video = parsed.path.strip("/")
                elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
                    video = parsed.path.split("/")[2]
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
                    try:
                        normalize_url(candidate, mode)
                    except UserError:
                        continue
                    return candidate
        except (ValueError, IndexError):
            continue
    return None


def valid_category(value: str) -> str:
    value = unicodedata.normalize("NFC", value.strip())
    if (not value or value.startswith(".") or len(value.encode("utf-8")) > 100
            or any(ch in '/\\:' or unicodedata.category(ch).startswith("C") for ch in value)):
        raise FrontendError("種類名稱請使用一般文字，不能包含斜線、冒號、控制字元，也不能以句點開頭（最多約 33 個中文字）。")
    return value


def pick_category() -> str:
    categories = backend("categories")
    if isinstance(categories, dict):
        categories = categories.get("categories", [])
    add = "＋ 新增音樂種類…"
    while add in categories:
        add = "＋" + add
    picked = choose("選擇音樂種類；歌曲會直接存入該資料夾。", [*categories, add])
    if picked != add:
        return valid_category(picked)
    while True:
        try:
            return valid_category(ask("輸入新的音樂種類名稱，例如：遊戲原聲帶"))
        except FrontendError as error:
            message(str(error))


def _ask_playlist_limit(mix: bool) -> int | None:
    if mix:
        prompt = "這是 YouTube Mix 動態推薦清單，會持續延伸。\n要下載目前推薦的前幾首？（1–500 首）"
        minimum, maximum = 1, 500
    else:
        prompt = "要下載播放清單的前幾首？\n輸入 1–10000 的整數；輸入 0 代表全部。\n首數依播放清單原始順序計算，包含已下載或無法取得的歌曲。"
        minimum, maximum = 0, 10000
    while True:
        value = ask(prompt, "50")
        try:
            cleaned = value.strip()
            if re.fullmatch(r"[0-9]+", cleaned):
                count = int(cleaned)
                if minimum <= count <= maximum:
                    return count or None
        except ValueError:
            pass
        allowed = "1 到 500" if mix else "0 到 10000（0 代表全部）"
        message(f"請輸入 {allowed}之間的整數；取消即可停止，不會開始下載。")


def ask_playlist_limit(url: str) -> int | None:
    """Every playlist needs an explicit scope; Mix cannot request an unbounded list."""
    return _ask_playlist_limit(is_mix_url(url))


def ask_mix_limit() -> int:
    """Compatibility entry for legacy Mix jobs that lack a saved limit."""
    result = _ask_playlist_limit(True)
    assert result is not None
    return result


def parse_route_range(value: str, limit: int | None = None) -> tuple[int, int]:
    """Parse original playlist positions, never a filename or executable expression."""
    cleaned = unicodedata.normalize("NFKC", value).strip()
    cleaned = re.sub(r"[–—−~～至到]", "-", cleaned)
    match = re.fullmatch(r"([0-9]+)(?:\s*-\s*([0-9]+))?", cleaned)
    if not match:
        raise FrontendError("請輸入單一序號（例如 3）或連續區間（例如 1-10）。")
    try:
        start = int(match.group(1))
        end = int(match.group(2) or match.group(1))
    except ValueError as error:
        raise FrontendError("序號太長，請重新輸入。") from error
    maximum = limit if limit is not None else 10000
    if start < 1 or end < start:
        raise FrontendError("序號從 1 開始；區間結尾不能小於起點。")
    if end > maximum:
        raise FrontendError(f"序號不能超過 {maximum}。請調整區間，或取消後重新選擇下載首數。")
    return start, end


def route_label(route: dict) -> str:
    start, end = route["start"], route["end"]
    position = f"第 {start} 首" if start == end else f"第 {start}–{end} 首"
    return f"{position} → {route['category']}"


def pick_routes(limit: int | None = None) -> list[dict]:
    routes: list[dict] = []
    while True:
        scope = f"本次下載前 {limit} 首。" if limit is not None else "本次下載全部；可指定 1–10000 內的序號。"
        try:
            value = ask("輸入要指定分類的歌曲序號或區間，例如 3 或 1-10。\n接著選擇這些歌曲的分類。序號依播放清單原始順序，不會扣除跳過或失敗的歌曲。\n" + scope)
            start, end = parse_route_range(value, limit)
            if any(start <= route["end"] and end >= route["start"] for route in routes):
                raise FrontendError("這個區間與已指定的序號重疊。請輸入尚未分配的序號，或取消後重新設定。")
        except FrontendError as error:
            message(str(error))
            continue
        routes.append({"start": start, "end": end, "category": pick_category()})
        while routes:
            recent = routes[-12:]
            display = "\n".join(route_label(route) for route in sorted(recent, key=lambda route: route["start"]))
            heading = "已指定以下分類：" if len(routes) <= 12 else f"已指定 {len(routes)} 段，以下為最近 12 段："
            choices = ["完成分配"]
            if len(routes) < 100:
                choices.append("新增另一段")
            choices.append("移除最後一段")
            action = choose(heading + "\n" + display + "\n\n其餘歌曲依剛才選擇的分類方式處理。", choices)
            if action == "完成分配":
                return sorted(routes, key=lambda route: route["start"])
            if action == "新增另一段":
                break
            routes.pop()


def pick_download_options(mode: str, limit: int | None = None) -> tuple[list[dict], bool]:
    options = ["指定分類＋自動判斷鋼琴", "全部存入指定分類"]
    if mode == "playlist":
        options += ["依序號分配（其餘自動判斷鋼琴）", "依序號分配"]
    selected = choose("選擇歌曲分類方式。\n自動判斷只看影片標題中的「鋼琴／钢琴／Piano／ピアノ／피아노」等關鍵字，符合時存入「鋼琴」，不分析音訊。\n指定序號的分類優先，其餘歌曲才自動判斷或使用預設分類。", options)
    auto_piano = selected in {"指定分類＋自動判斷鋼琴", "依序號分配（其餘自動判斷鋼琴）"}
    routes = pick_routes(limit) if selected.startswith("依序號分配") else []
    return routes, auto_piano


def ask_download_url(mode: str, default: str = "") -> str:
    url = None
    while not url:
        kind = "單一影片／歌曲" if mode == "single" else "含有 list= 的播放清單"
        typed = ask(f"貼上 YouTube 或 YouTube Music 的{kind}網址：", default)
        url = valid_url(typed, mode)
        if not url:
            message(f"這不是有效的{kind}網址。請從 YouTube 的「分享」或瀏覽器網址列複製網址。")
            default = typed
    return url


def download_summary(mode: str, url: str, category: str, limit: int | None,
                     routes: list[dict], auto_piano: bool) -> str:
    name = "單首歌曲" if mode == "single" else "YouTube Mix" if is_mix_url(url) else "播放清單"
    scope = "僅這一首" if mode == "single" else f"前 {limit} 首" if limit else "全部歌曲"
    lines = ["確認這次下載", f"模式：{name}　｜　範圍：{scope}",
             "網址：" + normalize_url(url, mode), f"預設分類：{category}",
             "鋼琴標題自動分類：" + ("開啟 → 鋼琴（手動分配優先）" if auto_piano else "關閉")]
    if routes:
        lines += ["指定歌曲分類：", *(route_label(route) for route in routes)]
    lines += ["", "儲存於桌面「音樂」的對應分類；已存在的歌曲會跳過並保留原位置。",
              "確認後按「開始下載」。取消視窗不會建立任務。"]
    return "\n".join(lines)


def review_download_settings(mode: str, url: str, category: str, limit: int | None,
                             routes: list[dict], auto_piano: bool) -> dict:
    while True:
        choices = ["開始下載", "修改預設分類", "重新設定分類方式／序號分配", "更換網址"]
        if mode == "playlist":
            choices.insert(1, "修改下載首數")
        action = choose(download_summary(mode, url, category, limit, routes, auto_piano), choices)
        if action == "開始下載":
            payload = {"mode": mode, "url": url, "category": category,
                       "routes": routes, "auto_piano": auto_piano, "piano_category": "鋼琴"}
            if mode == "playlist":
                payload["playlist_limit"] = limit
            return payload
        if action == "修改預設分類":
            category = pick_category()
        elif action == "重新設定分類方式／序號分配":
            routes, auto_piano = pick_download_options(mode, limit)
        elif action in ("修改下載首數", "更換網址"):
            if action == "更換網址":
                url = ask_download_url(mode, url)
            if mode == "playlist":
                limit = ask_playlist_limit(url)
                try:
                    validate_options(mode, limit, routes, auto_piano)
                except UserError:
                    message("下載首數已變更，原本的序號分配超出範圍。請重新選擇分類方式與分配範圍。")
                    routes, auto_piano = pick_download_options(mode, limit)


def download(mode: str) -> None:
    clipboard = subprocess.run(["/usr/bin/pbpaste"], text=True, capture_output=True).stdout
    url = valid_url(clipboard, mode) or ask_download_url(mode)
    limit = ask_playlist_limit(url) if mode == "playlist" else None
    category = pick_category()
    routes, auto_piano = pick_download_options(mode, limit)
    payload = review_download_settings(mode, url, category, limit, routes, auto_piano)
    category, routes, auto_piano = payload["category"], payload["routes"], payload["auto_piano"]
    job = backend("submit-json", payload=payload)
    identifier = str(job.get("id") or job.get("job_id") or "")
    state = job.get("status") or job.get("state") or ""
    detail = "相同任務已在佇列中。" if job.get("existing") or job.get("duplicate") or job.get("already_queued") else "已加入背景下載佇列。"
    settings = [f"預設種類：{category}"]
    if routes:
        settings.append(f"{len(routes)} 段序號分配")
    if auto_piano:
        settings.append("鋼琴標題自動分類")
    opened = show_progress(identifier)
    try:
        notify(f"{detail}{'；'.join(settings)}。可再次執行捷徑選擇「查看進度／重試／取消」。")
    except FrontendError:
        if not opened:
            message(detail)
    print(json.dumps({"id": identifier, "state": state}, ensure_ascii=False))


STATE_NAMES = {
    "queued": "等候中", "pending": "等候中", "running": "下載中",
    "completed": "完成", "done": "完成", "failed": "失敗",
    "cancelled": "已取消", "canceled": "已取消", "interrupted": "已中斷",
    "partial": "部分完成", "partial_failed": "部分完成",
}


def job_state(job: dict) -> str:
    state = str(job.get("state") or job.get("status") or "")
    return STATE_NAMES.get(state, state)


def job_settings_lines(job: dict) -> list[str]:
    """Show the immutable options of this job, including jobs created by older versions."""
    lines: list[str] = []
    if job.get("mode") == "playlist":
        mix = is_mix_url(job.get("url", ""))
        limit = job.get("playlist_limit")
        if limit:
            lines.append(f"{'YouTube Mix' if mix else '播放清單'}：前 {limit} 首（原始序號）")
        elif mix:
            lines.append("YouTube Mix：尚未設定首數，重試時會詢問。")
        else:
            lines.append("播放清單：全部")
    routes = job.get("routes", [])
    if isinstance(routes, str):
        try:
            routes = json.loads(routes)
        except ValueError:
            routes = []
    if isinstance(routes, list) and routes:
        valid = [route for route in routes if isinstance(route, dict) and all(key in route for key in ("start", "end", "category"))]
        summary = "\n".join(route_label(route) for route in valid[:12])
        if len(valid) > 12:
            summary += f"\n另有 {len(valid) - 12} 段，請開啟完整結果查看。"
        if summary:
            lines.append("指定分類（優先套用）：\n" + summary)
    enabled = job.get("auto_piano", False)
    if isinstance(enabled, str):
        enabled = enabled.lower() in {"true", "1"}
    if enabled:
        lines.append(f"鋼琴標題自動分類：開啟 → {job.get('piano_category') or '鋼琴'}（只判斷標題）")
    else:
        lines.append("鋼琴標題自動分類：關閉")
    return lines


def item_classification_lines(items: list[dict]) -> list[str]:
    reasons = {
        "range": "指定序號", "route": "指定序號", "explicit": "指定序號", "manual": "指定序號",
        "auto_piano": "標題含鋼琴關鍵字", "title_piano": "標題含鋼琴關鍵字", "piano": "標題含鋼琴關鍵字",
        "default": "預設分類",
    }
    result = []
    for item in items:
        category = item.get("category")
        if not category:
            continue
        position = item.get("position")
        title = str(item.get("title") or item.get("video_id") or "未命名歌曲")[:100]
        reason = str(item.get("reason") or "")
        reason = reasons.get(reason, reason)
        suffix = f"（{reason}）" if reason else ""
        prefix = f"第 {position} 首 " if position is not None else ""
        result.append(f"{prefix}{title} → {category}{suffix}")
    if len(result) > 12:
        return [*result[:12], f"另有 {len(result) - 12} 首，請開啟完整結果查看。"]
    return result


def status() -> None:
    if show_progress():
        return
    while True:
        jobs = backend("jobs")
        if isinstance(jobs, dict):
            jobs = jobs.get("jobs", [])
        if not jobs:
            message("目前沒有下載任務。再次執行捷徑，選擇「下載單首」或「下載整份播放清單」即可開始。")
            return
        jobs = jobs[:40]
        labels = [f"{i + 1}. {job_state(job)}｜{job.get('category', '')}｜{str(job.get('id') or job.get('job_id'))[:8]}" for i, job in enumerate(jobs)]
        picked = choose("選擇任務查看下載數量、結果、重試或取消。", labels)
        job = jobs[labels.index(picked)]
        identifier = str(job.get("id") or job.get("job_id"))
        detail = backend("status", identifier)
        if isinstance(detail, dict) and isinstance(detail.get("job"), dict):
            job = detail["job"]
        else:
            job = detail
        counts = job.get("counts", {})
        lines = [f"狀態：{job_state(job)}", f"預設種類：{job.get('category', '')}",
                 f"下載：{job.get('downloaded', counts.get('downloaded', 0))}　跳過：{job.get('skipped', counts.get('skipped', 0))}　失敗：{job.get('failed', counts.get('failed', 0))}"]
        lines.extend(job_settings_lines(job))
        progress = job.get("progress") or job.get("message") or job.get("error")
        if progress:
            lines.append(str(progress))
        items = detail.get("items", []) if isinstance(detail, dict) else []
        failures = [i for i in items if i.get("state") == "failed" and i.get("error")]
        if failures:
            lines.append("失敗原因：\n" + "\n".join(f"{i.get('title') or i.get('video_id', '')}：{i['error']}" for i in failures[:3]))
        classifications = item_classification_lines(items)
        if classifications:
            lines.append("歌曲分類：\n" + "\n".join(classifications))
        locations = []
        for item in items:
            path = item.get("path") or item.get("file_path") or item.get("existing_path")
            if path and (item.get("state") == "skipped" or item.get("status") == "skipped"):
                locations.append(str(path))
        if locations:
            lines.append("已存在的歌曲位置：\n" + "\n".join(locations[:12]))
        if job.get("report") or job.get("report_path"):
            lines.append("完整結果：" + str(job.get("report") or job.get("report_path")))
        state = str(job.get("state") or job.get("status") or "")
        choices = ["重新整理", "返回任務列表"]
        report = detail.get("report") if isinstance(detail, dict) else None
        if report and Path(str(report)).is_file():
            choices.append("開啟完整結果")
        if state in {"queued", "pending", "running"}:
            choices.append("取消此任務")
        else:
            choices.append("重試此任務")
        action = choose("\n".join(lines)[:5000], choices)
        if action == "取消此任務":
            backend("cancel", identifier)
            message("已送出取消要求。正在完成的檔案會安全保留，稍後可重試未完成的歌曲。")
        elif action == "重試此任務":
            if job.get("mode") == "playlist" and is_mix_url(job.get("url", "")) and not job.get("playlist_limit"):
                backend("retry", identifier, "--playlist-limit", str(ask_mix_limit()))
            else:
                backend("retry", identifier)
            message("已將任務重新加入佇列；已成功下載的歌曲會跳過。")
        elif action == "開啟完整結果":
            subprocess.run(["/usr/bin/open", "-t", str(report)], check=False)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        mode = args[0] if args else None
        if mode is None:
            names = {"下載單首": "single", "下載整份播放清單": "playlist", "查看進度／重試／取消": "status"}
            mode = names[choose("選擇要執行的操作。", list(names))]
        if mode in {"single", "playlist"}:
            download(mode)
        elif mode == "status":
            status()
        else:
            raise FrontendError("操作類型無效，請重新安裝「youtube downloader」捷徑。")
        return 0
    except UserCancelled:
        return 0
    except (FrontendError, subprocess.TimeoutExpired, OSError) as error:
        problem = str(error) if isinstance(error, FrontendError) else "下載程式暫時無法回應。請稍候再試，或檢查安裝是否完整。"
        try:
            message(problem, "youtube downloader：無法完成")
        except (FrontendError, UserCancelled):
            pass
        print(problem, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
