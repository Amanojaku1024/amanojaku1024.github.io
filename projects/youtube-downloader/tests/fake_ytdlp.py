#!/usr/bin/env python3
"""Offline yt-dlp process double; configured only by test-owned fixture.json."""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from urllib.parse import parse_qs, urlparse

args = sys.argv[1:]
if "--version" in args:
    print("2026.10.26")
    raise SystemExit(0)
base = Path(__file__).parent
fixture = json.loads((base / "fixture.json").read_text())
with (base / "calls.jsonl").open("a") as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    stream.write(json.dumps(args, ensure_ascii=False) + "\n")

def opt(name, default=None):
    return args[args.index(name)+1] if name in args else default

url = args[-1]
parts = urlparse(url)
query = parse_qs(parts.query)
video_id = (query.get("v") or [parts.path.rsplit("/", 1)[-1]])[0]

if "--flat-playlist" in args:
    entries = []
    for item in fixture.get("playlist", []):
        if item is None:
            entries.append(None)
        else:
            video = fixture["videos"].get(item, {})
            entries.append({"id": item, "title": video.get("listing_title", video.get("title", "私人影片")),
                            "url": "https://www.youtube.com/watch?v=" + item,
                            "webpage_url": "https://www.youtube.com/watch?v=" + item,
                            "_type": "url", "ie_key": "Youtube"})
    print(json.dumps({"_type": "playlist", "id": "PLTEST", "title": "測試清單", "entries": entries}, ensure_ascii=False))
    raise SystemExit(0)

item = fixture["videos"].get(video_id)
if not item or item.get("error"):
    print("ERROR: [youtube] " + video_id + ": " + (item or {}).get("error", "Video unavailable"), file=sys.stderr)
    raise SystemExit(1)
time.sleep(item.get("sleep", 0))
info = {"id": video_id, "title": item.get("title", "測試歌曲"), "artist": item.get("artist", "測試歌手"),
        "extractor": "youtube", "extractor_key": "Youtube", "ext": "mp3", "duration": 0.3,
        "webpage_url": "https://www.youtube.com/watch?v=" + video_id}
if "track" in item:
    info["track"] = item["track"]
if any(flag in args for flag in ["--dump-single-json", "-J", "--dump-json", "-j"]):
    print(json.dumps(info, ensure_ascii=False))
    raise SystemExit(0)

template = opt("--output", opt("-o", "%(id)s.%(ext)s"))
out = template
for name, value in info.items():
    out = out.replace("%(" + name + ")s", str(value))
out = re.sub(r"%\([^)]+\)s", "NA", out)
target = Path(out).with_suffix(".mp3")
target.parent.mkdir(parents=True, exist_ok=True)
if item.get("corrupt"):
    target.write_bytes(b"not an MP3 file" * 20)
else:
    shutil.copyfile(base / item["fixture"], target)
info["filepath"] = str(target)
info["_filename"] = str(target)
target.with_suffix(".info.json").write_text(json.dumps(info, ensure_ascii=False))
if item.get("postprocess_error"):
    print("ERROR: Postprocessing: ffmpeg conversion failed", file=sys.stderr)
    raise SystemExit(1)
if "--print-to-file" in args:
    i = args.index("--print-to-file")
    template, path = args[i+1:i+3]
    value = str(target) if "filepath" in template else json.dumps(info, ensure_ascii=False)
    Path(path).write_text(value + "\n")
if "--print" in args:
    template = opt("--print")
    print(str(target) if "filepath" in template else json.dumps(info, ensure_ascii=False))
else:
    print("[download] 100% of test fixture")
