"""Read-only progress parsing with isolated logs; no GUI or download processes."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from progress_status import enrich_status, parse_track_progress

VIDEO = "AAAAAAAAAAA"
START = "[youtube] Extracting URL: https://www.youtube.com/watch?v=" + VIDEO + "\n"


class TrackProgressTest(unittest.TestCase):
    def test_exact_download_percent_speed_eta_from_latest_line(self):
        result = parse_track_progress(START + "[download] 12.0% of 10.00MiB at 1.25MiB/s ETA 00:08\n"
                                      "[download] 42.7% of 10.00MiB at 2.50MiB/s ETA 00:03\n", VIDEO)
        self.assertEqual(result, {"phase": "downloading", "track_percent": 42.7, "speed_text": "2.50MiB/s", "eta_text": "00:03"})

    def test_ansi_colors_and_carriage_return_lines(self):
        result = parse_track_progress(START + "\x1b[0;94m[download]\x1b[0m 0.1% of 3MiB at 20.00KiB/s ETA 00:30\r"
                                      "[download] 25.0% of 3MiB at 1.00MiB/s ETA 00:03\r", VIDEO)
        self.assertEqual(result["track_percent"], 25.0)

    def test_no_marker_or_invalid_percent_does_not_invent_progress(self):
        for text in ["[download] 90.0% of 2MiB", START + "[download] 101.0% of 2MiB",
                     START + "[download] -5.0% of 2MiB", START + "[download] nan% of 2MiB",
                     START + "[download] Destination: song.webm"]:
            with self.subTest(text=text):
                self.assertIsNone(parse_track_progress(text, VIDEO)["track_percent"])

    def test_previous_video_progress_is_not_reused(self):
        old = START + "[download] 100% of 2MiB in 00:01 at 2.00MiB/s\n"
        newer = "[youtube] Extracting URL: https://www.youtube.com/watch?v=BBBBBBBBBBB\n"
        self.assertIsNone(parse_track_progress(old + newer, VIDEO)["track_percent"])
        self.assertIsNone(parse_track_progress(old + newer, "BBBBBBBBBBB")["track_percent"])

    def test_latest_attempt_of_same_video_starts_indeterminate(self):
        result = parse_track_progress(START + "[download] 90.0% of 2MiB\n" + START + "[youtube] Downloading webpage\n", VIDEO)
        self.assertEqual(result["phase"], "preparing")
        self.assertIsNone(result["track_percent"])

    def test_postprocessing_phases_clear_percent_speed_eta(self):
        for marker, expected in [("[ExtractAudio] Destination: song.mp3", "transcoding"),
                                 ("[Metadata] Adding metadata", "metadata"),
                                 ("[EmbedThumbnail] Adding thumbnail", "cover"),
                                 ("[ThumbnailsConvertor] Converting thumbnail to jpg", "cover"),
                                 ("[FixupM4a] Correcting container", "transcoding"),
                                 ("[FixupM3u8] Fixing MPEG-TS", "transcoding"),
                                 ("[Merger] Merging formats", "transcoding")]:
            with self.subTest(marker=marker):
                result = parse_track_progress(START + "[download] 100% of 2MiB at 2.00MiB/s ETA 00:00\n" + marker, VIDEO)
                self.assertEqual(result["phase"], expected)
                self.assertIsNone(result["track_percent"])
                self.assertEqual((result["speed_text"], result["eta_text"]), ("", ""))

    def test_thumbnail_preparation_can_be_followed_by_audio_download(self):
        result = parse_track_progress(START + "[ThumbnailsConvertor] Converting thumbnail to jpg\n"
                                      "[download] 20.0% of 2MiB at 1.00MiB/s ETA 00:02", VIDEO)
        self.assertEqual((result["phase"], result["track_percent"]), ("downloading", 20.0))

    def test_youtube_wait_clears_stale_progress(self):
        result = parse_track_progress(START + "[download] 2.0% of 2MiB at 2.00MiB/s ETA 00:02\n"
                                      "[download] Sleeping 4.00 seconds as required by the site...", VIDEO)
        self.assertEqual((result["phase"], result["track_percent"], result["speed_text"]), ("waiting", None, ""))

    def test_unknown_speed_and_eta_are_not_guessed(self):
        result = parse_track_progress(START + "[download] 0.0% of 5MiB at Unknown B/s ETA Unknown", VIDEO)
        self.assertEqual((result["track_percent"], result["speed_text"], result["eta_text"]), (0.0, "", ""))


class OverallProgressTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="musicdownloader-progress-")
        self.home = Path(self.temp.name)
        (self.home / "logs").mkdir()
        self.library = self.home / "桌面" / "音樂"

    def tearDown(self):
        self.temp.cleanup()

    def job(self, **changes):
        job = {"id": "test-job", "state": "running", "enumerated": 1,
               "downloaded": 99, "skipped": 99, "failed": 99,
               "items": [{"position": 1, "state": "downloaded", "video_id": "BBBBBBBBBBB"},
                         {"position": 2, "state": "skipped", "video_id": "CCCCCCCCCCC"},
                         {"position": 3, "state": "failed", "video_id": "DDDDDDDDDDD"},
                         {"position": 4, "state": "pending", "video_id": "EEEEEEEEEEE"},
                         {"position": 5, "state": "running", "video_id": VIDEO, "title": "中文歌曲"}]}
        job.update(changes)
        return job

    def test_overall_counts_only_settled_items_and_never_blends_track_percent(self):
        (self.home / "logs/test-job.log").write_text(START + "[download] 45.0% of 2MiB at 1.00MiB/s ETA 00:02")
        source = self.job()
        before = copy.deepcopy(source)
        result = enrich_status(source, self.home, self.library)
        self.assertEqual((result["completed_items"], result["total"], result["overall_percent"]), (3, 5, 60.0))
        self.assertEqual(result["track_percent"], 45.0)
        self.assertEqual((result["current_position"], result["current_title"]), (5, "中文歌曲"))
        self.assertEqual(result["library"], str(self.library))
        self.assertEqual(source, before)

    def test_unknown_playlist_total_is_indeterminate(self):
        result = enrich_status(self.job(enumerated=0, items=[]), self.home, self.library)
        self.assertIsNone(result["total"])
        self.assertIsNone(result["overall_percent"])
        self.assertIsNone(result["track_percent"])
        self.assertEqual((result["phase"], result["completed_items"]), ("listing", 0))

    def test_completed_or_cancelled_state_never_uses_stale_track_progress(self):
        (self.home / "logs/test-job.log").write_text(START + "[download] 100% of 2MiB")
        for state in ["completed", "partial", "failed", "cancelled"]:
            with self.subTest(state=state):
                result = enrich_status(self.job(state=state), self.home, self.library)
                self.assertEqual(result["phase"], state)
                self.assertIsNone(result["track_percent"])
                self.assertEqual(result["overall_percent"], 60.0)

    def test_missing_or_truncated_log_is_preparing_not_zero_percent(self):
        result = enrich_status(self.job(), self.home, self.library)
        self.assertEqual(result["phase"], "preparing")
        self.assertIsNone(result["track_percent"])
        (self.home / "logs/test-job.log").write_text(START + "[download] 90.0% of 2MiB\n" + "unrelated log line\n" * 10000)
        result = enrich_status(self.job(), self.home, self.library)
        self.assertEqual(result["phase"], "preparing")
        self.assertIsNone(result["track_percent"])

    def test_bad_job_id_cannot_read_arbitrary_path(self):
        with mock.patch.object(Path, "open", side_effect=AssertionError("must not read an untrusted path")):
            result = enrich_status(self.job(id="../outside"), self.home, self.library)
        self.assertEqual(result["phase"], "preparing")

    def test_cancel_requested_changes_text_only(self):
        result = enrich_status(self.job(cancel_requested=1), self.home, self.library)
        self.assertIn("正在取消", result["phase_text"])
        self.assertEqual(result["state"], "running")
        self.assertEqual(result["overall_percent"], 60.0)


if __name__ == "__main__":
    unittest.main()
