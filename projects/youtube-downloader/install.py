#!/usr/bin/env python3
"""Install MusicDownloader for the current macOS user; no sudo or pip needed."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

LABEL = "com.wyw.musicdownloader.worker"
SUPPORT = Path.home() / "Library/Application Support/MusicDownloader"
SOURCE = Path(__file__).resolve().parent
TOOL_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def command(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment["PATH"] = TOOL_PATH
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    return subprocess.run(arguments, text=True, capture_output=True, check=check, env=environment)


def locate(name: str) -> str | None:
    return shutil.which(name, path=TOOL_PATH)


def atomic_write(path: Path, contents: bytes, mode: int = 0o600) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".install-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.chmod(mode)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def active_jobs() -> bool:
    database = SUPPORT / "library.sqlite3"
    if not database.exists():
        return False
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=10) as connection:
        return bool(connection.execute("SELECT count(*) FROM jobs WHERE state IN ('queued', 'running')").fetchone()[0])


def health() -> dict:
    result = command(["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], check=False)
    return {
        "service": LABEL,
        "loaded": result.returncode == 0,
        "running": result.returncode == 0 and "state = running" in result.stdout,
        "launcher": str(SUPPORT / "launcher.sh"),
        "installed": (SUPPORT / "app/music_downloader.py").exists(),
    }


def validate_platform() -> None:
    if sys.platform != "darwin":
        raise RuntimeError("此安裝程式僅適用 macOS。")
    if sys.version_info < (3, 10):
        raise RuntimeError("需要 Python 3.10 以上版本，請使用 Homebrew Python 執行安裝。")


def validate_sources(names: tuple[str, ...]) -> None:
    for name in names:
        path = SOURCE / name
        if not path.is_file():
            raise RuntimeError(f"缺少必要檔案：{name}，請使用完整專案資料夾。")
        if path.suffix == ".py":
            compile(path.read_text(encoding="utf-8"), str(path), "exec")


def install_native_helper(app: Path) -> Path:
    """Compile privately, then replace only our UI executable and bundle metadata."""
    validate_sources(("native_ui.swift",))
    if not Path("/usr/bin/xcrun").is_file():
        raise RuntimeError("找不到 Xcode Command Line Tools，無法建立原生視窗；請安裝 Apple 開發工具後重試。")
    compiler = command(["/usr/bin/xcrun", "--find", "swiftc"], check=False)
    if compiler.returncode or not compiler.stdout.strip():
        raise RuntimeError("需要 Xcode Command Line Tools 的 Swift 編譯器。請完成 Apple 開發工具安裝後重試；此程式不會自動開啟安裝視窗。")
    cache = SUPPORT / "build-cache"
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    modules = cache / "modules"
    modules.mkdir(exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="native-ui-", dir=cache) as build_directory:
        executable = Path(build_directory) / "MusicDownloaderUI"
        result = command(["/usr/bin/xcrun", "swiftc", "-O", "-framework", "AppKit",
                          "-module-cache-path", str(modules), str(SOURCE / "native_ui.swift"),
                          "-o", str(executable)], check=False)
        if result.returncode or not executable.is_file():
            detail = (result.stderr or result.stdout).strip()[-4000:]
            raise RuntimeError("原生視窗編譯失敗，原下載服務未重新啟動：\n" + detail)
        bundle = app / "NativeUI.app"
        contents = bundle / "Contents"
        binary_directory = contents / "MacOS"
        binary_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        metadata = {
            "CFBundleIdentifier": "com.wyw.musicdownloader.ui",
            "CFBundleName": "youtube downloader",
            "CFBundleDisplayName": "youtube downloader",
            "CFBundleExecutable": "MusicDownloaderUI",
            "CFBundlePackageType": "APPL",
            "CFBundleVersion": "1",
            "CFBundleShortVersionString": "1.0",
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",
        }
        atomic_write(contents / "Info.plist", plistlib.dumps(metadata), 0o600)
        # Replacing an executable leaves an already open window/process intact.
        atomic_write(binary_directory / "MusicDownloaderUI", executable.read_bytes(), 0o700)
        atomic_write(app / "native_ui.swift", (SOURCE / "native_ui.swift").read_bytes(), 0o600)
    return bundle


def install_ui_only() -> dict:
    """Deploy the UI without changing the worker, queue, settings or launchd."""
    validate_platform()
    validate_sources(("frontend.py", "progress_status.py", "native_ui.swift"))
    app = SUPPORT / "app"
    if not (app / "music_downloader.py").is_file() or not (SUPPORT / "launcher.sh").is_file():
        raise RuntimeError("尚未完成下載工具安裝，請先在沒有下載任務時執行完整安裝。")
    bundle = install_native_helper(app)
    # Publish the dependency before the frontend that invokes it.
    for name in ("progress_status.py", "frontend.py", "install.py"):
        atomic_write(app / name, (SOURCE / name).read_bytes(), 0o600)
    return {
        "mode": "ui-only",
        "installed": True,
        "native_ui": str(bundle),
        "updated_files": ["frontend.py", "progress_status.py", "install.py", "native_ui.swift", "NativeUI.app"],
        "worker_untouched": True,
        "settings_untouched": True,
    }


def install() -> dict:
    validate_platform()
    validate_sources(("music_downloader.py", "frontend.py", "progress_status.py", "native_ui.swift"))
    brew = locate("brew")
    if not brew:
        raise RuntimeError("尚未安裝 Homebrew；請先依 https://brew.sh/ 官方指示安裝，再重新執行此程式。")
    required = {"yt-dlp": "yt-dlp", "ffmpeg": "ffmpeg", "ffprobe": "ffmpeg", "deno": "deno"}
    missing = sorted({formula for binary, formula in required.items() if not locate(binary)})
    if missing:
        print("正在安裝缺少的工具：" + "、".join(missing), flush=True)
        result = command([brew, "install", *missing], check=False)
        if result.returncode:
            raise RuntimeError("Homebrew 安裝失敗：\n" + result.stderr[-4000:])
    tools = {name: locate(name) for name in required}
    if not all(tools.values()):
        raise RuntimeError("部分工具仍無法執行，請檢查 Homebrew 安裝結果。")
    if active_jobs() and health()["running"]:
        raise RuntimeError("目前仍有下載任務，請等完成或在「youtube downloader」取消任務後再安裝，避免中斷下載。")

    SUPPORT.mkdir(parents=True, exist_ok=True, mode=0o700)
    SUPPORT.chmod(0o700)
    app = SUPPORT / "app"
    app.mkdir(exist_ok=True, mode=0o700)
    for folder in ("logs", "staging", "reports"):
        (SUPPORT / folder).mkdir(exist_ok=True, mode=0o700)
    install_native_helper(app)
    desktop = Path(command(["/usr/bin/osascript", "-e", "POSIX path of (path to desktop folder)"]).stdout.strip())
    if not desktop.is_absolute() or not desktop.is_dir():
        raise RuntimeError("macOS 未能解析桌面位置，請確認桌面或 iCloud 桌面已可存取。")
    library = desktop / "音樂"
    library.mkdir(exist_ok=True)
    config_path = SUPPORT / "config.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    config.update({"library": str(library), "ytdlp": tools["yt-dlp"], "ffmpeg": tools["ffmpeg"],
                   "ffprobe": tools["ffprobe"], "deno": tools["deno"],
                   "python": str(Path(sys.executable).absolute()), "version": 1})
    atomic_write(config_path, (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode())

    # Copy only our packaged program files. Personal music and database are never touched.
    for path in SOURCE.iterdir():
        if path.is_file() and path.suffix in {".py", ".sh", ".md", ".command", ".swift"}:
            atomic_write(app / path.name, path.read_bytes(), 0o700 if path.suffix in {".sh", ".command"} else 0o600)
    python = str(Path(sys.executable).absolute())
    launcher = "\n".join([
        "#!/bin/bash", "set -eu", "unset PYTHONHOME PYTHONPATH",
        "export PATH=" + shlex.quote(TOOL_PATH),
        "if [[ ${1:-} == ui ]]; then", "  shift",
        "  exec " + shlex.quote(python) + " " + shlex.quote(str(app / "frontend.py")) + ' "$@"',
        "fi",
        "exec " + shlex.quote(python) + " " + shlex.quote(str(app / "music_downloader.py")) + ' "$@"', "",
    ])
    atomic_write(SUPPORT / "launcher.sh", launcher.encode(), 0o700)
    atomic_write(SUPPORT / "runtime.json", (json.dumps({"python": python, "app": str(app)}, indent=2) + "\n").encode())
    agents = Path.home() / "Library/LaunchAgents"
    agents.mkdir(exist_ok=True)
    plist_path = agents / (LABEL + ".plist")
    plist = {
        "Label": LABEL,
        "ProgramArguments": [python, str(app / "music_downloader.py"), "worker"],
        "WorkingDirectory": str(SUPPORT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "EnvironmentVariables": {"PATH": TOOL_PATH, "PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1"},
        "StandardOutPath": str(SUPPORT / "logs/worker.stdout.log"),
        "StandardErrorPath": str(SUPPORT / "logs/worker.stderr.log"),
    }
    atomic_write(plist_path, plistlib.dumps(plist), 0o600)
    target = f"gui/{os.getuid()}/{LABEL}"
    loaded = command(["/bin/launchctl", "print", target], check=False).returncode == 0
    if loaded:
        command(["/bin/launchctl", "bootout", target])
    command(["/bin/launchctl", "enable", target])
    result = command(["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)], check=False)
    # bootout may return before launchd has finished tearing down its service.
    # Retry without escalating permissions; never register a second worker.
    for _ in range(20):
        if result.returncode == 0:
            break
        time.sleep(0.25)
        if command(["/bin/launchctl", "print", target], check=False).returncode == 0:
            continue
        result = command(["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)], check=False)
    if result.returncode:
        raise RuntimeError("程式已安裝，但無法啟動背景服務：\n" + result.stderr.strip())
    command(["/bin/launchctl", "kickstart", target])
    result = health()
    for _ in range(20):
        if result["running"]:
            break
        time.sleep(0.1)
        result = health()
    if not result["running"]:
        raise RuntimeError("背景服務已登錄但尚未成功啟動，請查看 logs/worker.stderr.log。")
    result.update({"library": str(library), "python": python, "tools": tools})
    atomic_write(SUPPORT / "installation.json", (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="安裝或檢查 youtube downloader")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只檢查既有安裝與背景服務")
    mode.add_argument("--ui-only", action="store_true", help="只更新原生視窗，不中斷進行中的下載")
    args = parser.parse_args()
    try:
        result = health() if args.check else install_ui_only() if args.ui_only else install()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError, sqlite3.Error) as error:
        print("安裝未完成：" + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
