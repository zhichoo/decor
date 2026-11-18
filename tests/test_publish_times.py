"""Publish times: one meaning for text without an offset (Beijing time) across collector, server and migration."""
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


with patch.dict(os.environ, {"ADMIN_PASSWORD": "test-password-only", "ADMIN_SESSION_SECRET": "test-signing-key-only",
                             "DATABASE_URL": "postgresql://localhost/unused_test_db"}):
    server = load("decor_publish_time_server", "backend/server.py")
collector = load("decor_publish_time_collector", "backend/collector_douyin.py")
sys.path.insert(0, str(ROOT / "scripts"))
migration = load("decor_publish_time_migration", "scripts/migrate_publish_times.py")

BEIJING = timezone(timedelta(hours=8))


class PublishTimeTests(unittest.TestCase):
    def test_server_reads_text_without_offset_as_beijing_time(self):
        self.assertEqual(server.parse_published_at("2026-11-04 16:54:54"), datetime(2026, 11, 4, 16, 54, 54, tzinfo=BEIJING))
        self.assertEqual(server.parse_published_at("2026-11-04"), datetime(2026, 11, 4, tzinfo=BEIJING))
        self.assertEqual(server.parse_published_at("2026-11-07T08:16:28+00:00"),
                         datetime(2026, 11, 7, 8, 16, 28, tzinfo=timezone.utc))
        # A Beijing afternoon post now sorts after a UTC morning post from the same instant range.
        self.assertLess(server.parse_published_at("2026-11-07 15:00:00"), server.parse_published_at("2026-11-07T08:16:28+00:00"))
        self.assertIsNone(server.parse_published_at(""))

    def test_collector_keeps_the_offset_whatever_the_machine_zone(self):
        stamp = int(datetime(2026, 11, 4, 8, 54, 54, tzinfo=timezone.utc).timestamp())
        item = collector.recursive_find_video_objects({"aweme_id": "7600000000000000001", "desc": "v", "create_time": stamp})[0]
        self.assertEqual(item["published_at"], "2026-11-04T08:54:54+00:00")
        self.assertEqual(server.parse_published_at(item["published_at"]).timestamp(), stamp)

    def test_migration_only_targets_text_without_offset(self):
        pattern = re.compile(migration.NAIVE_TIME)
        for text in ("2026-11-04 16:54:54", "2026-11-04 16:54", "2026-11-04"):
            self.assertTrue(pattern.search(text), text)
        for text in ("2026-11-07T08:16:28+00:00", "2026-11-07T08:16:28Z", "未提及", ""):
            self.assertFalse(pattern.search(text), text)


if __name__ == "__main__":
    unittest.main()
