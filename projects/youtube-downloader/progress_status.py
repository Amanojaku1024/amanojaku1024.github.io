#!/usr/bin/env python3
"""Read-only live progress adapter for existing workers, without restarting downloads."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys

from music_downloader import DEFAULT_HOME, Engine, UserError

PHASES = {
    "queued": "等候下載", "listing": "讀取播放清單", "preparing": "準備歌曲／取得音訊資訊",
    "waiting": "等待 YouTube 排程", "downloading": "下載音訊", "transcoding": "處理音訊／轉換 MP3",
    "metadata": "寫入歌曲資訊", "cover": "處理／嵌入封面", "completed": "下載完成",
    "partial": "部分完成", "failed": "下載失敗", "cancelled": "已取消",
}


def parse_track_progress(log_text: str, video_id: str) -> dict:
    """Use only the current video's latest attempt; never reuse a previous song's %.

    Both older and current workers already produce newline yt-dlp progress. This
    bounded reader therefore works immediately for jobs running before UI updates.
    """
    result = {"phase": "preparing", "track_percent": None, "speed_text": "", "eta_text": ""}
    if not video_id:
        return result
    clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", log_text)
    starts = list(re.finditer(r"(?m)^\[youtube\] Extracting URL:\s*([^\r\n]+)", clean))
    if not starts:
        return result
    latest = starts[-1]
    # A newer song's output cannot be used for a stale SQLite snapshot either.
    if not re.search(r"(?:[?&]v=|/)(" + re.escape(video_id) + r")(?:[&#?\s]|$)", latest.group(1)):
        return result
    for line in clean[latest.end():].splitlines():
        if line.startswith(("[ExtractAudio]", "[FixupM4a]", "[FixupM3u8]", "[FixupTimestamp]", "[Merger]")):
            result.update(phase="transcoding", track_percent=None, speed_text="", eta_text="")
        elif line.startswith("[Metadata]"):
            result.update(phase="metadata", track_percent=None, speed_text="", eta_text="")
        elif line.startswith(("[EmbedThumbnail]", "[ThumbnailsConvertor]")):
            result.update(phase="cover", track_percent=None, speed_text="", eta_text="")
        elif line.startswith("[download]"):
            if "Sleeping" in line:
                result.update(phase="waiting", track_percent=None, speed_text="", eta_text="")
                continue
            match = re.search(r"\[download\]\s+([0-9]+(?:\.[0-9]+)?)%", line)
            if not match:
                continue
            percent = float(match.group(1))
            if not math.isfinite(percent) or not 0 <= percent <= 100:
                continue
            speed = re.search(r"\bat\s+([0-9.]+\s*[KMGTPE]?i?B/s)", line)
            eta = re.search(r"\bETA\s+([0-9:]+)", line)
            result.update(phase="downloading", track_percent=percent,
                          speed_text=speed.group(1) if speed else "",
                          eta_text=eta.group(1) if eta else "")
    return result


def enrich_status(job: dict, home: Path, library: Path) -> dict:
    data = dict(job)
    items = data.get("items", [])
    total = len(items) if items or data.get("enumerated") else None
    finished = sum(i.get("state") in ("downloaded", "skipped", "failed") for i in items)
    data.update(total=total, completed_items=finished,
                overall_percent=100 * finished / total if total else None,
                track_percent=None, speed_text="", eta_text="", current_title="",
                library=str(library), phase=data.get("state", "queued"))
    if data.get("state") == "running":
        current = next((item for item in items if item.get("state") == "running"), None)
        if current:
            data["current_title"] = current.get("title") or current.get("video_id") or ""
            data["current_position"] = current.get("position")
            # IDs are supplied by SQLite, but keep paths confined even for bad input.
            job_id = str(data.get("id", ""))
            if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", job_id):
                path = Path(home) / "logs" / (job_id + ".log")
                try:
                    with path.open("rb") as stream:
                        stream.seek(max(0, stream.seek(0, 2) - 128 * 1024))
                        data.update(parse_track_progress(stream.read().decode("utf-8", "replace"), str(current.get("video_id", ""))))
                except OSError:
                    data["phase"] = "preparing"
            else:
                data["phase"] = "preparing"
        else:
            data["phase"] = "listing" if not data.get("enumerated") else "preparing"
    data["phase_text"] = PHASES.get(data["phase"], str(data["phase"]))
    if data.get("cancel_requested") and data.get("state") in ("queued", "running"):
        data["phase_text"] = "正在取消，已完成歌曲會保留"
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="youtube downloader live progress")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("jobs")
    for command in ("status", "cancel", "retry"):
        child = sub.add_parser(command)
        child.add_argument("id")
        if command == "retry":
            child.add_argument("--playlist-limit", type=int)
    args = parser.parse_args(argv)
    engine = Engine(args.home)
    try:
        if args.command == "jobs":
            result = engine.jobs()
        elif args.command == "status":
            result = enrich_status(engine.status(args.id), engine.home, engine.library)
        elif args.command == "retry":
            result = engine.retry(args.id, args.playlist_limit)
        else:
            result = engine.cancel(args.id)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (UserError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc) if isinstance(exc, UserError) else "無法讀取進度，請稍後再試。"}, ensure_ascii=False))
        return 1
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
