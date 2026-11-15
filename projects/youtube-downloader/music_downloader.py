#!/usr/bin/env python3
"""MusicDownloader: standard-library-only queue, SQLite index and yt-dlp worker."""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import unicodedata
from urllib.parse import parse_qs, urlsplit
import uuid

DEFAULT_HOME = Path.home() / "Library/Application Support/MusicDownloader"
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{2,200}$")
DEFAULT_CATEGORIES = ["日文", "華語", "英文", "古典", "純音樂"]


class UserError(Exception):
    pass


class Cancelled(UserError):
    pass


def normalize_url(value: str, mode: str) -> str:
    if mode not in ("single", "playlist"):
        raise UserError("請選擇下載單首或播放清單。")
    value = str(value).strip()
    if len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise UserError("網址格式不正確。")
    try:
        u = urlsplit(value)
        if u.scheme not in ("https", "http") or u.username or u.password or u.port not in (None, 80, 443):
            raise ValueError()
        host = (u.hostname or "").lower()
        if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}:
            raise ValueError()
        q = parse_qs(u.query)
        if mode == "playlist":
            playlist = q.get("list", [""])[0]
            if not PLAYLIST_ID.fullmatch(playlist):
                raise UserError("請貼上包含 list= 的 YouTube 或 YouTube Music 播放清單網址。")
            if playlist.startswith("RD"):
                seed = q.get("v", [""])[0]
                if host.endswith("youtu.be"):
                    seed = u.path.strip("/")
                if not VIDEO_ID.fullmatch(seed) and VIDEO_ID.fullmatch(playlist[2:]):
                    seed = playlist[2:]
                if not VIDEO_ID.fullmatch(seed):
                    raise UserError("這是 YouTube Mix 推薦清單，請從歌曲播放頁複製完整網址（包含 v= 與 list=）。")
                return "https://www.youtube.com/watch?v=" + seed + "&list=" + playlist
            return "https://www.youtube.com/playlist?list=" + playlist
        if host.endswith("youtu.be"):
            video = u.path.strip("/")
        elif u.path.rstrip("/") == "/watch":
            video = q.get("v", [""])[0]
        elif u.path.split("/")[1:2] in (["shorts"], ["live"], ["embed"]):
            video = u.path.split("/")[2] if len(u.path.split("/")) > 2 else ""
        else:
            video = ""
        if not VIDEO_ID.fullmatch(video):
            raise ValueError()
        return "https://www.youtube.com/watch?v=" + video
    except (ValueError, TypeError):
        raise UserError("請輸入有效的 YouTube 或 YouTube Music 歌曲網址。") from None


def is_mix_url(url: str) -> bool:
    return parse_qs(urlsplit(url).query).get("list", [""])[0].startswith("RD")


def validate_playlist_limit(mode: str, url: str, value: int | None) -> int | None:
    if mode == "playlist" and is_mix_url(url):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 500:
            raise UserError("YouTube Mix 是持續更新的推薦清單，請先選擇下載前幾首（1–500 首）。從捷徑重試時會詢問首數。")
        return value
    if mode == "playlist" and value is not None:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10000:
            raise UserError("播放清單首數請選擇 1–10000；也可以在視窗輸入 0 選擇全部。")
        return value
    if value is not None:
        raise UserError("單首下載不需要設定播放清單首數。")
    return None


def job_fingerprint(mode: str, url: str, category: str, playlist_limit: int | None, options: dict | None = None) -> str:
    values = [mode, url, category]
    if playlist_limit is not None:
        values.append(playlist_limit)
    if options:
        values.append(options)
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def validate_category(value: str) -> str:
    name = unicodedata.normalize("NFC", str(value).strip())
    if (not name or name in {".", ".."} or name.startswith(".") or
            any(c in '/\\:' or unicodedata.category(c).startswith("C") for c in name) or
            len(name.encode("utf-8")) > 100):
        raise UserError("分類名稱不可空白、以句點開頭，或包含 /、\\、冒號及控制字元；請使用較短的名稱。")
    return name


def validate_options(mode: str, playlist_limit: int | None, routes=None,
                     auto_piano: bool = False, piano_category: str = "鋼琴") -> dict:
    if not isinstance(auto_piano, bool):
        raise UserError("自動辨識鋼琴的設定不正確，請重新選擇分類方式。")
    if routes is None:
        routes = []
    if not isinstance(routes, list) or len(routes) > 100:
        raise UserError("分配規則必須是清單，最多 100 組。")
    if mode == "single" and routes:
        raise UserError("依序號分配只適用於播放清單。")
    cleaned = []
    for route in routes:
        if not isinstance(route, dict):
            raise UserError("分配規則格式不正確。")
        start, end = route.get("start"), route.get("end")
        maximum = playlist_limit if playlist_limit is not None else 10000
        if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or
                not isinstance(end, int) or not 1 <= start <= end <= maximum):
            raise UserError(f"分配範圍須為第 1–{maximum} 首之間，且結束序號不可小於開始序號。")
        if not isinstance(route.get("category"), str):
            raise UserError("請為每個分配範圍選擇音樂分類。")
        cleaned.append({"start": start, "end": end, "category": validate_category(route["category"])})
    cleaned.sort(key=lambda r: r["start"])
    if any(a["end"] >= b["start"] for a, b in zip(cleaned, cleaned[1:])):
        raise UserError("歌曲分配範圍不能重疊，請調整序號後重試。")
    if not cleaned and not auto_piano:
        return {}
    options = {"routes": cleaned, "auto_piano": auto_piano}
    if auto_piano:
        options["piano_category"] = validate_category(piano_category)
    return options


def is_piano_title(title: str) -> bool:
    """Conservative title keywords only; no audio analysis or duplicate matching."""
    title = unicodedata.normalize("NFKC", str(title)).casefold()
    negative = (r"\b(?:no|not|without|non)[\s_-]*piano\b|\bpiano[\s_-]*(?:free|less)\b|"
                r"(?:非|無|无|不是)[鋼钢]琴|ピアノ(?:なし|無し|以外)|피아노\s*없")
    if re.search(negative, title):
        return False
    return bool(re.search(r"鋼琴|钢琴|ピアノ|피아노|(?<![a-z])piano(?:forte)?(?![a-z])|\bklavier\b", title))


def select_category(job: dict, item: dict, video_title: str) -> tuple[str, str]:
    options = job.get("options") or json.loads(job.get("options_json") or "{}")
    for route in options.get("routes", []):
        if route["start"] <= item["position"] <= route["end"]:
            return route["category"], f"手動分配：第 {route['start']}–{route['end']} 首"
    if options.get("auto_piano") and is_piano_title(video_title):
        return options.get("piano_category", "鋼琴"), "影片標題含鋼琴相關字樣（文字判斷）"
    return job["category"], "預設分類"


def clean_title(value: str) -> str:
    name = unicodedata.normalize("NFC", str(value))
    name = "".join(" " if c in '/\\:*?"<>|' or unicodedata.category(c).startswith("C") else c for c in name)
    name = re.sub(r"\s+", " ", name).strip(" .") or "未命名歌曲"
    while len(name.encode("utf-8")) > 180:
        name = name[:-1]
    return name


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rename_exclusive(source: Path, target: Path):
    """macOS atomic rename with RENAME_EXCL: an existing file is never replaced."""
    if sys.platform != "darwin":
        os.link(source, target)
        source.unlink()
        return
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    function = libc.renamex_np
    function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(os.fsencode(source), os.fsencode(target), 0x00000004):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def notify(message: str, title: str = "youtube downloader") -> None:
    if sys.platform != "darwin" or os.environ.get("MUSIC_DOWNLOADER_NO_NOTIFY"):
        return
    script = 'on run argv\n display notification (item 1 of argv) with title (item 2 of argv)\nend run'
    try:
        subprocess.run(["/usr/bin/osascript", "-e", script, message, title],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        pass


class Engine:
    def __init__(self, home: Path = DEFAULT_HOME, library: Path | None = None,
                 ytdlp: str | None = None, ffmpeg: str | None = None, ffprobe: str | None = None):
        self.home = Path(home).expanduser().absolute()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        config_path = self.home / "config.json"
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        self.library = Path(library or config.get("library", str(Path.home() / "Desktop/音樂"))).expanduser().absolute()
        self.ytdlp = ytdlp or config.get("ytdlp") or shutil.which("yt-dlp") or "/opt/homebrew/bin/yt-dlp"
        self.ffmpeg = ffmpeg or config.get("ffmpeg") or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
        self.ffprobe = ffprobe or config.get("ffprobe") or shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
        self.deno = config.get("deno") or shutil.which("deno")
        self.min_free = int(config.get("min_free_bytes", 256 * 1024 * 1024))
        for folder in ("logs", "staging", "reports"):
            (self.home / folder).mkdir(exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.home / "library.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS assets(path TEXT PRIMARY KEY, sha256 TEXT NOT NULL,
                size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS assets_hash ON assets(sha256);
            CREATE TABLE IF NOT EXISTS videos(video_id TEXT PRIMARY KEY, path TEXT NOT NULL, sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                mode TEXT NOT NULL, url TEXT NOT NULL, category TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                cancel_requested INTEGER NOT NULL DEFAULT 0, enumerated INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '', downloaded INTEGER NOT NULL DEFAULT 0,
                skipped INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
                playlist_limit INTEGER, options_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS items(job_id TEXT NOT NULL REFERENCES jobs(id),
                position INTEGER NOT NULL, video_id TEXT, title TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'pending', path TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '', PRIMARY KEY(job_id, position));
        ''')
        self.db.commit()
        # Upgrade the original installed database in place; retain music and jobs.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if "playlist_limit" not in {r[1] for r in self.db.execute("PRAGMA table_info(jobs)")}:
                self.db.execute("ALTER TABLE jobs ADD COLUMN playlist_limit INTEGER")
            if "options_json" not in {r[1] for r in self.db.execute("PRAGMA table_info(jobs)")}:
                self.db.execute("ALTER TABLE jobs ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}'")
            item_columns = {r[1] for r in self.db.execute("PRAGMA table_info(items)")}
            for column in ("category", "reason"):
                if column not in item_columns:
                    self.db.execute(f"ALTER TABLE items ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        self.log = logging.getLogger("MusicDownloader." + str(self.home))
        self.log.setLevel(logging.INFO)
        if not self.log.handlers:
            handler = RotatingFileHandler(self.home / "logs/engine.log", maxBytes=2_000_000, backupCount=3)
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.log.addHandler(handler)
        self.stopping = False
        self.worker_fd = None
        self.last_category_refresh = 0.0

    def close(self):
        self.db.close()

    def categories(self) -> list[str]:
        """The shortcut reads private state only; Desktop access belongs to worker."""
        existing = []
        try:
            cached = json.loads((self.home / "categories.json").read_text())
            if isinstance(cached, list):
                existing.extend(name for name in cached if isinstance(name, str))
        except (OSError, ValueError):
            pass
        for row in self.db.execute("SELECT path FROM assets"):
            try:
                parts = Path(row[0]).relative_to(self.library).parts
                if len(parts) > 1:
                    existing.append(parts[0])
            except ValueError:
                continue
        valid = []
        for name in existing:
            try:
                valid.append(validate_category(name))
            except UserError:
                continue
        return list(dict.fromkeys(DEFAULT_CATEGORIES + sorted(set(valid))))

    def refresh_categories(self):
        """Called by the background worker, which owns music-directory access."""
        self.library.mkdir(parents=True, exist_ok=True)
        existing = [p.name for p in self.library.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")]
        temporary = self.home / "categories.tmp"
        temporary.write_text(json.dumps(existing, ensure_ascii=False))
        temporary.replace(self.home / "categories.json")

    def category_path(self, category: str) -> Path:
        target = self.library / validate_category(category)
        self.library.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise UserError("這個分類是替身連結，請改用一般資料夾。")
        target.mkdir(exist_ok=True)
        if target.resolve().parent != self.library.resolve():
            raise UserError("分類資料夾不在音樂目錄內。")
        return target

    def enqueue(self, mode: str, url: str, category: str, playlist_limit: int | None = None,
                routes=None, auto_piano: bool = False, piano_category: str = "鋼琴") -> dict:
        url, category = normalize_url(url, mode), validate_category(category)
        playlist_limit = validate_playlist_limit(mode, url, playlist_limit)
        options = validate_options(mode, playlist_limit, routes, auto_piano, piano_category)
        fingerprint = job_fingerprint(mode, url, category, playlist_limit, options)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM jobs WHERE fingerprint=? AND state IN ('queued','running')", (fingerprint,)).fetchone()
            if row:
                result = dict(row)
                result["already_queued"] = True
                return result
            job_id = uuid.uuid4().hex[:12]
            now = time.time()
            self.db.execute("INSERT INTO jobs(id,fingerprint,mode,url,category,state,created,updated,playlist_limit,options_json) VALUES(?,?,?,?,?,'queued',?,?,?,?)",
                            (job_id, fingerprint, mode, url, category, now, now, playlist_limit, json.dumps(options, ensure_ascii=False)))
        return self.status(job_id)

    def jobs(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 100")]

    def status(self, job_id: str) -> dict:
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise UserError("找不到這個下載任務。")
        result = dict(row)
        result["options"] = json.loads(result["options_json"])
        result["routes"] = result["options"].get("routes", [])
        result["auto_piano"] = result["options"].get("auto_piano", False)
        result["piano_category"] = result["options"].get("piano_category", "鋼琴")
        result["items"] = [dict(r) for r in self.db.execute("SELECT * FROM items WHERE job_id=? ORDER BY position", (job_id,))]
        result["total"] = len(result["items"])
        current = next((i for i in result["items"] if i["state"] == "running"), None)
        if current:
            result["progress"] = f"正在處理第 {current['position']}／{result['total']} 首：{current['title'] or current['video_id']}"
        result["report"] = str(self.home / "reports" / (job_id + ".txt"))
        return result

    def cancel(self, job_id: str) -> dict:
        with self.db:
            self.db.execute("UPDATE jobs SET cancel_requested=1,updated=? WHERE id=? AND state IN ('queued','running')", (time.time(), job_id))
        return self.status(job_id)

    def retry(self, job_id: str, playlist_limit: int | None = None) -> dict:
        old = self.status(job_id)
        if old["state"] in ("queued", "running"):
            return old
        url = normalize_url(old["url"], old["mode"])
        limit = validate_playlist_limit(old["mode"], url, playlist_limit if playlist_limit is not None else old["playlist_limit"])
        if old["enumerated"] and old["playlist_limit"] is not None and limit != old["playlist_limit"]:
            raise UserError("重試會沿用原本的清單範圍；若要變更首數，請建立新的下載任務。")
        if old["enumerated"] and limit is not None and len(old["items"]) > limit:
            raise UserError("舊任務的範圍超過所選首數，請建立新的 Mix 下載任務。")
        options = validate_options(old["mode"], limit, old["routes"], old["auto_piano"], old["piano_category"])
        fingerprint = job_fingerprint(old["mode"], url, old["category"], limit, options)
        # Retain verified successes and partial source files; retry just unfinished items.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            active = self.db.execute("SELECT * FROM jobs WHERE fingerprint=? AND state IN ('queued','running')", (fingerprint,)).fetchone()
            if active:
                return dict(active)
            self.db.execute("UPDATE items SET state='pending',error='' WHERE job_id=? AND state IN ('failed','running')", (job_id,))
            self.db.execute("UPDATE jobs SET state='queued',cancel_requested=0,error='',url=?,playlist_limit=?,fingerprint=?,updated=? WHERE id=?", (url, limit, fingerprint, time.time(), job_id))
        return self.status(job_id)

    def check_cancel(self, job_id: str):
        row = self.db.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
        if self.stopping or row[0]:
            raise Cancelled("下載已取消；已完成的歌曲會保留，可稍後重試。" if not self.stopping else "背景服務已停止，稍後自動恢復。")

    def run_tool(self, args: list[str], job_id: str, output: Path | None = None, timeout: int = 7200):
        """No shell. Poll cancellation, deadline and free space while logging progress."""
        logpath = self.home / "logs" / (job_id + ".log")
        self.log.info("job=%s exec=%r", job_id, args)
        with logpath.open("ab") as log, contextlib.ExitStack() as stack:
            log_start = log.tell()
            out = stack.enter_context(output.open("wb")) if output else log
            # Inherit the flock into yt-dlp: even SIGKILL of this worker cannot let a
            # restarted worker race a still-running downloader in the same staging dir.
            inherited = (self.worker_fd,) if self.worker_fd is not None else ()
            proc = subprocess.Popen(args, stdout=out, stderr=log, start_new_session=True, pass_fds=inherited)
            started, last_space_check = time.monotonic(), 0.0
            try:
                while proc.poll() is None:
                    self.check_cancel(job_id)
                    if time.monotonic() - started > timeout:
                        raise UserError("連線或下載逾時，請稍後重試。")
                    if time.monotonic() - last_space_check > 5:
                        self.check_space()
                        last_space_check = time.monotonic()
                    time.sleep(0.2)
                if proc.returncode:
                    raise UserError(self.friendly_error(logpath, log_start))
            except BaseException:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                raise

    @staticmethod
    def friendly_error(logpath: Path, start: int = 0) -> str:
        with logpath.open("rb") as f:
            f.seek(max(start, f.seek(0, 2) - 16000))
            text = f.read().decode("utf-8", "replace").lower()
        if "no space left" in text:
            return "可用磁碟空間不足，請騰出空間後重試。"
        if "playlist type is unviewable" in text:
            return "YouTube 無法讀取這種清單；若是 Mix，請從播放頁複製包含 v= 與 list= 的完整網址後重試。"
        if any(s in text for s in ("playlist does not exist", "playlist is private", "failed to resolve url")):
            return "無法讀取播放清單，請確認網址正確，且清單為公開或不公開可分享。"
        if any(s in text for s in ("private video", "video is private", "video unavailable", "video is unavailable", "removed", "not available", "members-only")):
            return "影片無法取得，可能已刪除、設為私人或有限制。"
        if any(s in text for s in ("sign in", "bot", "403", "429", "nsig", "signature", "javascript")):
            return "YouTube 暫時拒絕連線或需要驗證；請稍後重試，必要時更新 yt-dlp。"
        if any(s in text for s in ("timed out", "network", "resolve", "connection")):
            return "網路連線中斷或逾時，請確認網路後重試。"
        return "這首歌曲下載或轉換失敗；其他歌曲會繼續，詳情已記錄。"

    def base_args(self) -> list[str]:
        args = [self.ytdlp, "--ignore-config", "--no-plugin-dirs", "--no-exec", "--socket-timeout", "30", "--retries", "3", "--fragment-retries", "3", "--encoding", "utf-8"]
        if self.deno:
            args += ["--js-runtimes", "deno:" + self.deno]
        return args

    def check_space(self):
        for path in (self.home, self.library):
            if shutil.disk_usage(path).free < self.min_free:
                raise UserError("可用磁碟空間不足（需保留至少 256 MB），請騰出空間後重試。")

    def scan_library(self):
        """Index exact bytes of existing MP3s, never change a personal file."""
        known = {r["path"]: r for r in self.db.execute("SELECT * FROM assets")}
        seen = set()
        for directory, dirs, files in os.walk(self.library, followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith(".") and not (Path(directory) / d).is_symlink()]
            for filename in files:
                path = Path(directory) / filename
                if path.suffix.lower() != ".mp3" or path.is_symlink():
                    continue
                key = str(path)
                try:
                    stat = path.stat()
                    row = known.get(key)
                    digest = row["sha256"] if row and row["size"] == stat.st_size and row["mtime_ns"] == stat.st_mtime_ns else sha256(path)
                    with self.db:
                        self.db.execute("INSERT OR REPLACE INTO assets VALUES(?,?,?,?)", (key, digest, stat.st_size, stat.st_mtime_ns))
                    seen.add(key)
                except FileNotFoundError:
                    continue
        with self.db:
            for key in set(known) - seen:
                self.db.execute("DELETE FROM assets WHERE path=?", (key,))

    def existing_video(self, video_id: str) -> str | None:
        row = self.db.execute("SELECT a.path,a.size,v.sha256 FROM videos v JOIN assets a ON a.path=v.path WHERE v.video_id=?", (video_id,)).fetchone()
        if not row:
            return None
        path = Path(row["path"])
        try:
            stat = path.stat()
            # Modified/replaced files cannot permanently block a fresh download.
            if not path.is_symlink() and stat.st_size == row["size"] and sha256(path) == row["sha256"]:
                return str(path)
        except FileNotFoundError:
            pass
        with self.db:
            self.db.execute("DELETE FROM videos WHERE video_id=?", (video_id,))
        return None

    def enumerate_items(self, job: dict, stage: Path):
        if job["mode"] == "playlist":
            validate_playlist_limit("playlist", job["url"], job.get("playlist_limit"))
        if job["enumerated"]:
            return
        if job["mode"] == "single":
            entries = [{"id": parse_qs(urlsplit(job["url"]).query)["v"][0]}]
        else:
            metadata = stage / "playlist.json"
            url = normalize_url(job["url"], "playlist")
            limit = validate_playlist_limit("playlist", url, job.get("playlist_limit"))
            bounds = ["--playlist-end", str(limit)] if limit is not None else []
            # Ignore unavailable entries only at the listing stage. Each download is strict.
            self.run_tool(self.base_args() + ["--flat-playlist", "--dump-single-json", "--yes-playlist", "--ignore-errors"] + bounds + ["--", url], job["id"], metadata, 1800)
            if metadata.stat().st_size > 100 * 1024 * 1024:
                raise UserError("播放清單資料過大，請拆成較小清單。")
            info = json.loads(metadata.read_text())
            if not isinstance(info, dict):
                raise UserError("無法讀取播放清單資料，請確認網址或稍後重試。")
            entries = info.get("entries")
            if not isinstance(entries, list):
                raise UserError("無法讀取播放清單，請確認清單是公開或可存取的。")
            if not entries:
                raise UserError("播放清單沒有可讀取的歌曲。")
            if limit is not None:
                entries = entries[:limit]
        with self.db:
            self.db.execute("DELETE FROM items WHERE job_id=?", (job["id"],))
            for index, entry in enumerate(entries, 1):
                entry = entry or {}
                vid = str(entry.get("id", ""))
                valid = bool(VIDEO_ID.fullmatch(vid))
                title = str(entry.get("title", ""))
                category, reason = select_category(job, {"position": index}, title)
                self.db.execute("INSERT INTO items(job_id,position,video_id,title,state,error,category,reason) VALUES(?,?,?,?,?,?,?,?)",
                    (job["id"], index, vid, title, "pending" if valid else "failed", "" if valid else "此播放清單項目已刪除或無法讀取。", category, reason))
            self.db.execute("UPDATE jobs SET enumerated=1 WHERE id=?", (job["id"],))

    def verify_audio(self, path: Path):
        if not path.is_file() or path.stat().st_size < 32:
            raise UserError("轉換後沒有完整 MP3，請重試。")
        result = subprocess.run([self.ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name:format=duration", "-of", "json", str(path)], capture_output=True, text=True, timeout=30)
        try:
            data = json.loads(result.stdout)
            if result.returncode or not any(s.get("codec_name") == "mp3" and s.get("codec_type") == "audio" for s in data.get("streams", [])) or float(data.get("format", {}).get("duration", 0)) <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise UserError("MP3 驗證失敗，這首歌曲未列為成功。") from None

    def publish(self, path: Path, video_id: str, title: str, category: str) -> tuple[str, str]:
        digest = sha256(path)
        for row in self.db.execute("SELECT * FROM assets WHERE sha256=?", (digest,)):
            original = Path(row["path"])
            if original.is_file() and not original.is_symlink() and sha256(original) == digest:
                with self.db:
                    self.db.execute("INSERT OR REPLACE INTO videos VALUES(?,?,?)", (video_id, str(original), digest))
                return "skipped", str(original)
        destination = self.category_path(category)
        base = clean_title(title)
        # Hard-link promotion is atomic and never replaces a destination. If a different
        # volume hosts Desktop, prepare a private sibling staging area on that volume.
        alternate = None
        try:
            for number in range(10000):
                suffix = "" if number == 0 else f" [{video_id}]" if number == 1 else f" [{video_id}-{number}]"
                target = destination / (base + suffix + ".mp3")
                try:
                    os.link(path, target)
                except FileExistsError:
                    continue
                except OSError as exc:
                    if exc.errno not in (errno.EXDEV, errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP):
                        raise
                    sibling = self.library.parent / ".MusicDownloader-staging"
                    sibling.mkdir(mode=0o700, exist_ok=True)
                    if sibling.is_symlink() or sibling.stat().st_uid != os.getuid():
                        raise UserError("跨磁碟暫存資料夾不安全，請檢查音樂位置。")
                    if alternate is None:
                        alternate = sibling / (uuid.uuid4().hex + ".tmp")
                        with path.open("rb") as reader, alternate.open("xb") as writer:
                            shutil.copyfileobj(reader, writer)
                            writer.flush()
                            os.fsync(writer.fileno())
                    try:
                        rename_exclusive(alternate, target)
                    except FileExistsError:
                        continue
                    alternate = None
                stat = target.stat()
                with self.db:
                    self.db.execute("INSERT OR REPLACE INTO assets VALUES(?,?,?,?)", (str(target), digest, stat.st_size, stat.st_mtime_ns))
                    self.db.execute("INSERT OR REPLACE INTO videos VALUES(?,?,?)", (video_id, str(target), digest))
                return "downloaded", str(target)
            raise UserError("同名檔案太多，請改用其他分類。")
        finally:
            if alternate:
                alternate.unlink(missing_ok=True)

    def process_item(self, job: dict, item: dict, stage: Path) -> tuple[str, str, str, str, str]:
        original = self.existing_video(item["video_id"])
        if original:
            return "skipped", original, item["title"], Path(original).parent.name, "影片已存在，保留原始位置（未移動）"
        self.check_space()
        item_stage = stage / item["video_id"]
        item_stage.mkdir(exist_ok=True)
        audio = item_stage / "song.mp3"
        marker = item_stage / "complete.json"
        if marker.exists() and audio.exists():
            metadata = json.loads(marker.read_text())
        else:
            # Only our private staged output is removed here. An interrupted
            # postprocessor must never be mistaken for a verified final MP3.
            audio.unlink(missing_ok=True)
            args = self.base_args() + ["--no-playlist", "--no-abort-on-error", "--no-overwrites", "--continue", "--newline", "--progress", "--progress-delta", "3",
                "-f", "bestaudio/best", "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0", "--embed-metadata", "--no-embed-chapters", "--no-embed-info-json",
                "--embed-thumbnail", "--convert-thumbnails", "jpg", "--write-info-json", "--ffmpeg-location", str(Path(self.ffmpeg).parent),
                "--output", str(item_stage / "song.%(ext)s"), "--", "https://www.youtube.com/watch?v=" + item["video_id"]]
            self.run_tool(args, job["id"])
            info_path = item_stage / "song.info.json"
            metadata = json.loads(info_path.read_text()) if info_path.exists() else {}
            self.verify_audio(audio)
            marker.write_text(json.dumps(metadata, ensure_ascii=False))
        self.verify_audio(audio)
        title = metadata.get("track") or metadata.get("title") or item["title"] or item["video_id"]
        video_title = metadata.get("title") or item["title"] or ""
        category, reason = select_category(job, item, video_title)
        state, output = self.publish(audio, item["video_id"], title, category)
        if state == "skipped":
            category, reason = Path(output).parent.name, "音檔內容完全相同，保留原始位置（未移動）"
        shutil.rmtree(item_stage)
        return state, output, title, category, reason

    def write_report(self, job_id: str):
        data = self.status(job_id)
        counts = {name: sum(i["state"] == name for i in data["items"]) for name in ("downloaded", "skipped", "failed")}
        with self.db:
            self.db.execute("UPDATE jobs SET downloaded=?,skipped=?,failed=?,updated=? WHERE id=?", (*counts.values(), time.time(), job_id))
        lines = ["youtube downloader", f"任務：{job_id}", f"狀態：{data['state']}", f"分類：{data['category']}",
                 f"下載 {counts['downloaded']} 首／跳過 {counts['skipped']} 首／失敗 {counts['failed']} 首", data["error"], ""]
        if data["playlist_limit"] is not None:
            label = "YouTube Mix" if is_mix_url(data["url"]) else "播放清單"
            lines.insert(4, f"{label}：本次擷取前 {data['playlist_limit']} 首。")
        options = data["options"]
        if options.get("auto_piano"):
            lines.append(f"自動鋼琴分類：{options.get('piano_category', '鋼琴')}（僅依影片標題判斷；手動分配優先）")
        for route in options.get("routes", []):
            lines.append(f"手動分配：第 {route['start']}–{route['end']} 首 → {route['category']}")
            if data["enumerated"] and route["end"] > len(data["items"]):
                lines.append("  注意：這個範圍部分或全部超出本次取得的歌曲數量。")
        labels = {"downloaded": "已下載", "skipped": "已跳過（原始位置）", "failed": "失敗", "pending": "等待", "running": "下載中"}
        for item in data["items"]:
            lines.append(f"{item['position']}. {labels.get(item['state'], item['state'])}：{item['title'] or item['video_id']}\n   {item['path'] or item['error']}\n   分類：{item['category']}；原因：{item['reason']}")
        report = Path(data["report"])
        temp = report.with_suffix(".tmp")
        temp.write_text("\n".join(lines), encoding="utf-8")
        temp.replace(report)

    def process_next(self) -> bool:
        with (self.home / "worker.lock").open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            self.worker_fd = lock.fileno()
            if time.monotonic() - self.last_category_refresh > 30:
                self.last_category_refresh = time.monotonic()
                try:
                    self.refresh_categories()
                except OSError:
                    self.log.exception("Unable to refresh category cache")
            with self.db:
                self.db.execute("UPDATE jobs SET state='queued' WHERE state='running'")
                self.db.execute("UPDATE items SET state='pending' WHERE state='running'")
            row = self.db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return False
            job = dict(row)
            with self.db:
                self.db.execute("UPDATE jobs SET state='running',error='',updated=? WHERE id=?", (time.time(), job["id"]))
            stage = self.home / "staging" / job["id"]
            stage.mkdir(exist_ok=True)
            final_state, error = "completed", ""
            try:
                self.check_cancel(job["id"])
                for tool in (self.ytdlp, self.ffmpeg, self.ffprobe):
                    if not os.access(tool, os.X_OK):
                        raise UserError("找不到必要工具，請重新執行安裝程式修復 yt-dlp／ffmpeg。")
                self.category_path(job["category"])
                self.check_space()
                self.scan_library()
                self.enumerate_items(job, stage)
                # Check saved paths here, never from a shortcut-owned retry process.
                with self.db:
                    for saved in self.db.execute("SELECT position,path FROM items WHERE job_id=? AND state IN ('downloaded','skipped')", (job["id"],)).fetchall():
                        if not Path(saved["path"]).is_file():
                            self.db.execute("UPDATE items SET state='pending',path='',error='' WHERE job_id=? AND position=?", (job["id"], saved["position"]))
                self.write_report(job["id"])
                items = [dict(r) for r in self.db.execute("SELECT * FROM items WHERE job_id=? AND state='pending' ORDER BY position", (job["id"],))]
                for item in items:
                    self.check_cancel(job["id"])
                    category, reason = select_category(job, item, item["title"])
                    with self.db:
                        self.db.execute("UPDATE items SET state='running',category=?,reason=? WHERE job_id=? AND position=?", (category, reason, job["id"], item["position"]))
                    self.write_report(job["id"])
                    try:
                        state, output, title, category, reason = self.process_item(job, item, stage)
                        with self.db:
                            self.db.execute("UPDATE items SET state=?,path=?,title=?,category=?,reason=?,error='' WHERE job_id=? AND position=?", (state, output, title, category, reason, job["id"], item["position"]))
                    except Cancelled:
                        with self.db:
                            self.db.execute("UPDATE items SET state='pending' WHERE job_id=? AND position=?", (job["id"], item["position"]))
                        raise
                    except Exception as exc:
                        self.log.exception("job=%s video=%s", job["id"], item["video_id"])
                        message = str(exc) if isinstance(exc, UserError) else "歌曲處理失敗，技術細節已記錄。"
                        with self.db:
                            self.db.execute("UPDATE items SET state='failed',error=? WHERE job_id=? AND position=?", (message, job["id"], item["position"]))
                    self.write_report(job["id"])
                if self.db.execute("SELECT count(*) FROM items WHERE job_id=? AND state='failed'", (job["id"],)).fetchone()[0]:
                    successes = self.db.execute("SELECT count(*) FROM items WHERE job_id=? AND state IN ('downloaded','skipped')", (job["id"],)).fetchone()[0]
                    final_state = "partial" if successes else "failed"
            except Cancelled as exc:
                final_state, error = ("queued" if self.stopping else "cancelled"), str(exc)
            except Exception as exc:
                self.log.exception("job=%s failed", job["id"])
                final_state = "failed"
                error = str(exc) if isinstance(exc, UserError) else "任務處理失敗，請查看報告或稍後重試。"
            with self.db:
                self.db.execute("UPDATE jobs SET state=?,error=?,updated=? WHERE id=?", (final_state, error, time.time(), job["id"]))
            self.write_report(job["id"])
            if final_state in ("completed", "partial", "cancelled", "failed"):
                data = self.status(job["id"])
                prefix = "下載完成" if final_state == "completed" else "部分完成" if final_state == "partial" else "已取消" if final_state == "cancelled" else "下載失敗"
                notify(f"{prefix}：下載 {data['downloaded']}、跳過 {data['skipped']}、失敗 {data['failed']}。詳情見「查看下載狀態」。" + (" " + error if error else ""))
            if final_state == "completed":
                shutil.rmtree(stage)
            return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="youtube downloader 背景引擎")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("categories", "submit-json", "jobs", "worker", "process-next"):
        sub.add_parser(cmd)
    for cmd in ("status", "cancel"):
        sub.add_parser(cmd).add_argument("id")
    retry_parser = sub.add_parser("retry")
    retry_parser.add_argument("id")
    retry_parser.add_argument("--playlist-limit", type=int)
    args = parser.parse_args(argv)
    engine = Engine(args.home)
    try:
        if args.command == "worker":
            def stop(signum, frame):
                engine.stopping = True
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            while not engine.stopping:
                if not engine.process_next():
                    time.sleep(2)
            return 0
        if args.command == "submit-json":
            payload = sys.stdin.read(262145)
            if len(payload) > 262144:
                raise UserError("分配設定資料太多，請減少分配範圍後重試。")
            data = json.loads(payload)
            result = engine.enqueue(data["mode"], data["url"], data["category"], data.get("playlist_limit"),
                                    data.get("routes"), data.get("auto_piano", False), data.get("piano_category", "鋼琴"))
        elif args.command == "categories":
            result = engine.categories()
        elif args.command == "jobs":
            result = engine.jobs()
        elif args.command == "process-next":
            result = engine.process_next()
        elif args.command == "retry":
            result = engine.retry(args.id, args.playlist_limit)
        else:
            result = getattr(engine, args.command)(args.id)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (UserError, OSError, ValueError, KeyError) as exc:
        engine.log.exception("CLI error")
        message = str(exc) if isinstance(exc, UserError) else "無法完成操作，請確認桌面存取權限、磁碟空間與安裝狀態。"
        print(json.dumps({"error": message}, ensure_ascii=False))
        return 1
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
