import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock


spec = importlib.util.spec_from_file_location(
    "decor_douyin_collector_test", Path(__file__).resolve().parents[1] / "backend/collector_douyin.py"
)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class DouyinCollectorTests(unittest.TestCase):
    def aweme(self, index, **extra):
        return {"aweme_id": str(7600000000000000000 + index), "desc": f"Video {index}", **extra}

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
