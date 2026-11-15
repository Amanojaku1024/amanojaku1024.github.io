#!/usr/bin/env python3
"""Drive real AppKit controls via an isolated in-process exercise hook.

This is not external mouse/keyboard E2E automation. No production engine is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SENTINEL = {"kind": "MusicDownloaderUIFixture", "version": 1}
BACKEND = '''# MusicDownloaderUIFixture: isolated, read-only UI exercise backend.
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--home", type=Path, required=True)
parser.add_argument("command")
parser.add_argument("id", nargs="?")
parser.add_argument("--playlist-limit", type=int)
args = parser.parse_args()
home = args.home.resolve()
safe = (os.environ.get("MUSIC_DOWNLOADER_UI_EXERCISE") == "1"
        and home == Path(__file__).resolve().parent
        and json.loads((home / ".musicdownloader-ui-fixture.json").read_text())
        == {"kind": "MusicDownloaderUIFixture", "version": 1})
if not safe:
    raise SystemExit("Fixture guard rejected the request")
with (home / "backend-calls.jsonl").open("a") as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    stream.write(json.dumps({"command": args.command, "id": args.id, "playlist_limit": args.playlist_limit,
                             "argv": sys.argv[1:], "pid": os.getpid(), "time": time.time()}) + "\\n")
jobs = json.loads((home / "fixture.json").read_text())["jobs"]
if args.command == "retry" and args.id == "fixture-legacy-mix" and args.playlist_limit == 25:
    job = next(job for job in jobs if job["id"] == args.id)
    job.update(state="queued", phase="queued", phase_text="等候下載（隔離UI fixture）", playlist_limit=25)
    temporary = home / "fixture-update.json"
    temporary.write_text(json.dumps({"jobs": jobs}, ensure_ascii=False))
    temporary.replace(home / "fixture.json")
    print(json.dumps(job, ensure_ascii=False))
    raise SystemExit(0)
if args.command not in {"jobs", "status"}:
    print(json.dumps({"error": "UI fixture forbids cancel, retry and downloads"}))
    raise SystemExit(3)
if args.command == "jobs":
    print(json.dumps([{k: v for k, v in job.items() if k != "items"} for job in jobs], ensure_ascii=False))
else:
    job = next((job for job in jobs if job["id"] == args.id), None)
    if job is None:
        print(json.dumps({"error": "Unknown fixture job"}))
        raise SystemExit(2)
    time.sleep(0.04)
    print(json.dumps(job, ensure_ascii=False))
'''


def prepare_fixture(home: Path) -> None:
    marker = home / ".musicdownloader-ui-fixture.json"
    if home.exists() and any(home.iterdir()) and (not marker.is_file() or json.loads(marker.read_text()) != SENTINEL):
        raise ValueError("Refusing to reuse a directory without the UI fixture sentinel")
    home.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(SENTINEL))
    (home / "fixture_backend.py").write_text(BACKEND)
    library = home / "測試音樂"
    library.mkdir(exist_ok=True)
    items = []
    for position in range(1, 31):
        piano = position % 2 == 0 or position == 13
        state = "downloaded" if position <= 10 else "failed" if position == 11 else "skipped" if position == 12 else "running" if position == 13 else "pending"
        items.append({"position": position, "video_id": f"TEST{position:07d}", "state": state,
                      "title": f"{'鋼琴 演奏' if piano else '中文 歌曲'} {position:02d} — 長標題與中文空白測試",
                      "category": "鋼琴" if piano else "華語", "reason": "影片標題含鋼琴相關字樣" if piano else "手動分配：第 1–30 首",
                      "path": "", "error": "測試網路失敗，這是隔離資料" if state == "failed" else ""})
    job_a = {"id": "fixture-running", "state": "running", "mode": "playlist", "category": "華語", "playlist_limit": 30,
             "url": "https://www.youtube.com/playlist?list=PLTEST123456", "created": 1794700800,
             "items": items, "total": 30, "completed_items": 12, "overall_percent": 40,
             "downloaded": 10, "skipped": 1, "failed": 1, "phase": "downloading", "phase_text": "下載音訊",
             "current_title": items[12]["title"], "current_position": 13, "track_percent": 37.2,
             "speed_text": "1.25MiB/s", "eta_text": "00:12", "library": str(library), "cancel_requested": 0}
    job_b_items = [{"position": index, "video_id": f"ALT{index:08d}", "title": f"另一份清單 歌曲 {index}",
                   "state": "failed" if index in (2, 5) else "downloaded", "category": "英文", "reason": "預設分類", "path": "",
                   "error": "測試私人影片" if index in (2, 5) else ""} for index in range(1, 7)]
    job_b = {**job_a, "id": "fixture-failed", "state": "partial", "category": "英文", "playlist_limit": 6,
             "items": job_b_items, "total": 6, "completed_items": 6, "overall_percent": 100,
             "downloaded": 4, "skipped": 0, "failed": 2, "phase": "partial", "phase_text": "部分完成",
             "current_title": "", "track_percent": None, "speed_text": "", "eta_text": ""}
    job_legacy = {**job_b, "id": "fixture-legacy-mix", "state": "failed", "category": "鋼琴", "playlist_limit": None,
                  "url": "https://www.youtube.com/playlist?list=RDAAAAAAAAAAA", "items": [], "total": None,
                  "completed_items": 0, "overall_percent": None, "downloaded": 0, "skipped": 0, "failed": 0,
                  "phase": "failed", "phase_text": "下載失敗", "error": "舊版 Mix 任務，請確認首數後重試"}
    (home / "fixture.json").write_text(json.dumps({"jobs": [job_a, job_b, job_legacy]}, ensure_ascii=False, indent=2))
    (home / "backend-calls.jsonl").write_text("")


def run_case(binary: Path, home: Path, name: str, mode: str, request=None, extra=None, expected=None) -> dict:
    result_path = home / f"result-{name}.json"
    screenshot = home / f"exercise-{name}.png"
    result_path.unlink(missing_ok=True)
    command = [str(binary), mode, "--home", str(home), "--python", sys.executable,
               "--engine", str(home / "fixture_backend.py"), "--exercise-ui",
               "--exercise-result", str(result_path), "--exercise-screenshot", str(screenshot)]
    command += extra or []
    started = time.monotonic()
    process = subprocess.run(command, input=json.dumps(request, ensure_ascii=False) if request is not None else None,
                             text=True, capture_output=True, timeout=45,
                             env={**os.environ, "MUSIC_DOWNLOADER_UI_EXERCISE": "1"})
    if process.returncode:
        raise AssertionError(f"{name}: helper exit {process.returncode}: {process.stdout} {process.stderr}")
    result = json.loads(result_path.read_text())
    if not result.get("ok") or not result.get("events") or any(not event.get("passed") for event in result["events"]):
        raise AssertionError(f"{name}: failed AppKit assertions: {result}")
    if not screenshot.is_file():
        raise AssertionError(f"{name}: no own-view screenshot")
    if expected is not None:
        responses = [json.loads(line) for line in process.stdout.splitlines() if line.startswith("{")]
        if not responses or any(responses[-1].get(key) != value for key, value in expected.items()):
            raise AssertionError(f"{name}: unexpected dialog result: {process.stdout}")
    return {"case": name, "seconds": round(time.monotonic() - started, 3), "result": result,
            "screenshot": str(screenshot), "stdout": process.stdout, "stderr": process.stderr}


def check_guards(binary: Path, home: Path) -> list[dict]:
    invalid = home.parent / "missing-sentinel" / "fixture-home"
    invalid.mkdir(parents=True, exist_ok=True)
    (invalid / "fixture_backend.py").write_text(BACKEND)
    checks = []
    for name, root, enabled in [("missing_environment_flag", home, False), ("missing_fixture_sentinel", invalid, True)]:
        environment = dict(os.environ)
        environment.pop("MUSIC_DOWNLOADER_UI_EXERCISE", None)
        if enabled:
            environment["MUSIC_DOWNLOADER_UI_EXERCISE"] = "1"
        process = subprocess.run([str(binary), "dialog", "--home", str(root), "--python", sys.executable,
                                  "--engine", str(root / "fixture_backend.py"), "--exercise-ui",
                                  "--exercise-result", str(root / f"guard-{name}.json"),
                                  "--exercise-screenshot", str(root / f"guard-{name}.png")],
                                 input=json.dumps({"kind": "message", "prompt": "Guard rejection test"}),
                                 text=True, capture_output=True, timeout=10, env=environment)
        if process.returncode == 0:
            raise AssertionError(f"Unsafe exercise guard accepted {name}")
        checks.append({"name": name, "passed": True, "exit_code": process.returncode})
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path.cwd() / "work/ui_exercise")
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    output = args.output.resolve()
    if "work" not in output.parts:
        raise ValueError("UI exercise output must be inside a work directory")
    production = (Path.home() / "Library/Application Support/MusicDownloader").resolve()
    if output == production or production in output.parents:
        raise ValueError("Refusing to exercise the production installation")
    binary = args.binary.resolve()
    if not binary.is_file():
        raise ValueError("Build the AppKit helper first")
    home = output / "fixture-home"
    prepare_fixture(home)
    guards = check_guards(binary, home)
    cases = []
    text = "https://youtu.be/AAAAAAAAAAA?備註=中文 空白"
    cases.append(run_case(binary, home, "ask", "dialog", {"kind": "ask", "title": "UI 操作測試", "prompt": "輸入網址（隔離測試）", "default": "old value"},
                          ["--exercise-value", text], {"value": text, "cancelled": False}))
    cases.append(run_case(binary, home, "choose", "dialog", {"kind": "choose", "title": "UI 操作測試", "prompt": "選擇分類", "choices": ["日文", "華語", "鋼琴"]},
                          ["--exercise-choice", "2"], {"value": "鋼琴", "cancelled": False}))
    cases.append(run_case(binary, home, "cancel", "dialog", {"kind": "ask", "title": "UI 操作測試", "prompt": "取消不建立任務"},
                          ["--exercise-cancel"], {"cancelled": True}))
    cases.append(run_case(binary, home, "message", "dialog", {"kind": "message", "title": "UI 操作測試", "prompt": "完整訊息可閱讀與放大"},
                          expected={"value": "", "cancelled": False}))
    source = args.source_dir.resolve()
    sys.path.insert(0, str(source))
    from frontend import download_summary
    summary = download_summary("playlist", "https://music.youtube.com/playlist?list=PLTEST123456", "日文", 30,
                               [{"start": 1, "end": 10, "category": "華語"}, {"start": 11, "end": 20, "category": "英文"}], True)
    cases.append(run_case(binary, home, "review-summary", "dialog",
                          {"kind": "choose", "title": "確認下載設定", "prompt": summary,
                           "choices": ["開始下載", "修改下載首數", "修改預設分類", "重新設定分類方式／序號分配", "更換網址"]},
                          ["--exercise-choice", "2"], {"value": "修改預設分類", "cancelled": False}))
    cases.append(run_case(binary, home, "progress", "progress", extra=["--job", "fixture-running"]))
    cases.append(run_case(binary, home, "legacy-mix-retry", "progress", extra=["--job", "fixture-legacy-mix", "--exercise-legacy-retry"]))
    calls = [json.loads(line) for line in (home / "backend-calls.jsonl").read_text().splitlines()]
    mutations = [call for call in calls if call["command"] not in {"jobs", "status"}]
    if not calls or len(mutations) != 1 or mutations[0]["command"] != "retry" or mutations[0]["id"] != "fixture-legacy-mix" or mutations[0]["playlist_limit"] != 25:
        raise AssertionError("Unexpected fixture mutation; only one legacy Mix retry of 25 is permitted")
    report = {"ok": True, "method": "real AppKit controls driven in-process; not external mouse/keyboard E2E",
              "fixture_home": str(home), "cases": cases, "backend_calls": calls,
              "guard_checks": guards,
              "production_engine_used": False, "music_downloads_started": 0, "fake_retry_requests": len(mutations),
              "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "swift_source_sha256": hashlib.sha256((source / "native_ui.swift").read_bytes()).hexdigest()}
    output.mkdir(exist_ok=True)
    (output / "exercise-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"ok": True, "cases": len(cases), "events": sum(len(case["result"]["events"]) for case in cases),
                      "report": str(output / "exercise-report.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
