"""Content classification must never replace cards, restore deletions or lose edits."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from psycopg2.errors import CheckViolation

import test_pipeline_safety as pipeline

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_content_types as backfill

TYPES = ("选购建议", "施工做法", "验收要求", "价格信息", "个人体验", "中性说明", "其他")


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.cards = [{"id": "one", "video_id": "v1", "object_name": "插座",
                       "original_conclusion": "验收时检查插座接线", "content_type": None, "deleted_at": None}]

    def payload(self, category="验收要求"):
        return {"items": [{"id": "one", "content_type": category, "reason": "明确验收检查要求"}]}

    def test_valid_and_unresolved_are_separate(self):
        self.assertEqual(backfill.validate_result(self.payload(), self.cards, TYPES)[0]["content_type"], "验收要求")
        self.assertIsNone(backfill.validate_result(self.payload(None), self.cards, TYPES)[0]["content_type"])
        with self.assertRaisesRegex(ValueError, "invalid_content_type"):
            backfill.validate_result(self.payload("未分类"), self.cards, TYPES)

    def test_missing_duplicate_unknown_and_extra_fields_are_rejected(self):
        cases = [
            {"items": []}, {"items": self.payload()["items"] * 2},
            {"items": [{**self.payload()["items"][0], "id": "unknown"}]},
            {"items": [{**self.payload()["items"][0], "original_conclusion": "改写"}]},
            {"items": [{**self.payload()["items"][0], "content_type": []}]},
        ]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                backfill.validate_result(payload, self.cards, TYPES)

    def test_preparation_skips_deleted_and_already_classified(self):
        snapshot = {"sources": [], "extraction_runs": [],
                    "videos": [{"id": "v1"}, {"id": "gone", "deleted_at": 1}],
                    "claims": self.cards + [
                        {**self.cards[0], "id": "classified", "content_type": "施工做法"},
                        {**self.cards[0], "id": "deleted", "deleted_at": 1},
                        {**self.cards[0], "id": "deleted-video", "video_id": "gone"}]}
        self.assertEqual([row["id"] for row in backfill.eligible_cards(snapshot)], ["one"])

    def test_abstention_withholds_only_the_label_and_preserves_model_result(self):
        items = self.payload()["items"]
        self.assertIsNone(backfill.abstain_items(items, {"one": "主旨不足以确定"})[0]["content_type"])
        self.assertEqual(items[0]["content_type"], "验收要求")
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            backfill.save_json(folder / "abstentions.private.json", [{"id": "unplanned", "reason": "不确定"}])
            with self.assertRaisesRegex(ValueError, "invalid_abstention_entry"):
                backfill.load_abstentions(folder, {"batches": [{"ids": ["one"]}]})

    def test_failed_or_interrupted_requests_are_never_silently_resubmitted(self):
        snapshot = {"sources": [], "extraction_runs": [], "videos": [{"id": "v1"}], "claims": self.cards}
        for interrupt in (False, True):
            with self.subTest(interrupt=interrupt), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory) / "run"
                with patch.object(backfill, "read_database", return_value=snapshot):
                    backfill.prepare(folder, "unused")
                model = Mock(side_effect=RuntimeError("interrupted")) if interrupt else Mock(return_value=(None, "http_503"))
                server = SimpleNamespace(active_model_name=lambda: "test", call_deepseek=model, CONTENT_TYPES=TYPES)
                if interrupt:
                    with self.assertRaisesRegex(RuntimeError, "interrupted"):
                        backfill.classify(folder, server, "sample")
                else:
                    backfill.classify(folder, server, "sample")
                backfill.classify(folder, server, "sample")
                self.assertEqual(model.call_count, 1)
                state = json.loads((folder / "batches/sample-001.private.json").read_text())
                self.assertEqual(state["status"], "request_started" if interrupt else "model_failed")


class ClassificationDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(pipeline.PipelineSafetyTests.setUpClass.__func__)
    tearDownClass = classmethod(pipeline.PipelineSafetyTests.tearDownClass.__func__)
    setUp = pipeline.PipelineSafetyTests.setUp

    def cards(self):
        with self.server.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM claims ORDER BY id").fetchall()]

    def apply(self, expected, items, execute=True):
        with self.server.connect() as conn, conn.transaction():
            return backfill.apply_batch(conn, expected, items, execute)

    def item(self, category="验收要求", key="old"):
        return {"id": key, "content_type": category, "reason": "明确检查要求"}

    def test_dry_run_and_apply_change_only_type_without_new_rows_or_runs(self):
        before = self.cards()
        self.assertEqual(self.apply(before, [self.item()], False)[0]["status"], "ready")
        self.assertEqual(self.cards(), before)
        self.assertEqual(self.apply(before, [self.item()])[0]["status"], "updated")
        expected = [{**before[0], "content_type": "验收要求"}]
        self.assertEqual(self.cards(), expected)
        self.assertEqual(self.apply(before, [self.item()])[0]["status"], "skipped_already_classified")
        self.assertEqual(self.cards(), expected)
        with self.server.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM extraction_runs").fetchone()["n"], 0)

    def test_deleted_cards_and_videos_are_never_changed(self):
        for statement in ("UPDATE claims SET deleted_at=88, deleted_by='admin'", "UPDATE videos SET deleted_at=88"):
            with self.subTest(statement=statement):
                self.setUp()
                before = self.cards()
                with self.server.connect() as conn:
                    conn.execute(statement)
                guarded = self.cards()
                self.assertEqual(self.apply(before, [self.item()])[0]["status"], "skipped_deleted_or_missing")
                self.assertEqual(self.cards(), guarded)

    def test_concurrent_edits_and_existing_types_are_preserved(self):
        for statement, status in (
            ("UPDATE claims SET original_conclusion='管理员已修改'", "skipped_changed_card"),
            ("UPDATE claims SET content_type='其他'", "skipped_already_classified"),
        ):
            with self.subTest(statement=statement):
                self.setUp()
                before = self.cards()
                with self.server.connect() as conn:
                    conn.execute(statement)
                guarded = self.cards()
                self.assertEqual(self.apply(before, [self.item()])[0]["status"], status)
                self.assertEqual(self.cards(), guarded)

    def test_unresolved_does_not_turn_into_other(self):
        before = self.cards()
        self.assertEqual(self.apply(before, [self.item(None)])[0]["status"], "unresolved")
        self.assertEqual(self.cards(), before)

    def test_partial_batch_write_is_rolled_back_on_database_failure(self):
        with self.server.connect() as conn:
            conn.execute("""INSERT INTO claims (id,video_id,object_name,stance,process_stage,space_tags,topic_tags,
                original_conclusion,original_reasons,conditions,alternatives,price_info,source_video_url,created_at)
                SELECT 'second',video_id,object_name,stance,process_stage,space_tags,topic_tags,
                original_conclusion,original_reasons,conditions,alternatives,price_info,source_video_url,created_at
                FROM claims WHERE id='old'""")
            conn.execute("ALTER TABLE claims ADD CONSTRAINT classification_test_failure "
                         "CHECK (id <> 'second' OR content_type IS NULL)")
        try:
            before = self.cards()
            with self.assertRaises(CheckViolation):
                self.apply(before, [self.item(), self.item(key="second")])
            self.assertEqual(self.cards(), before)
        finally:
            with self.server.connect() as conn:
                conn.execute("ALTER TABLE claims DROP CONSTRAINT classification_test_failure")


if __name__ == "__main__":
    unittest.main()
