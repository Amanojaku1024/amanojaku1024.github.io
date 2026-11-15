"""Validate untrusted URLs/category input without opening any GUI."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frontend

MIX = "https://music.youtube.com/watch?v=AAAAAAAAAAA&list=RDAAAAAAAAAAA"


class FrontendValidationTest(unittest.TestCase):
    def setUp(self):
        # A concurrently built UI bundle must never make unit tests open real GUI.
        progress_patch = mock.patch.object(frontend, "show_progress", return_value=False)
        self.progress_mock = progress_patch.start()
        self.addCleanup(progress_patch.stop)
        confirmation_patch = mock.patch.object(frontend, "choose", return_value="開始下載")
        self.confirmation_mock = confirmation_patch.start()
        self.addCleanup(confirmation_patch.stop)

    def test_youtube_and_music_single_urls(self):
        for url in ["https://www.youtube.com/watch?v=AAAAAAAAAAA&list=PLTEST123456",
                    "https://music.youtube.com/watch?v=AAAAAAAAAAA",
                    "https://youtu.be/AAAAAAAAAAA", "https://youtube.com/shorts/AAAAAAAAAAA",
                    "https://youtube.com/live/AAAAAAAAAAA", "https://youtube.com/embed/AAAAAAAAAAA"]:
            with self.subTest(url=url):
                self.assertEqual(frontend.valid_url(url, "single"), url)

    def test_clipboard_text_and_manual_url(self):
        self.assertEqual(frontend.valid_url("分享這首歌：https://youtu.be/AAAAAAAAAAA。", "single"),
                         "https://youtu.be/AAAAAAAAAAA")
        self.assertEqual(frontend.valid_url("music.youtube.com/watch?v=AAAAAAAAAAA", "single"),
                         "https://music.youtube.com/watch?v=AAAAAAAAAAA")

    def test_playlist_requires_list(self):
        self.assertIsNone(frontend.valid_url("https://youtube.com/watch?v=AAAAAAAAAAA", "playlist"))
        self.assertIsNotNone(frontend.valid_url("https://music.youtube.com/playlist?list=PLTEST123456", "playlist"))
        self.assertIsNotNone(frontend.valid_url("https://youtube.com/watch?v=AAAAAAAAAAA&list=RDMM", "playlist"))

    def test_mix_count_prompt_has_default_and_rejects_invalid_counts(self):
        with mock.patch.object(frontend, "ask", side_effect=["0", "501", "1.5", "50"]) as ask, \
                mock.patch.object(frontend, "message") as message:
            self.assertEqual(frontend.ask_mix_limit(), 50)
        self.assertEqual(message.call_count, 3)
        self.assertTrue(all(call.args[1] == "50" for call in ask.call_args_list))

    def test_mix_download_submits_only_confirmed_count(self):
        with mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout=MIX)), \
                mock.patch.object(frontend, "ask_playlist_limit", return_value=2) as count, \
                mock.patch.object(frontend, "pick_category", return_value="日文"), \
                mock.patch.object(frontend, "pick_download_options", return_value=([], True)), \
                mock.patch.object(frontend, "backend", return_value={"id": "test", "state": "queued"}) as backend, \
                mock.patch.object(frontend, "notify"), mock.patch("builtins.print"):
            frontend.download("playlist")
        count.assert_called_once()
        backend.assert_called_once_with("submit-json", payload={"mode": "playlist", "url": MIX, "category": "日文", "playlist_limit": 2,
                                                                 "routes": [], "auto_piano": True, "piano_category": "鋼琴"})

    def test_cancel_mix_count_does_not_create_download_job(self):
        with mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout=MIX)), \
                mock.patch.object(frontend, "ask_playlist_limit", side_effect=frontend.UserCancelled), \
                mock.patch.object(frontend, "pick_category") as category, \
                mock.patch.object(frontend, "backend") as backend:
            with self.assertRaises(frontend.UserCancelled):
                frontend.download("playlist")
        category.assert_not_called()
        backend.assert_not_called()

    def test_single_mix_url_does_not_request_playlist_count(self):
        with mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout=MIX)), \
                mock.patch.object(frontend, "ask_playlist_limit") as count, \
                mock.patch.object(frontend, "pick_category", return_value="日文"), \
                mock.patch.object(frontend, "pick_download_options", return_value=([], False)), \
                mock.patch.object(frontend, "backend", return_value={"id": "test", "state": "queued"}) as backend, \
                mock.patch.object(frontend, "notify"), mock.patch("builtins.print"):
            frontend.download("single")
        count.assert_not_called()
        self.assertNotIn("playlist_limit", backend.call_args.kwargs["payload"])

    def test_normal_playlist_asks_for_scope_and_submits_explicit_all(self):
        url = "https://music.youtube.com/playlist?list=PLTEST123456"
        with mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout=url)), \
                mock.patch.object(frontend, "ask_playlist_limit", return_value=None) as count, \
                mock.patch.object(frontend, "pick_category", return_value="日文"), \
                mock.patch.object(frontend, "pick_download_options", return_value=([], False)), \
                mock.patch.object(frontend, "backend", return_value={"id": "test", "state": "queued"}) as backend, \
                mock.patch.object(frontend, "notify"), mock.patch("builtins.print"):
            frontend.download("playlist")
        count.assert_called_once_with(url)
        self.assertIn("playlist_limit", backend.call_args.kwargs["payload"])
        self.assertIsNone(backend.call_args.kwargs["payload"]["playlist_limit"])

    def test_normal_playlist_scope_accepts_zero_for_all(self):
        with mock.patch.object(frontend, "ask", return_value="0"):
            self.assertIsNone(frontend.ask_playlist_limit("https://youtube.com/playlist?list=PLTEST123456"))
        with mock.patch.object(frontend, "ask", side_effect=["10001", "-1", "1.5", "10000"]), \
                mock.patch.object(frontend, "message") as message:
            self.assertEqual(frontend.ask_playlist_limit("https://youtube.com/playlist?list=PLTEST123456"), 10000)
        self.assertEqual(message.call_count, 3)

    def test_route_range_parser_and_bounds(self):
        for text, expected in [("3", (3, 3)), ("1-3", (1, 3)), (" １～３ ", (1, 3)), ("2 至 3", (2, 3)), ("1–2", (1, 2))]:
            with self.subTest(text=text):
                self.assertEqual(frontend.parse_route_range(text, 3), expected)
        for text in ["0", "3-1", "1-4", "1,2", "../3", "1;echo test", ""]:
            with self.subTest(text=text), self.assertRaises(frontend.FrontendError):
                frontend.parse_route_range(text, 3)

    def test_route_picker_rejects_overlap_and_keeps_adjacent_ranges(self):
        with mock.patch.object(frontend, "ask", side_effect=["1-2", "2-3", "3"]), \
                mock.patch.object(frontend, "pick_category", side_effect=["日文", "華語"]), \
                mock.patch.object(frontend, "choose", side_effect=["新增另一段", "完成分配"]), \
                mock.patch.object(frontend, "message") as message:
            routes = frontend.pick_routes(3)
        self.assertEqual(routes, [{"start": 1, "end": 2, "category": "日文"}, {"start": 3, "end": 3, "category": "華語"}])
        message.assert_called_once()

    def test_route_picker_can_remove_last_range(self):
        with mock.patch.object(frontend, "ask", side_effect=["1", "2"]), \
                mock.patch.object(frontend, "pick_category", side_effect=["日文", "華語"]), \
                mock.patch.object(frontend, "choose", side_effect=["移除最後一段", "完成分配"]):
            routes = frontend.pick_routes(3)
        self.assertEqual(routes, [{"start": 2, "end": 2, "category": "華語"}])

    def test_route_and_automatic_options_are_sent_to_backend(self):
        routes = [{"start": 1, "end": 2, "category": "華語"}]
        with mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout=MIX)), \
                mock.patch.object(frontend, "ask_playlist_limit", return_value=3), \
                mock.patch.object(frontend, "pick_category", return_value="日文"), \
                mock.patch.object(frontend, "pick_download_options", return_value=(routes, True)) as options, \
                mock.patch.object(frontend, "backend", return_value={"id": "test", "state": "queued"}) as backend, \
                mock.patch.object(frontend, "notify"), mock.patch("builtins.print"):
            frontend.download("playlist")
        options.assert_called_once_with("playlist", 3)
        self.assertEqual(backend.call_args.kwargs["payload"]["routes"], routes)
        self.assertTrue(backend.call_args.kwargs["payload"]["auto_piano"])

    def test_classification_option_picker_limits_single_to_supported_choices(self):
        with mock.patch.object(frontend, "choose", return_value="指定分類＋自動判斷鋼琴") as choose, \
                mock.patch.object(frontend, "pick_routes") as routes:
            self.assertEqual(frontend.pick_download_options("single"), ([], True))
        self.assertEqual(len(choose.call_args.args[1]), 2)
        routes.assert_not_called()

    def test_classification_option_picker_combines_routes_and_auto_piano(self):
        rules = [{"start": 1, "end": 1, "category": "華語"}]
        with mock.patch.object(frontend, "choose", return_value="依序號分配（其餘自動判斷鋼琴）"), \
                mock.patch.object(frontend, "pick_routes", return_value=rules) as routes:
            self.assertEqual(frontend.pick_download_options("playlist", 3), (rules, True))
        routes.assert_called_once_with(3)

    def test_reject_untrusted_hosts_or_credentials(self):
        for url in ["https://youtube.com.evil.test/watch?v=AAAAAAAAAAA",
                    "https://www.youtube.com@evil.test/watch?v=AAAAAAAAAAA",
                    "https://evil@www.youtube.com/watch?v=AAAAAAAAAAA",
                    "https://www.youtube.com:444/watch?v=AAAAAAAAAAA",
                    "https://youtube.com/not-a-watch?v=AAAAAAAAAAA",
                    "file:///tmp/music.mp3", "https://youtube.com/watch?v=invalid"]:
            with self.subTest(url=url):
                self.assertIsNone(frontend.valid_url(url, "single"))

    def test_category_unicode_and_rejected_paths(self):
        self.assertEqual(frontend.valid_category("  日文 音樂  "), "日文 音樂")
        self.assertEqual(frontend.valid_category("Cafe\u0301"), "Café")
        for category in ["", ".", "..", "../音樂", "foo/bar", "foo\\bar", "foo:bar", "foo\nbar", "\x00", "字" * 100]:
            with self.subTest(category=repr(category)):
                with self.assertRaises(frontend.FrontendError):
                    frontend.valid_category(category)


if __name__ == "__main__":
    unittest.main()
