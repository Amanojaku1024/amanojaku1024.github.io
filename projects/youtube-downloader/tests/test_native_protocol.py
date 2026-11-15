"""Native helper JSON protocol and viewer launch; all OS processes are mocked."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frontend


class NativeDialogProtocolTest(unittest.TestCase):
    def test_unicode_user_data_is_json_stdin_never_shell_source(self):
        prompt = '中文 空白 "quote" $(printf marker)\n第二行'
        choices = ["日文", "鋼琴 演奏"]
        binary = Path("/temporary app/NativeUI.app/Contents/MacOS/MusicDownloaderUI")
        with mock.patch.object(frontend, "native_binary", return_value=binary), \
                mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout='{"value":"鋼琴 演奏"}', returncode=0)) as run:
            result = frontend.native_dialog("choose", prompt, choices=choices, title="原生視窗")
        self.assertEqual(result, "鋼琴 演奏")
        self.assertEqual(run.call_args.args[0], [str(binary), "dialog"])
        self.assertEqual(json.loads(run.call_args.kwargs["input"]),
                         {"kind": "choose", "title": "原生視窗", "prompt": prompt, "default": "", "choices": choices})
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_cancelled_result_raises_user_cancelled(self):
        with mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout='{"cancelled":true}', returncode=0)):
            with self.assertRaises(frontend.UserCancelled):
                frontend.native_dialog("ask", "請輸入")

    def test_malformed_or_non_object_json_is_a_readable_frontend_error(self):
        for output in ["", "not JSON", "null", "[]", '"text"']:
            with self.subTest(output=output), \
                    mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout=output, returncode=0)):
                with self.assertRaises(frontend.FrontendError):
                    frontend.native_dialog("ask", "請輸入")

    def test_helper_error_and_exit_failure_are_not_success(self):
        for output, code in [('{"error":"無法顯示視窗"}', 1), ('{"value":"ignored"}', 1)]:
            with self.subTest(output=output), \
                    mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout=output, returncode=code)):
                with self.assertRaises(frontend.FrontendError):
                    frontend.native_dialog("ask", "請輸入")

    def test_ask_choose_message_use_native_helper_when_present(self):
        binary = mock.Mock()
        binary.is_file.return_value = True
        with mock.patch.object(frontend, "native_binary", return_value=binary), \
                mock.patch.object(frontend, "native_dialog", side_effect=["輸入文字", "華語", ""]) as dialog, \
                mock.patch.object(frontend, "applescript") as fallback:
            self.assertEqual(frontend.ask("網址", "預設"), "輸入文字")
            self.assertEqual(frontend.choose("分類", ["日文", "華語"]), "華語")
            frontend.message("完成", "結果")
        self.assertEqual(dialog.call_args_list, [mock.call("ask", "網址", "預設"),
                                                mock.call("choose", "分類", choices=["日文", "華語"]),
                                                mock.call("message", "完成", title="結果")])
        fallback.assert_not_called()

    def test_legacy_dialog_fallback_works_without_bundle(self):
        binary = mock.Mock()
        binary.is_file.return_value = False
        with mock.patch.object(frontend, "native_binary", return_value=binary), \
                mock.patch.object(frontend, "applescript", return_value="回答") as fallback, \
                mock.patch.object(frontend, "native_dialog") as dialog:
            self.assertEqual(frontend.ask("網址"), "回答")
        fallback.assert_called_once()
        dialog.assert_not_called()


class ViewerIntegrationTest(unittest.TestCase):
    def test_viewer_is_detached_and_receives_only_status_adapter_arguments(self):
        with tempfile.TemporaryDirectory(prefix="musicdownloader-ui-") as directory:
            home = Path(directory)
            app = home / "app"
            app.mkdir()
            binary = app / "NativeUI.app/Contents/MacOS/MusicDownloaderUI"
            binary.parent.mkdir(parents=True)
            binary.touch()
            with mock.patch.object(frontend, "__file__", str(app / "frontend.py")), \
                    mock.patch.object(frontend, "native_binary", return_value=binary), \
                    mock.patch.object(frontend.subprocess, "Popen") as spawn:
                self.assertTrue(frontend.show_progress("a-job"))
            self.assertEqual(spawn.call_args.args[0], [str(binary), "progress", "--home", str(home.resolve()), "--python", sys.executable,
                                                      "--engine", str(app.resolve() / "progress_status.py"), "--job", "a-job"])
            self.assertTrue(spawn.call_args.kwargs["start_new_session"])
            spawn.return_value.wait.assert_not_called()
            self.assertTrue((home / "logs/ui.log").is_file())

    def test_missing_bundle_does_not_spawn_a_process(self):
        binary = mock.Mock()
        binary.is_file.return_value = False
        with mock.patch.object(frontend, "native_binary", return_value=binary), \
                mock.patch.object(frontend.subprocess, "Popen") as spawn:
            self.assertFalse(frontend.show_progress("a-job"))
        spawn.assert_not_called()

    def test_status_uses_viewer_without_entering_legacy_dialog_loop(self):
        with mock.patch.object(frontend, "show_progress", return_value=True) as show, \
                mock.patch.object(frontend, "backend") as backend, \
                mock.patch.object(frontend, "choose") as choose:
            frontend.status()
        show.assert_called_once_with()
        backend.assert_not_called()
        choose.assert_not_called()

    def test_notification_failure_does_not_prevent_viewer_after_enqueue(self):
        events = []
        def opened(job_id):
            events.append("progress")
            self.assertEqual(job_id, "queued-job")
            return True
        def denied(_text):
            events.append("notify")
            raise frontend.FrontendError("通知未授權")
        with mock.patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(stdout="https://youtu.be/AAAAAAAAAAA")), \
                mock.patch.object(frontend, "pick_category", return_value="日文"), \
                mock.patch.object(frontend, "pick_download_options", return_value=([], False)), \
                mock.patch.object(frontend, "choose", return_value="開始下載"), \
                mock.patch.object(frontend, "backend", return_value={"id": "queued-job", "state": "queued"}) as backend, \
                mock.patch.object(frontend, "show_progress", side_effect=opened), \
                mock.patch.object(frontend, "notify", side_effect=denied), \
                mock.patch.object(frontend, "message") as message, mock.patch("builtins.print"):
            frontend.download("single")
        self.assertEqual(events, ["progress", "notify"])
        backend.assert_called_once()
        message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
