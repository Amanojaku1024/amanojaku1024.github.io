"""Real yt-dlp + ffmpeg test using self-generated audio over localhost only."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@unittest.skipUnless(all(shutil.which(x) for x in ["yt-dlp", "ffmpeg", "ffprobe"]), "Requires installed media tools")
class RealTranscodeTest(unittest.TestCase):
    def test_generated_audio_metadata_cover_and_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="musicdownloader-media-") as directory:
            root = Path(directory)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
                            "-c:a", "libopus", str(root / "source.webm")], check=True, capture_output=True)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64",
                            "-frames:v", "1", "-threads", "1", str(root / "cover.jpg")], check=True, capture_output=True)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = "http://127.0.0.1:" + str(server.server_port)
                info = {"id": "TESTMEDIA01", "title": "中文測試 音樂", "artist": "測試歌手", "ext": "webm",
                        "url": base + "/source.webm", "webpage_url": base + "/source.webm",
                        "extractor": "generic", "extractor_key": "Generic", "format_id": "test",
                        "thumbnail": base + "/cover.jpg", "thumbnails": [{"url": base + "/cover.jpg", "id": "0"}],
                        "vcodec": "none", "acodec": "opus", "protocol": "http"}
                (root / "info.json").write_text(json.dumps(info, ensure_ascii=False))
                output = root / "中文分類"
                result = subprocess.run(["yt-dlp", "--ignore-config", "--no-plugin-dirs", "--no-exec",
                                         "--load-info-json", str(root / "info.json"), "--no-playlist", "-f", "bestaudio/best",
                                         "-x", "--audio-format", "mp3", "--audio-quality", "0", "--embed-metadata",
                                         "--embed-thumbnail", "--convert-thumbnails", "jpg", "--no-keep-video",
                                         "-o", str(output / "%(title)s.%(ext)s")], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                target = output / "中文測試 音樂.mp3"
                self.assertTrue(target.is_file())
                probe = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(target)],
                                       capture_output=True, text=True, check=True)
                details = json.loads(probe.stdout)
                self.assertEqual(details["format"]["tags"]["title"], "中文測試 音樂")
                self.assertEqual(details["format"]["tags"]["artist"], "測試歌手")
                self.assertTrue(any(s.get("codec_name") == "mp3" for s in details["streams"]))
                self.assertTrue(any(s.get("disposition", {}).get("attached_pic") == 1 for s in details["streams"]))
                self.assertFalse(list(output.glob("*.webm")))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
