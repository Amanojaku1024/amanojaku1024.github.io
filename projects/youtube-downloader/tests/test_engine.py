"""Isolated engine integration tests. Network is replaced by a process double."""
import concurrent.futures
import errno
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from music_downloader import Engine, UserError, is_piano_title, normalize_url, sha256, validate_options

os.environ["MUSIC_DOWNLOADER_NO_NOTIFY"] = "1"
SINGLE = "https://music.youtube.com/watch?v=AAAAAAAAAAA&list=PLTEST123456"
PLAYLIST = "https://music.youtube.com/playlist?list=PLTEST123456"
MIX = "https://music.youtube.com/watch?v=AAAAAAAAAAA&list=RDAAAAAAAAAAA&start_radio=1"
MIX_CANONICAL = "https://www.youtube.com/watch?v=AAAAAAAAAAA&list=RDAAAAAAAAAAA"


class MixURLRegressionTest(unittest.TestCase):
    def test_mix_watch_url_keeps_video_and_list(self):
        self.assertEqual(normalize_url(MIX, "playlist"), MIX_CANONICAL)

    def test_broken_mix_playlist_url_recovers_exact_seed(self):
        self.assertEqual(normalize_url("https://www.youtube.com/playlist?list=RDAAAAAAAAAAA", "playlist"),
                         MIX_CANONICAL)

    def test_rdmm_keeps_explicit_video_seed(self):
        self.assertEqual(normalize_url("https://www.youtube.com/watch?v=AAAAAAAAAAA&list=RDMM", "playlist"),
                         "https://www.youtube.com/watch?v=AAAAAAAAAAA&list=RDMM")

    def test_rdmm_without_seed_is_rejected(self):
        with self.assertRaises(UserError):
            normalize_url("https://www.youtube.com/playlist?list=RDMM", "playlist")

    def test_non_video_radio_id_does_not_invent_a_seed(self):
        with self.assertRaises(UserError):
            normalize_url("https://www.youtube.com/playlist?list=RDEM123456789012345678901234", "playlist")

    def test_single_with_mix_still_downloads_only_single_video(self):
        self.assertEqual(normalize_url(MIX, "single"), "https://www.youtube.com/watch?v=AAAAAAAAAAA")

    def test_normal_playlist_url_unchanged(self):
        self.assertEqual(normalize_url("https://music.youtube.com/watch?v=AAAAAAAAAAA&list=PLTEST123456", "playlist"),
                         "https://www.youtube.com/playlist?list=PLTEST123456")


class ClassificationRulesTest(unittest.TestCase):
    def test_piano_title_keywords_in_several_languages(self):
        for title in ["鋼琴演奏 夜曲", "钢琴独奏", "Song - Piano Cover", "pIaNo ver.",
                      "ピアノ演奏", "피아노 커버", "ＰＩＡＮＯ cover", "Pianoforte Sonata", "Klavier Solo"]:
            with self.subTest(title=title):
                self.assertTrue(is_piano_title(title))

    def test_piano_negative_phrases_and_unrelated_words(self):
        for title in ["No Piano Version", "without piano accompaniment", "Non-Piano Remix", "Piano-free",
                      "非鋼琴演奏", "无钢琴", "ピアノなし", "피아노 없음", "Pianola Cover", "Spianopolis", "Guitar Solo"]:
            with self.subTest(title=title):
                self.assertFalse(is_piano_title(title))

    def test_route_input_validation_and_safe_categories(self):
        invalid = ["not a list", [None], [{"start": 0, "end": 1, "category": "日文"}],
                   [{"start": 2, "end": 1, "category": "日文"}],
                   [{"start": True, "end": 1, "category": "日文"}],
                   [{"start": 1, "end": 1.5, "category": "日文"}],
                   [{"start": 1, "end": 4, "category": "日文"}],
                   [{"start": 1, "end": 1, "category": "../escape"}],
                   [{"start": 1, "end": 1, "category": "foo/bar"}],
                   [{"start": 1, "end": 1, "category": None}],
                   [{"start": 1, "end": 2, "category": "日文"}, {"start": 2, "end": 3, "category": "華語"}],
                   [{"start": 1, "end": 1, "category": "日文"}] * 101]
        for routes in invalid:
            with self.subTest(routes=routes), self.assertRaises(UserError):
                validate_options("playlist", 3, routes=routes)

    def test_route_adjacent_ranges_and_unicode_normalization(self):
        options = validate_options("playlist", 3, routes=[{"start": 3, "end": 3, "category": "  Cafe\u0301  "},
                                                       {"start": 1, "end": 2, "category": "日文"}])
        self.assertEqual(options["routes"], [{"start": 1, "end": 2, "category": "日文"},
                                             {"start": 3, "end": 3, "category": "Café"}])

    def test_auto_piano_requires_boolean_and_safe_destination(self):
        for value in ["false", "true", 0, 1, None]:
            with self.subTest(value=value), self.assertRaises(UserError):
                validate_options("playlist", None, auto_piano=value)
        with self.assertRaises(UserError):
            validate_options("playlist", None, auto_piano=True, piano_category="../outside")
        with self.assertRaises(UserError):
            validate_options("single", None, routes=[{"start": 1, "end": 1, "category": "日文"}])


def enqueue_process(spec):
    home, library, fake, category = spec
    engine = Engine(Path(home), Path(library), fake, shutil.which("ffmpeg"), shutil.which("ffprobe"))
    try:
        return engine.enqueue("single", SINGLE, category)["id"]
    finally:
        engine.close()


def process_worker(spec):
    home, library, fake = spec
    engine = Engine(Path(home), Path(library), fake, shutil.which("ffmpeg"), shutil.which("ffprobe"))
    try:
        return engine.process_next()
    finally:
        engine.close()


@unittest.skipUnless(all(shutil.which(x) for x in ["ffmpeg", "ffprobe"]), "Requires installed media tools")
class EngineIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_tmp = tempfile.TemporaryDirectory(prefix="musicdownloader-fixtures-")
        cls.media = Path(cls.media_tmp.name)
        for name, frequency in [("a.mp3", 440), ("b.mp3", 880), ("c.mp3", 1320)]:
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration=0.3",
                            "-q:a", "0", str(cls.media / name)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.media_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="musicdownloader-engine-")
        self.root = Path(self.tmp.name)
        self.home = self.root / "Application Support" / "下載引擎"
        self.library = self.root / "桌面" / "音樂"
        self.fake_dir = self.root / "fake tools"
        self.fake_dir.mkdir()
        self.fake = self.fake_dir / "yt-dlp"
        shutil.copyfile(Path(__file__).with_name("fake_ytdlp.py"), self.fake)
        self.fake.chmod(0o700)
        for name in ["a.mp3", "b.mp3", "c.mp3"]:
            shutil.copyfile(self.media / name, self.fake_dir / name)
        self.fixture = {"playlist": ["AAAAAAAAAAA", "BBBBBBBBBBB"], "videos": {
            "AAAAAAAAAAA": {"title": "天ノ弱 中文星", "fixture": "a.mp3"},
            "BBBBBBBBBBB": {"title": "第二首 歌曲", "fixture": "b.mp3"},
            "CCCCCCCCCCC": {"title": "相同內容不同影片", "fixture": "a.mp3"},
            "DDDDDDDDDDD": {"error": "Private video"},
        }}
        self.save_fixture()
        self.engine = Engine(self.home, self.library, str(self.fake), shutil.which("ffmpeg"), shutil.which("ffprobe"))

    def tearDown(self):
        self.engine.close()
        for handler in self.engine.log.handlers[:]:
            handler.close()
            self.engine.log.removeHandler(handler)
        self.tmp.cleanup()

    def save_fixture(self):
        (self.fake_dir / "fixture.json").write_text(json.dumps(self.fixture, ensure_ascii=False))

    def calls(self):
        file = self.fake_dir / "calls.jsonl"
        return [json.loads(line) for line in file.read_text().splitlines()] if file.exists() else []

    def downloads(self):
        return [call for call in self.calls() if "--output" in call]

    def run_job(self, mode="single", url=SINGLE, category="日文", **options):
        job = self.engine.enqueue(mode, url, category, **options)
        self.assertTrue(self.engine.process_next())
        return self.engine.status(job["id"])

    def insert_legacy_mix_job(self):
        job_id = "legacy-mix"
        now = time.time()
        self.engine.category_path("日文")
        with self.engine.db:
            self.engine.db.execute("INSERT INTO jobs(id,fingerprint,mode,url,category,state,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                                   (job_id, "old-broken-mix-fingerprint", "playlist",
                                    "https://www.youtube.com/playlist?list=RDAAAAAAAAAAA", "日文", "failed", now, now))
        return job_id

    def test_mix_listing_is_bounded_in_argv_and_persisted_items(self):
        # Deliberately make the process double ignore --playlist-end. The engine
        # must also enforce the confirmed limit on the returned entries.
        self.fixture["playlist"] = ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"]
        self.save_fixture()
        job = self.run_job("playlist", MIX, playlist_limit=1)
        self.assertEqual(job["url"], MIX_CANONICAL)
        self.assertEqual(job["playlist_limit"], 1)
        self.assertEqual((job["state"], job["total"], job["downloaded"]), ("completed", 1, 1))
        listing = next(call for call in self.calls() if "--flat-playlist" in call)
        self.assertEqual(listing[listing.index("--playlist-end") + 1], "1")
        self.assertEqual(listing[-1], MIX_CANONICAL)
        self.assertEqual(len(self.downloads()), 1)

    def test_mix_requires_explicit_valid_integer_limit(self):
        for limit in [None, 0, -1, 501, True, False, 1.5, "50", "invalid"]:
            with self.subTest(limit=limit), self.assertRaises(UserError):
                self.engine.enqueue("playlist", MIX, "日文", playlist_limit=limit)
        self.assertEqual(self.engine.jobs(), [])
        self.assertEqual(self.calls(), [])

    def test_mix_limit_is_part_of_active_job_identity(self):
        first = self.engine.enqueue("playlist", MIX, "日文", playlist_limit=1)
        other = self.engine.enqueue("playlist", MIX, "日文", playlist_limit=2)
        repeated = self.engine.enqueue("playlist", MIX, "日文", playlist_limit=1)
        self.assertNotEqual(first["id"], other["id"])
        self.assertEqual(first["id"], repeated["id"])

    def test_normal_playlist_is_not_silently_bounded(self):
        job = self.run_job("playlist", PLAYLIST)
        listing = next(call for call in self.calls() if "--flat-playlist" in call)
        self.assertNotIn("--playlist-end", listing)
        self.assertIsNone(job["playlist_limit"])
        self.assertEqual(job["total"], 2)
        limited = self.engine.enqueue("playlist", PLAYLIST, "日文", playlist_limit=50)
        self.assertEqual(limited["playlist_limit"], 50)

    def test_finite_playlist_limit_is_bounded_in_argv_and_items(self):
        self.fixture["playlist"] = ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"]
        self.save_fixture()
        job = self.run_job("playlist", PLAYLIST, playlist_limit=1)
        self.assertEqual((job["total"], job["downloaded"]), (1, 1))
        listing = next(call for call in self.calls() if "--flat-playlist" in call)
        self.assertEqual(listing[listing.index("--playlist-end") + 1], "1")
        self.assertEqual(len(self.downloads()), 1)

    def test_finite_playlist_limit_validation(self):
        for value in [0, -1, 10001, True, False, "50", 1.5]:
            with self.subTest(value=value), self.assertRaises(UserError):
                self.engine.enqueue("playlist", PLAYLIST, "日文", playlist_limit=value)
        self.assertEqual(self.engine.jobs(), [])
        self.assertEqual(self.engine.enqueue("playlist", PLAYLIST, "日文", playlist_limit=10000)["playlist_limit"], 10000)

    def test_routes_use_inclusive_original_positions_and_override_piano(self):
        self.fixture["playlist"] = ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"]
        self.fixture["videos"]["AAAAAAAAAAA"]["title"] = "Piano Cover Alpha"
        self.fixture["videos"]["CCCCCCCCCCC"] = {"title": "第三首 ピアノ", "fixture": "c.mp3"}
        self.save_fixture()
        routes = [{"start": 1, "end": 2, "category": "華語"}]
        job = self.run_job("playlist", PLAYLIST, "英文", playlist_limit=3, routes=routes, auto_piano=True)
        self.assertEqual(job["downloaded"], 3)
        self.assertEqual([item["category"] for item in job["items"]], ["華語", "華語", "鋼琴"])
        self.assertEqual([Path(item["path"]).parent.name for item in job["items"]], ["華語", "華語", "鋼琴"])
        self.assertIn("手動", job["items"][0]["reason"])
        self.assertIn("影片標題", job["items"][2]["reason"])
        report = Path(job["report"]).read_text()
        self.assertIn("第 1–2 首", report)
        self.assertIn("分類：鋼琴", report)

    def test_failed_items_do_not_shift_route_positions(self):
        self.fixture["playlist"] = ["DDDDDDDDDDD", "AAAAAAAAAAA", "BBBBBBBBBBB"]
        self.save_fixture()
        job = self.run_job("playlist", PLAYLIST, "英文", routes=[{"start": 2, "end": 2, "category": "華語"}])
        self.assertEqual((job["downloaded"], job["failed"]), (2, 1))
        self.assertEqual([item["position"] for item in job["items"]], [1, 2, 3])
        self.assertEqual(job["items"][1]["category"], "華語")
        self.assertEqual(job["items"][2]["category"], "英文")

    def test_manual_routes_never_move_or_duplicate_existing_song(self):
        self.fixture["playlist"] = ["AAAAAAAAAAA", "AAAAAAAAAAA", "BBBBBBBBBBB"]
        self.save_fixture()
        routes = [{"start": 1, "end": 1, "category": "日文"},
                  {"start": 2, "end": 2, "category": "古典"}]
        job = self.run_job("playlist", PLAYLIST, "英文", routes=routes)
        self.assertEqual((job["downloaded"], job["skipped"]), (2, 1))
        self.assertEqual(job["items"][0]["path"], job["items"][1]["path"])
        self.assertEqual(job["items"][1]["category"], "日文")
        self.assertIn("未移動", job["items"][1]["reason"])
        self.assertFalse((self.library / "古典" / "天ノ弱 中文星.mp3").exists())
        self.assertEqual(len(self.downloads()), 2)

    def test_piano_detection_uses_actual_video_title_not_track_metadata(self):
        self.fixture["videos"]["AAAAAAAAAAA"].update({"listing_title": "Alpha", "title": "Piano Alpha", "track": "Alpha Track"})
        self.fixture["videos"]["BBBBBBBBBBB"].update({"title": "Guitar Beta", "track": "Piano Track"})
        self.save_fixture()
        job = self.run_job("playlist", PLAYLIST, "英文", auto_piano=True)
        self.assertEqual(job["downloaded"], 2)
        self.assertEqual(job["items"][0]["category"], "鋼琴")
        self.assertEqual(Path(job["items"][0]["path"]).name, "Alpha Track.mp3")
        self.assertEqual(job["items"][1]["category"], "英文")
        self.assertEqual(Path(job["items"][1]["path"]).name, "Piano Track.mp3")

    def test_custom_piano_category_and_disabled_automation(self):
        self.fixture["videos"]["AAAAAAAAAAA"]["title"] = "鋼琴獨奏"
        self.fixture["videos"]["BBBBBBBBBBB"]["title"] = "Piano Cover Beta"
        self.save_fixture()
        enabled = self.run_job(auto_piano=True, piano_category="鋼琴 演奏")
        disabled = self.run_job(url="https://youtu.be/BBBBBBBBBBB", auto_piano=False)
        self.assertEqual(enabled["items"][0]["category"], "鋼琴 演奏")
        self.assertEqual(disabled["items"][0]["category"], "日文")

    def test_classification_options_are_persisted_and_part_of_job_identity(self):
        route1 = {"start": 1, "end": 1, "category": "華語"}
        route2 = {"start": 2, "end": 2, "category": "英文"}
        first = self.engine.enqueue("playlist", PLAYLIST, "日文", 2, [route2, route1], True)
        same = self.engine.enqueue("playlist", PLAYLIST, "日文", 2, [route1, route2], True)
        different = self.engine.enqueue("playlist", PLAYLIST, "日文", 2, [route1, route2], False)
        self.assertEqual(first["id"], same["id"])
        self.assertNotEqual(first["id"], different["id"])
        self.engine.close()
        self.engine = Engine(self.home, self.library, str(self.fake), shutil.which("ffmpeg"), shutil.which("ffprobe"))
        saved = self.engine.status(first["id"])
        self.assertEqual(saved["routes"], [route1, route2])
        self.assertTrue(saved["auto_piano"])
        self.assertEqual(saved["piano_category"], "鋼琴")

    def test_retry_preserves_original_playlist_snapshot_and_routes(self):
        self.fixture["playlist"] = ["AAAAAAAAAAA", "DDDDDDDDDDD", "BBBBBBBBBBB"]
        self.fixture["videos"]["AAAAAAAAAAA"]["title"] = "Piano Alpha"
        self.save_fixture()
        routes = [{"start": 2, "end": 3, "category": "華語"}]
        first = self.run_job("playlist", PLAYLIST, "英文", playlist_limit=3, routes=routes, auto_piano=True)
        self.assertEqual((first["downloaded"], first["failed"]), (2, 1))
        self.fixture["playlist"] = ["CCCCCCCCCCC"]
        self.fixture["videos"]["DDDDDDDDDDD"] = {"title": "Piano Fixed", "fixture": "c.mp3"}
        self.save_fixture()
        self.engine.retry(first["id"])
        self.assertTrue(self.engine.process_next())
        final = self.engine.status(first["id"])
        self.assertEqual([item["video_id"] for item in final["items"]], ["AAAAAAAAAAA", "DDDDDDDDDDD", "BBBBBBBBBBB"])
        self.assertEqual(final["routes"], routes)
        self.assertTrue(final["auto_piano"])
        self.assertEqual((final["downloaded"], final["failed"]), (3, 0))
        self.assertEqual(final["items"][1]["category"], "華語")
        self.assertEqual(len([call for call in self.calls() if "--flat-playlist" in call]), 1)

    def test_deleted_auto_classified_song_can_return_without_cross_category_duplicate(self):
        self.fixture["videos"]["AAAAAAAAAAA"]["title"] = "Piano Alpha"
        self.save_fixture()
        first = self.run_job(auto_piano=True)
        old = Path(first["items"][0]["path"])
        old.unlink()
        self.engine.retry(first["id"])
        self.assertTrue(self.engine.process_next())
        restored = self.engine.status(first["id"])
        self.assertEqual(restored["items"][0]["category"], "鋼琴")
        self.assertTrue(old.is_file())
        other = self.run_job(category="古典", auto_piano=False)
        self.assertEqual((other["downloaded"], other["skipped"]), (0, 1))
        self.assertEqual(other["items"][0]["path"], str(old))
        self.assertEqual(other["items"][0]["category"], "鋼琴")
        self.assertEqual(len(list(self.library.rglob("*.mp3"))), 1)

    def test_single_song_rejects_playlist_limit(self):
        with self.assertRaises(UserError):
            self.engine.enqueue("single", SINGLE, "日文", playlist_limit=50)

    def test_legacy_failed_mix_requires_confirmation_before_retry(self):
        job_id = self.insert_legacy_mix_job()
        with self.assertRaises(UserError):
            self.engine.retry(job_id)
        unchanged = self.engine.status(job_id)
        self.assertEqual(unchanged["state"], "failed")
        self.assertIsNone(unchanged["playlist_limit"])
        self.assertEqual(self.calls(), [])
        repaired = self.engine.retry(job_id, playlist_limit=1)
        self.assertEqual((repaired["id"], repaired["state"], repaired["url"], repaired["playlist_limit"]),
                         (job_id, "queued", MIX_CANONICAL, 1))
        self.assertTrue(self.engine.process_next())
        self.assertEqual(self.engine.status(job_id)["total"], 1)

    def test_retry_keeps_confirmed_mix_range(self):
        job = self.run_job("playlist", MIX, playlist_limit=1)
        with self.assertRaises(UserError):
            self.engine.retry(job["id"], playlist_limit=2)
        self.assertEqual(self.engine.status(job["id"])["state"], "completed")
        retried = self.engine.retry(job["id"])
        self.assertEqual(retried["playlist_limit"], 1)

    def test_legacy_enumerated_mix_cannot_retry_beyond_new_limit(self):
        job_id = self.insert_legacy_mix_job()
        with self.engine.db:
            self.engine.db.execute("UPDATE jobs SET enumerated=1 WHERE id=?", (job_id,))
            self.engine.db.executemany("INSERT INTO items(job_id,position,video_id) VALUES(?,?,?)",
                                      [(job_id, 1, "AAAAAAAAAAA"), (job_id, 2, "BBBBBBBBBBB")])
        with self.assertRaises(UserError):
            self.engine.retry(job_id, playlist_limit=1)
        self.assertEqual(self.engine.status(job_id)["state"], "failed")
        self.assertEqual(self.calls(), [])

    def test_legacy_enumerated_mix_without_limit_cannot_start(self):
        job_id = self.insert_legacy_mix_job()
        with self.engine.db:
            self.engine.db.execute("UPDATE jobs SET state='queued',enumerated=1 WHERE id=?", (job_id,))
            self.engine.db.execute("INSERT INTO items(job_id,position,video_id) VALUES(?,?,?)", (job_id, 1, "AAAAAAAAAAA"))
        self.assertTrue(self.engine.process_next())
        status = self.engine.status(job_id)
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["downloaded"], 0)
        self.assertEqual(self.calls(), [])

    def test_old_database_gains_limit_column_without_losing_job(self):
        job_id = self.insert_legacy_mix_job()
        old_home = self.root / "legacy Application Support"
        old_home.mkdir()
        legacy = sqlite3.connect(old_home / "library.sqlite3")
        fields = [row for row in self.engine.db.execute("PRAGMA table_info(jobs)") if row["name"] not in {"playlist_limit", "options_json"}]
        declarations = []
        for field in fields:
            part = field["name"] + " " + field["type"]
            if field["pk"]:
                part += " PRIMARY KEY"
            if field["notnull"]:
                part += " NOT NULL"
            if field["dflt_value"] is not None:
                part += " DEFAULT " + field["dflt_value"]
            declarations.append(part)
        legacy.execute("CREATE TABLE jobs(" + ",".join(declarations) + ")")
        old_job = self.engine.status(job_id)
        names = [field["name"] for field in fields]
        legacy.execute("INSERT INTO jobs(" + ",".join(names) + ") VALUES(" + ",".join("?" for _ in names) + ")",
                       [old_job[name] for name in names])
        legacy.execute("CREATE TABLE items(job_id TEXT NOT NULL,position INTEGER NOT NULL,video_id TEXT,title TEXT NOT NULL DEFAULT '',"
                       "state TEXT NOT NULL DEFAULT 'pending',path TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',PRIMARY KEY(job_id,position))")
        legacy.execute("INSERT INTO items(job_id,position,video_id,state,error) VALUES(?,?,?,?,?)",
                       (job_id, 1, "AAAAAAAAAAA", "failed", "舊任務失敗"))
        legacy.commit()
        legacy.close()
        migrated = Engine(old_home, self.library, str(self.fake), shutil.which("ffmpeg"), shutil.which("ffprobe"))
        try:
            self.assertIsNone(migrated.status(job_id)["playlist_limit"])
            self.assertEqual(migrated.status(job_id)["state"], "failed")
            self.assertEqual(migrated.status(job_id)["options"], {})
            self.assertEqual(migrated.status(job_id)["routes"], [])
            self.assertEqual(migrated.status(job_id)["items"][0]["category"], "")
            self.assertEqual(migrated.status(job_id)["items"][0]["reason"], "")
            self.assertEqual(migrated.status(job_id)["items"][0]["error"], "舊任務失敗")
            with self.assertRaises(UserError):
                migrated.retry(job_id)
            self.assertEqual(migrated.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            migrated.close()
            for handler in migrated.log.handlers[:]:
                handler.close()
                migrated.log.removeHandler(handler)

    def test_single_category_chinese_path_and_no_playlist(self):
        job = self.run_job(category="日文 原聲帶")
        self.assertEqual((job["state"], job["downloaded"], job["failed"]), ("completed", 1, 0))
        target = self.library / "日文 原聲帶" / "天ノ弱 中文星.mp3"
        self.assertTrue(target.is_file())
        args = self.downloads()[0]
        self.assertIn("--no-playlist", args)
        self.assertEqual(args[-1], "https://www.youtube.com/watch?v=AAAAAAAAAAA")
        self.assertEqual(list(self.library.rglob("*.mp3")), [target])

    def test_playlist_repeat_skips_before_download(self):
        first = self.run_job("playlist", PLAYLIST)
        second = self.run_job("playlist", PLAYLIST)
        self.assertEqual((first["downloaded"], first["failed"]), (2, 0))
        self.assertEqual((second["downloaded"], second["skipped"]), (0, 2))
        self.assertEqual(len(self.downloads()), 2)
        self.assertEqual(len(list(self.library.rglob("*.mp3"))), 2)
        self.assertFalse(any(path.is_dir() for path in (self.library / "日文").iterdir()))

    def test_global_video_id_skip_reports_original_category(self):
        original = self.run_job(category="日文")
        other = self.run_job(category="英文")
        self.assertEqual((other["downloaded"], other["skipped"]), (0, 1))
        self.assertEqual(other["items"][0]["path"], original["items"][0]["path"])
        self.assertEqual(len(self.downloads()), 1)
        self.assertEqual(list((self.library / "英文").iterdir()), [])

    def test_removed_download_can_be_downloaded_again(self):
        first = self.run_job()
        Path(first["items"][0]["path"]).unlink()
        second = self.run_job()
        self.assertEqual((second["downloaded"], second["skipped"]), (1, 0))
        self.assertEqual(len(self.downloads()), 2)

    def test_retry_checks_removed_success_in_worker(self):
        first = self.run_job()
        Path(first["items"][0]["path"]).unlink()
        # Queueing the retry must work without inspecting Desktop paths.
        with mock.patch.object(Path, "is_file", side_effect=PermissionError("Desktop denied to UI")):
            retried = self.engine.retry(first["id"])
        self.assertEqual(retried["state"], "queued")
        self.assertTrue(self.engine.process_next())
        final = self.engine.status(first["id"])
        self.assertEqual((final["state"], final["downloaded"], final["failed"]), ("completed", 1, 0))
        self.assertEqual(len(self.downloads()), 2)

    def test_partial_playlist_failure_keeps_later_songs(self):
        self.fixture["playlist"] = ["AAAAAAAAAAA", "DDDDDDDDDDD", None, "BBBBBBBBBBB"]
        self.save_fixture()
        job = self.run_job("playlist", PLAYLIST)
        self.assertEqual((job["state"], job["downloaded"], job["skipped"], job["failed"]), ("partial", 2, 0, 2))
        self.assertTrue((self.library / "日文" / "第二首 歌曲.mp3").is_file())
        self.assertIsNone(self.engine.existing_video("DDDDDDDDDDD"))

    def test_exact_hash_existing_untracked_file_is_preserved(self):
        old = self.library / "古典" / "既有個人音樂.mp3"
        old.parent.mkdir(parents=True)
        shutil.copyfile(self.media / "a.mp3", old)
        before = old.read_bytes()
        job = self.run_job()
        self.assertEqual((job["downloaded"], job["skipped"]), (0, 1))
        self.assertEqual(job["items"][0]["path"], str(old))
        self.assertEqual(old.read_bytes(), before)
        self.assertEqual(len(list(self.library.rglob("*.mp3"))), 1)

    def test_exact_hash_different_video_ids_save_once(self):
        self.run_job()
        job = self.run_job(url="https://youtu.be/CCCCCCCCCCC", category="華語")
        self.assertEqual((job["downloaded"], job["skipped"]), (0, 1))
        self.assertEqual(len(list(self.library.rglob("*.mp3"))), 1)
        self.assertIsNotNone(self.engine.existing_video("CCCCCCCCCCC"))

    def test_same_title_different_bytes_never_overwrites(self):
        old = self.library / "日文" / "天ノ弱 中文星.mp3"
        old.parent.mkdir(parents=True)
        shutil.copyfile(self.media / "b.mp3", old)
        before = sha256(old)
        job = self.run_job()
        self.assertEqual(job["downloaded"], 1)
        self.assertEqual(sha256(old), before)
        self.assertNotEqual(job["items"][0]["path"], str(old))
        self.assertIn("[AAAAAAAAAAA]", job["items"][0]["path"])

    def test_provider_rejecting_hardlinks_uses_exclusive_rename(self):
        old = self.library / "日文" / "天ノ弱 中文星.mp3"
        old.parent.mkdir(parents=True)
        shutil.copyfile(self.media / "b.mp3", old)
        before = sha256(old)
        with mock.patch("music_downloader.os.link", side_effect=OSError(errno.EPERM, "File provider rejects hard links")):
            job = self.run_job()
        self.assertEqual((job["state"], job["downloaded"]), ("completed", 1))
        self.assertEqual(sha256(old), before)
        self.assertNotEqual(job["items"][0]["path"], str(old))
        self.assertEqual(len(list(self.library.rglob("*.mp3"))), 2)
        self.assertEqual(list((self.library.parent / ".MusicDownloader-staging").iterdir()), [])

    def test_crash_between_promotion_and_database_commit_recovers(self):
        job = self.engine.enqueue("single", SINGLE, "日文")
        real_link = os.link
        def link_then_crash(source, target):
            real_link(source, target)
            raise SystemExit("simulated worker crash after file promotion")
        with mock.patch("music_downloader.os.link", side_effect=link_then_crash):
            with self.assertRaises(SystemExit):
                self.engine.process_next()
        self.assertEqual(len(list(self.library.rglob("*.mp3"))), 1)
        self.assertTrue(self.engine.process_next())
        final = self.engine.status(job["id"])
        self.assertEqual((final["state"], final["skipped"], final["failed"]), ("completed", 1, 0))
        self.assertEqual(len(self.downloads()), 1)
        self.assertEqual(len(list(self.library.rglob("*.mp3"))), 1)

    def test_failed_postprocessing_is_not_success_and_retry_recovers(self):
        self.fixture["videos"]["AAAAAAAAAAA"]["postprocess_error"] = True
        self.save_fixture()
        job = self.run_job()
        self.assertEqual((job["state"], job["downloaded"], job["failed"]), ("failed", 0, 1))
        self.assertIsNone(self.engine.existing_video("AAAAAAAAAAA"))
        self.assertEqual(list(self.library.rglob("*.mp3")), [])
        self.fixture["videos"]["AAAAAAAAAAA"].pop("postprocess_error")
        self.save_fixture()
        self.engine.retry(job["id"])
        self.assertTrue(self.engine.process_next())
        self.assertEqual(self.engine.status(job["id"])["downloaded"], 1)

    def test_corrupt_mp3_is_rejected_by_real_ffprobe(self):
        self.fixture["videos"]["AAAAAAAAAAA"]["corrupt"] = True
        self.save_fixture()
        job = self.run_job()
        self.assertEqual((job["state"], job["downloaded"], job["failed"]), ("failed", 0, 1))
        self.assertIsNone(self.engine.existing_video("AAAAAAAAAAA"))
        self.assertEqual(list(self.library.rglob("*.mp3")), [])

    def test_filename_illegal_characters_are_cleaned(self):
        self.fixture["videos"]["AAAAAAAAAAA"]["title"] = '測試 / 歌曲 : 標題*?<>|"\\\n終'
        self.save_fixture()
        job = self.run_job()
        name = Path(job["items"][0]["path"]).name
        self.assertEqual(job["downloaded"], 1)
        self.assertFalse(any(c in name for c in '/\\:*?"<>|\n'))

    def test_invalid_input_rejected_without_escape(self):
        for url in ["https://youtube.com.evil.test/watch?v=AAAAAAAAAAA", "file:///etc/passwd",
                    "https://user@youtube.com/watch?v=AAAAAAAAAAA", "https://youtube.com/watch?v=bad"]:
            with self.subTest(url=url), self.assertRaises(UserError):
                self.engine.enqueue("single", url, "日文")
        for name in ["../escape", ".", "foo/bar", "foo\\bar", "foo:bar", "\x00", "\n"]:
            with self.subTest(category=repr(name)), self.assertRaises(UserError):
                self.engine.enqueue("single", SINGLE, name)
        self.assertFalse((self.root / "escape").exists())

    def test_concurrent_duplicate_submit_has_one_job(self):
        spec = (str(self.home), str(self.library), str(self.fake), "日文")
        context = multiprocessing.get_context("fork")
        with concurrent.futures.ProcessPoolExecutor(max_workers=4, mp_context=context) as pool:
            ids = list(pool.map(enqueue_process, [spec] * 8))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(self.engine.jobs()), 1)
        self.assertEqual(self.engine.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_concurrent_workers_same_song_save_once(self):
        self.fixture["videos"]["AAAAAAAAAAA"]["sleep"] = 0.5
        self.save_fixture()
        self.engine.enqueue("single", SINGLE, "日文")
        self.engine.enqueue("single", SINGLE, "英文")
        spec = (str(self.home), str(self.library), str(self.fake))
        context = multiprocessing.get_context("fork")
        with concurrent.futures.ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
            list(pool.map(process_worker, [spec] * 2))
        while self.engine.process_next():
            pass
        jobs = self.engine.jobs()
        self.assertEqual(sum(j["downloaded"] for j in jobs), 1)
        self.assertEqual(sum(j["skipped"] for j in jobs), 1)
        self.assertEqual(len(self.downloads()), 1)
        self.assertEqual(len(list(self.library.rglob("*.mp3"))), 1)
        self.assertEqual(self.engine.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_interrupted_running_job_recovers(self):
        job = self.engine.enqueue("single", SINGLE, "日文")
        with self.engine.db:
            self.engine.db.execute("UPDATE jobs SET state='running' WHERE id=?", (job["id"],))
        self.assertTrue(self.engine.process_next())
        self.assertEqual(self.engine.status(job["id"])["downloaded"], 1)

    def test_killed_worker_child_keeps_lock_until_exit(self):
        self.fixture["videos"]["AAAAAAAAAAA"]["sleep"] = 1.5
        self.save_fixture()
        job = self.engine.enqueue("single", SINGLE, "日文")
        context = multiprocessing.get_context("fork")
        process = context.Process(target=process_worker, args=((str(self.home), str(self.library), str(self.fake)),))
        process.start()
        deadline = time.monotonic() + 5
        while not self.calls() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(self.calls(), "worker did not start its yt-dlp child")
        process.kill()
        process.join(timeout=2)
        self.assertFalse(process.is_alive())
        self.assertFalse(self.engine.process_next(), "orphan yt-dlp must retain worker lock to prevent a second writer")
        time.sleep(1.6)
        self.assertTrue(self.engine.process_next())
        final = self.engine.status(job["id"])
        self.assertEqual((final["state"], final["downloaded"], final["failed"]), ("completed", 1, 0))
        self.assertEqual(len(list(self.library.rglob("*.mp3"))), 1)

    def test_cancel_running_then_retry_same_job(self):
        self.fixture["videos"]["AAAAAAAAAAA"]["sleep"] = 2
        self.save_fixture()
        job = self.engine.enqueue("single", SINGLE, "日文")
        context = multiprocessing.get_context("fork")
        process = context.Process(target=process_worker, args=((str(self.home), str(self.library), str(self.fake)),))
        process.start()
        deadline = time.monotonic() + 5
        while not self.calls() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(self.calls())
        self.engine.cancel(job["id"])
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
            self.fail("running cancellation did not stop the worker")
        self.assertEqual(self.engine.status(job["id"])["state"], "cancelled")
        self.assertEqual(list(self.library.rglob("*.mp3")), [])
        self.fixture["videos"]["AAAAAAAAAAA"]["sleep"] = 0
        self.save_fixture()
        retried = self.engine.retry(job["id"])
        self.assertEqual(retried["id"], job["id"])
        self.assertTrue(self.engine.process_next())
        final = self.engine.status(job["id"])
        self.assertEqual((final["state"], final["downloaded"]), ("completed", 1))

    def test_cancel_queued_job_does_not_download(self):
        job = self.engine.enqueue("single", SINGLE, "日文")
        self.engine.cancel(job["id"])
        self.assertTrue(self.engine.process_next())
        status = self.engine.status(job["id"])
        self.assertEqual(status["state"], "cancelled")
        self.assertEqual(len(self.downloads()), 0)

    def test_low_disk_space_fails_without_downloading(self):
        job = self.engine.enqueue("single", SINGLE, "日文")
        disk = type("Disk", (), {"free": 0})()
        with mock.patch("music_downloader.shutil.disk_usage", return_value=disk):
            self.assertTrue(self.engine.process_next())
        status = self.engine.status(job["id"])
        self.assertEqual(status["state"], "failed")
        self.assertIn("空間不足", status["error"])
        self.assertEqual(len(self.downloads()), 0)

    def test_missing_ffmpeg_fails_readably(self):
        self.engine.ffmpeg = str(self.root / "does-not-exist")
        job = self.run_job()
        self.assertEqual(job["state"], "failed")
        self.assertIn("必要工具", job["error"])
        self.assertEqual(len(self.downloads()), 0)


if __name__ == "__main__":
    unittest.main()
