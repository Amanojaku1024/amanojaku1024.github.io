"""Shortcuts must not need Desktop access to select categories or queue/retry."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from music_downloader import Engine


class DesktopBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="music-ui-boundary-")
        self.base = Path(self.temp.name)
        self.library = self.base / "桌面" / "音樂"
        self.engine = Engine(self.base / "support", self.library)

    def tearDown(self):
        self.engine.close()
        for handler in self.engine.log.handlers[:]:
            handler.close()
            self.engine.log.removeHandler(handler)
        self.temp.cleanup()

    def test_category_selection_reads_only_private_cache(self):
        (self.engine.home / "categories.json").write_text(json.dumps(["鋼琴", "自訂分類", "../unsafe"]))
        with mock.patch.object(Path, "iterdir", side_effect=PermissionError("Desktop denied")):
            result = self.engine.categories()
        self.assertIn("鋼琴", result)
        self.assertIn("自訂分類", result)
        self.assertNotIn("../unsafe", result)
        self.assertFalse(self.library.exists())

    def test_missing_cache_uses_asset_paths_without_stat(self):
        path = self.library / "日文原聲帶" / "song.mp3"
        with self.engine.db:
            self.engine.db.execute("INSERT INTO assets VALUES(?,?,?,?)", (str(path), "sha", 1, 1))
        with mock.patch.object(Path, "is_file", side_effect=PermissionError("Desktop denied")), \
             mock.patch.object(Path, "iterdir", side_effect=PermissionError("Desktop denied")):
            result = self.engine.categories()
        self.assertIn("日文原聲帶", result)

    def test_enqueue_does_not_create_music_directory(self):
        with mock.patch.object(self.engine, "category_path", side_effect=AssertionError("UI touched Desktop")):
            job = self.engine.enqueue("single", "https://youtu.be/AAAAAAAAAAA", "鋼琴")
        self.assertEqual(job["state"], "queued")
        self.assertFalse(self.library.exists())

    def test_retry_does_not_stat_saved_music(self):
        job = self.engine.enqueue("single", "https://youtu.be/AAAAAAAAAAA", "鋼琴")
        with self.engine.db:
            self.engine.db.execute("UPDATE jobs SET state='partial',enumerated=1 WHERE id=?", (job["id"],))
            self.engine.db.execute("INSERT INTO items(job_id,position,video_id,state,path) VALUES(?,1,?,'downloaded',?)",
                                   (job["id"], "AAAAAAAAAAA", str(self.library / "鋼琴" / "song.mp3")))
        with mock.patch.object(Path, "is_file", side_effect=PermissionError("Desktop denied")):
            result = self.engine.retry(job["id"])
        self.assertEqual(result["state"], "queued")

    def test_worker_refresh_includes_empty_folders_and_excludes_links(self):
        (self.library / "空白分類").mkdir(parents=True)
        (self.library / "連結分類").symlink_to(self.library / "空白分類")
        self.engine.refresh_categories()
        self.assertIn("空白分類", self.engine.categories())
        self.assertNotIn("連結分類", self.engine.categories())
