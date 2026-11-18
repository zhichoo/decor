import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch


spec = importlib.util.spec_from_file_location(
    "decor_douyin_collector_test", Path(__file__).resolve().parents[1] / "backend/collector_douyin.py"
)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class DouyinCollectorTests(unittest.TestCase):
    def aweme(self, index, **extra):
        return {"aweme_id": str(7600000000000000000 + index), "desc": f"Video {index}", **extra}

    def run_mode(self, mode, *, available=True):
        playwright = MagicMock()
        context = MagicMock()
        context.new_page.return_value.locator.return_value.inner_text.return_value = "Creator"
        context.new_page.return_value.locator.return_value.count.return_value = 0
        api = SimpleNamespace(sync_playwright=Mock(return_value=playwright))
        output = io.StringIO()
        videos = collector.recursive_find_video_objects(self.aweme(1)) if available else []
        with patch.dict("sys.modules", {"playwright.sync_api": api}), \
             patch("sys.argv", ["collector", "--mode", mode]), \
             patch.object(collector, "launch_context", return_value=context) as launch, \
             patch.object(collector, "cookie_status", return_value={"logged_in": available}), \
             patch.object(collector, "collect_render_data_videos", return_value=videos), \
             redirect_stdout(output):
            result = collector.main()
        return result, json.loads(output.getvalue()), launch, context

    def test_collection_and_status_never_show_a_browser_window(self):
        for mode in ("collect", "status"):
            with self.subTest(mode=mode):
                result, payload, launch, context = self.run_mode(mode)
                self.assertEqual(result, 0)
                self.assertTrue(payload["ok"])
                self.assertTrue(launch.call_args.kwargs["headless"])
                launch.assert_called_once()
                context.close.assert_called_once()

    def test_missing_login_does_not_fall_back_to_a_visible_window(self):
        result, payload, launch, context = self.run_mode("collect", available=False)
        self.assertEqual(result, 1)
        self.assertEqual(payload["error"], "douyin_profile_data_unavailable")
        self.assertTrue(launch.call_args.kwargs["headless"])
        launch.assert_called_once()
        context.close.assert_called_once()

    def test_explicit_login_can_show_its_interactive_window(self):
        result, payload, launch, context = self.run_mode("login")
        self.assertEqual(result, 0)
        self.assertTrue(payload["logged_in"])
        self.assertFalse(launch.call_args.kwargs["headless"])
        context.close.assert_called_once()

    def test_browser_launcher_defaults_to_headless(self):
        playwright = MagicMock()
        with tempfile.TemporaryDirectory() as profile:
            context = collector.launch_context(playwright, profile)
            context.close()
        launch = playwright.chromium.launch_persistent_context
        launch.assert_called_once()
        self.assertTrue(launch.call_args.kwargs["headless"])

    def test_profile_lock_blocks_other_process_and_releases_on_close_or_launch_failure(self):
        code = """import fcntl, pathlib, sys
with open(pathlib.Path(sys.argv[1]) / '.decor-profile.lock', 'a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    print('locked', flush=True)
    sys.stdin.readline()
"""
        with tempfile.TemporaryDirectory() as profile:
            child = subprocess.Popen([sys.executable, "-c", code, profile], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), "locked")
                playwright = MagicMock()
                with self.assertRaises(collector.BrowserProfileBusy):
                    collector.launch_context(playwright, profile, lock_timeout=0)
                playwright.chromium.launch_persistent_context.assert_not_called()
            finally:
                child.communicate("release\n", timeout=5)
            context = collector.launch_context(playwright, profile, lock_timeout=0)
            with self.assertRaises(collector.BrowserProfileBusy):
                collector.launch_context(playwright, profile, lock_timeout=0)
            context.close()
            playwright.chromium.launch_persistent_context.side_effect = RuntimeError("launch failed")
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                collector.launch_context(playwright, profile, lock_timeout=0)
            playwright.chromium.launch_persistent_context.side_effect = None
            collector.launch_context(playwright, profile, lock_timeout=0).close()

    def test_busy_status_does_not_claim_the_user_is_logged_out(self):
        api = SimpleNamespace(sync_playwright=MagicMock())
        output = io.StringIO()
        with patch.dict("sys.modules", {"playwright.sync_api": api}), \
             patch("sys.argv", ["collector", "--mode", "status"]), \
             patch.object(collector, "launch_context", side_effect=collector.BrowserProfileBusy), \
             redirect_stdout(output):
            self.assertEqual(collector.main(), 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["busy"])
        self.assertNotIn("logged_in", payload)

    def test_pin_flags_are_not_interpreted_by_python_truthiness(self):
        for key in ("is_top", "isTop", "is_pinned", "isPinned"):
            for value in (True, 1, "1", "true"):
                with self.subTest(key=key, value=value):
                    self.assertTrue(collector.is_pinned_video({key: value}))
            for value in (False, 0, "0", "false", None):
                with self.subTest(key=key, value=value):
                    self.assertFalse(collector.is_pinned_video({key: value}))

    def test_excludes_pins_before_filling_requested_count(self):
        raw = {"aweme_list": [self.aweme(0, is_top=1), self.aweme(1, is_top="0"),
                              self.aweme(2), self.aweme(3)]}
        target = []
        collector.append_unique_videos(target, collector.recursive_find_video_objects(raw), set(), 2)
        self.assertEqual([item["title"] for item in target], ["Video 1", "Video 2"])

    def test_wrapper_pin_applies_to_nested_video(self):
        items = collector.recursive_find_video_objects(
            {"items": [{"isTop": True, "aweme_info": self.aweme(1)}, {"aweme_info": self.aweme(2)}]}
        )
        self.assertEqual([item["is_pinned"] for item in items], [True, False])

    def test_later_pin_evidence_removes_unmarked_copy_and_blocks_fallback(self):
        target, seen, excluded = [], set(), set()
        plain = collector.recursive_find_video_objects(self.aweme(1))
        collector.append_unique_videos(target, plain, seen, 2, excluded)
        pinned = collector.recursive_find_video_objects(self.aweme(1, is_top=1))
        collector.append_unique_videos(target, pinned, seen, 2, excluded)
        collector.append_unique_videos(target, plain, set(), 2, excluded)
        self.assertEqual(target, [])

    def test_pin_evidence_after_limit_still_wins(self):
        items = collector.recursive_find_video_objects(
            [self.aweme(1), self.aweme(2), self.aweme(1, is_top=1)]
        )
        target = []
        collector.append_unique_videos(target, items, set(), 1)
        self.assertEqual([item["title"] for item in target], ["Video 2"])

    def test_render_data_cannot_restore_response_pins(self):
        excluded = {collector.canonical_video_url_from_id(self.aweme(1)["aweme_id"])}
        page = Mock()
        page.eval_on_selector_all.return_value = [
            {"id": "RENDER_DATA", "text": json.dumps({"aweme_list": [self.aweme(1), self.aweme(2)]})}
        ]
        videos = collector.collect_render_data_videos(page, 5, excluded)
        self.assertEqual([item["title"] for item in videos], ["Video 2"])


if __name__ == "__main__":
    unittest.main()
