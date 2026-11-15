"""Final review and edit flow; no production backend or GUI is invoked."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frontend

PLAYLIST = "https://music.youtube.com/playlist?list=PLTEST123456"
MIX = "https://music.youtube.com/watch?v=AAAAAAAAAAA&list=RDAAAAAAAAAAA"
SINGLE = "https://youtu.be/AAAAAAAAAAA"
ROUTES = [{"start": 1, "end": 2, "category": "華語"}]


class DownloadReviewTest(unittest.TestCase):
    def setUp(self):
        for method in ["native_dialog", "applescript"]:
            patch = mock.patch.object(frontend, method, side_effect=AssertionError("unit tests must not open real GUI"))
            patch.start()
            self.addCleanup(patch.stop)

    def test_summary_displays_canonical_url_scope_category_and_manual_rules(self):
        summary = frontend.download_summary("playlist", MIX, "日文", 20, ROUTES, True)
        self.assertIn("https://www.youtube.com/watch?v=AAAAAAAAAAA&list=RDAAAAAAAAAAA", summary)
        self.assertIn("前 20 首", summary)
        self.assertIn("預設分類：日文", summary)
        self.assertIn("第 1–2 首 → 華語", summary)
        self.assertIn("手動分配優先", summary)

    def test_single_acceptance_has_no_playlist_limit(self):
        with mock.patch.object(frontend, "choose", return_value="開始下載"):
            payload = frontend.review_download_settings("single", SINGLE, "日文", None, [], False)
        self.assertNotIn("playlist_limit", payload)
        self.assertEqual(payload["url"], SINGLE)
        self.assertEqual(payload["piano_category"], "鋼琴")

    def test_edit_default_category_keeps_other_choices(self):
        with mock.patch.object(frontend, "choose", side_effect=["修改預設分類", "開始下載"]), \
                mock.patch.object(frontend, "pick_category", return_value="英文") as category, \
                mock.patch.object(frontend, "pick_download_options") as options:
            payload = frontend.review_download_settings("playlist", PLAYLIST, "日文", 20, ROUTES, True)
        self.assertEqual(payload["category"], "英文")
        self.assertEqual(payload["playlist_limit"], 20)
        self.assertEqual(payload["routes"], ROUTES)
        self.assertTrue(payload["auto_piano"])
        category.assert_called_once()
        options.assert_not_called()

    def test_edit_scope_keeps_still_valid_routes(self):
        with mock.patch.object(frontend, "choose", side_effect=["修改下載首數", "開始下載"]), \
                mock.patch.object(frontend, "ask_playlist_limit", return_value=5), \
                mock.patch.object(frontend, "pick_download_options") as options, \
                mock.patch.object(frontend, "message") as message:
            payload = frontend.review_download_settings("playlist", PLAYLIST, "日文", 20, ROUTES, False)
        self.assertEqual(payload["playlist_limit"], 5)
        self.assertEqual(payload["routes"], ROUTES)
        options.assert_not_called()
        message.assert_not_called()

    def test_smaller_scope_requires_replacing_out_of_range_rules(self):
        old = [{"start": 6, "end": 10, "category": "古典"}]
        with mock.patch.object(frontend, "choose", side_effect=["修改下載首數", "開始下載"]), \
                mock.patch.object(frontend, "ask_playlist_limit", return_value=5), \
                mock.patch.object(frontend, "pick_download_options", return_value=(ROUTES, True)) as options, \
                mock.patch.object(frontend, "message") as message:
            payload = frontend.review_download_settings("playlist", PLAYLIST, "日文", 20, old, False)
        self.assertEqual((payload["playlist_limit"], payload["routes"], payload["auto_piano"]), (5, ROUTES, True))
        message.assert_called_once()
        options.assert_called_once_with("playlist", 5)

    def test_edit_classification_keeps_url_scope_and_default_category(self):
        with mock.patch.object(frontend, "choose", side_effect=["重新設定分類方式／序號分配", "開始下載"]), \
                mock.patch.object(frontend, "pick_download_options", return_value=(ROUTES, True)):
            payload = frontend.review_download_settings("playlist", PLAYLIST, "日文", 20, [], False)
        self.assertEqual((payload["url"], payload["category"], payload["playlist_limit"]), (PLAYLIST, "日文", 20))
        self.assertEqual(payload["routes"], ROUTES)
        self.assertTrue(payload["auto_piano"])

    def test_replace_playlist_url_reasks_scope_for_the_new_url(self):
        with mock.patch.object(frontend, "choose", side_effect=["更換網址", "開始下載"]), \
                mock.patch.object(frontend, "ask_download_url", return_value=MIX) as ask_url, \
                mock.patch.object(frontend, "ask_playlist_limit", return_value=3) as scope:
            payload = frontend.review_download_settings("playlist", PLAYLIST, "日文", None, [], False)
        ask_url.assert_called_once_with("playlist", PLAYLIST)
        scope.assert_called_once_with(MIX)
        self.assertEqual((payload["url"], payload["playlist_limit"]), (MIX, 3))

    def test_replace_single_url_does_not_ask_playlist_scope(self):
        new = "https://youtu.be/BBBBBBBBBBB"
        with mock.patch.object(frontend, "choose", side_effect=["更換網址", "開始下載"]), \
                mock.patch.object(frontend, "ask_download_url", return_value=new), \
                mock.patch.object(frontend, "ask_playlist_limit") as scope:
            payload = frontend.review_download_settings("single", SINGLE, "日文", None, [], False)
        self.assertEqual(payload["url"], new)
        self.assertNotIn("playlist_limit", payload)
        scope.assert_not_called()

    def test_valid_clipboard_url_is_shown_for_confirmation_before_enqueue(self):
        order = []
        def confirm(prompt, choices):
            order.append("confirm")
            self.assertIn("https://www.youtube.com/watch?v=AAAAAAAAAAA", prompt)
            self.assertIn("開始下載", choices)
            return "開始下載"
        def enqueue(*args, **kwargs):
            order.append("enqueue")
            return {"id": "fixture-job", "state": "queued"}
        with mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout=SINGLE)), \
                mock.patch.object(frontend, "pick_category", return_value="日文"), \
                mock.patch.object(frontend, "pick_download_options", return_value=([], False)), \
                mock.patch.object(frontend, "choose", side_effect=confirm), \
                mock.patch.object(frontend, "backend", side_effect=enqueue), \
                mock.patch.object(frontend, "show_progress", return_value=False), \
                mock.patch.object(frontend, "notify"), mock.patch("builtins.print"):
            frontend.download("single")
        self.assertEqual(order, ["confirm", "enqueue"])

    def test_cancelling_final_review_never_enqueues_or_opens_progress(self):
        with mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout=SINGLE)), \
                mock.patch.object(frontend, "pick_category", return_value="日文"), \
                mock.patch.object(frontend, "pick_download_options", return_value=([], False)), \
                mock.patch.object(frontend, "choose", side_effect=frontend.UserCancelled), \
                mock.patch.object(frontend, "backend") as backend, \
                mock.patch.object(frontend, "show_progress") as progress:
            with self.assertRaises(frontend.UserCancelled):
                frontend.download("single")
        backend.assert_not_called()
        progress.assert_not_called()

    def test_cancelling_a_review_edit_never_enqueues(self):
        with mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout=SINGLE)), \
                mock.patch.object(frontend, "pick_category", side_effect=["日文", frontend.UserCancelled()]), \
                mock.patch.object(frontend, "pick_download_options", return_value=([], False)), \
                mock.patch.object(frontend, "choose", return_value="修改預設分類"), \
                mock.patch.object(frontend, "backend") as backend:
            with self.assertRaises(frontend.UserCancelled):
                frontend.download("single")
        backend.assert_not_called()

    def test_url_error_retains_entered_text_for_correction(self):
        with mock.patch.object(frontend, "ask", side_effect=["bad value", SINGLE]) as ask, \
                mock.patch.object(frontend, "message") as message:
            self.assertEqual(frontend.ask_download_url("single", "old"), SINGLE)
        self.assertEqual(ask.call_args_list[1].args[1], "bad value")
        message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
