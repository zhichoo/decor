"""Read-only maintenance metrics; fixture schemas roll back without business data writes."""
from datetime import datetime, timezone
import hashlib
import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import advertising
import source_performance as performance
import test_video_facets as facets


def video(**values):
    return {"id": "v", "title": "Test", "transcript_text": "真实文案", "status": "claims_extracted",
            "published_at_ts": datetime(2026, 11, 1, tzinfo=timezone.utc), **values}


def run(**values):
    return {"id": "r", "video_id": "v", "input_hash": hashlib.sha256("真实文案".encode()).hexdigest(),
            "prompt_version": "current", "created_at": 1, "status": "completed", **values}


class SourcePerformanceTests(unittest.TestCase):
    def summarize(self, v=None, claims=(), runs=()):
        return performance.summarize_video(v or video(), claims, runs, "current")

    def test_trashed_video_occupies_sample_and_counts_only_retained_active_cards(self):
        item = self.summarize(video(deleted_at=1), [{"extraction_run_id": "r"}], [run()])
        self.assertTrue(item["deleted"])
        self.assertEqual(item["retained_cards"], 1)
        item = self.summarize(video(deleted_at=1), [{"extraction_run_id": "r", "deleted_at": 1}], [run()])
        self.assertEqual(item["retained_cards"], 0)

    def test_replacement_and_user_deletion_are_not_quality_rejections(self):
        cards = [{"deleted_at": 1, "deleted_by": who, "delete_reason": reason} for who, reason in (
            ("system", "replace_extracted_claims"), ("admin", "参数不清"),
            ("system", "incremental_quality_cleanup: 参数不清"))]
        item = self.summarize(claims=cards)
        self.assertEqual(item["deletions"], {"replacement": 1, "other": 1, "quality_cleanup": 1})
        self.assertEqual(item["cleanup_reasons"], {"parameter": 1})

    def test_current_legacy_stale_and_untracked_cards_are_separate(self):
        runs = [run(), run(id="old", prompt_version="old"), run(id="stale", input_hash="changed")]
        item = self.summarize(claims=[{"extraction_run_id": key} for key in ("r", "old", "stale", None)], runs=runs)
        self.assertEqual(item["card_versions"], {"current": 1, "legacy": 1, "stale": 1, "untracked": 1})

    def test_newer_different_transcript_run_does_not_hide_matching_run(self):
        item = self.summarize(runs=[run(), run(id="new", created_at=20, input_hash="different", status="parse_failed")])
        self.assertEqual(item["outcome"], "completed")
        stale = self.summarize(runs=[run(input_hash="different")])
        self.assertEqual(stale["outcome"], "stale")
        self.assertFalse(stale["technical_issue"])

    def test_technical_failures_do_not_become_empty_content(self):
        for status, expected in (("parse_failed", "format_failed"), ("quality_check_failed", "format_failed"),
                                 ("deepseek_http_503: private-key", "model_failed"),
                                 ("insert_failed", "storage_failed"), ("request_started", "in_progress")):
            with self.subTest(status=status):
                item = self.summarize(runs=[run(status=status)])
                self.assertEqual(item["outcome"], expected)
                self.assertTrue(item["technical_issue"])
                self.assertNotIn("private-key", json.dumps(item))
        self.assertEqual(self.summarize(video(status="transcript_failed"))["outcome"], "asr_failed")

    def test_existing_classification_is_validated_and_manual_override_preserved(self):
        v = video()
        v["ad_review"] = {"decision": "advertising", "version": advertising.VERSION,
                          "input_hash": advertising.input_hash(v), "reason": "private explanation"}
        self.assertEqual(self.summarize(v)["content"], "advertising")
        v["transcript_text"] = "changed"
        self.assertEqual(self.summarize(v)["content"], "unknown")
        v["ad_review_override"] = {"decision": "not_ad"}
        item = self.summarize(v)
        self.assertEqual((item["content"], item["decision_source"]), ("not_ad", "manual"))
        self.assertNotIn("private explanation", json.dumps(item))

    def test_optional_field_pruning_is_not_whole_card_exclusion(self):
        item = self.summarize(runs=[run(review_data={"items": [
            {"reason": "unsupported_optional_field"},
            {"reason": "ambiguous_content", "issues": [{"type": "parameter", "reason": "private"}]},
        ]})])
        self.assertEqual(item["exclusions"], {"parameter": 1})
        self.assertEqual(item["optional_omissions"], 1)
        superseded = self.summarize(runs=[run(review_data={"items": [{"reason": "thin"}], "superseded": True})])
        self.assertEqual(superseded["exclusions"], {})

    def test_legacy_filtered_video_has_completed_run_but_counts_as_filtered(self):
        item = self.summarize(video(status="claims_filtered"), runs=[run(prompt_version="old")])
        self.assertEqual((item["outcome"], item["run_version"]), ("filtered", "legacy"))

    def test_filtered_reason_uses_safe_category_not_raw_processing_errors(self):
        item = self.summarize(video(status="claims_filtered", last_error="无有效内容：识别错误严重"), runs=[run()])
        self.assertEqual(item["filtered_reason"], "文案不清")
        item = self.summarize(video(status="claims_filtered", last_error="private-key"), runs=[run()])
        self.assertIsNone(item["filtered_reason"])
        self.assertNotIn("private-key", json.dumps(item))
        item = self.summarize(video(status="claims_filtered", last_error="无有效内容：只有品牌型号或单品价格"), runs=[run()])
        self.assertEqual(item["filtered_reason"], "推广关联")

    def test_source_is_keyed_by_id_and_technical_count_deduplicates(self):
        v = video(ad_review_override={"decision": "error"}, status="transcript_failed")
        # Error is a cached automatic result, not an allowed manual override.
        v["ad_review"] = {"decision": "error", "version": advertising.VERSION, "input_hash": advertising.input_hash(v)}
        result = performance.summarize_source("source-id", [v], [], [], "current")
        self.assertEqual((result["source_id"], result["sample_count"], result["technical_videos"]), ("source-id", 1, 1))
        self.assertEqual(result["content_counts"]["error"], 1)
        empty = performance.summarize_source("empty", [], [], [], "current")
        self.assertEqual((empty["sample_count"], empty["retained_cards"]), (0, 0))


class SourcePerformanceDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(facets.VideoFacetsTests.setUpClass.__func__)
    setUp = facets.VideoFacetsTests.setUp
    add_video = facets.VideoFacetsTests.add_video
    add_claim = facets.VideoFacetsTests.add_claim

    def seed(self):
        for source_id in ("source", "empty"):
            self.conn.execute("""INSERT INTO sources (id, platform, name, created_at)
                VALUES (%s, 'douyin', 'Same display name', 1)""", (source_id,))
        for index in range(11):
            self.add_video(f"v{index:02}", "douyin", "Same display name", "source", created_at=index + 1,
                           deleted_at=1 if index == 10 else None)
        self.add_claim("active", "v09")
        self.add_claim("retained-on-trashed-video", "v10")

    def test_rank_keeps_tombstone_and_excludes_eleventh_record_without_name_grouping(self):
        original = self.conn.execute
        statements = []

        def execute(statement, params=None):
            statements.append(statement)
            # Test fixtures already live in an outer rollback-only transaction.
            if statement.startswith("SET TRANSACTION"):
                return None
            return original(statement, params)

        self.conn.execute = execute
        result = performance.fetch_performance(self.conn, "current")
        by_id = {item["source_id"]: item for item in result["sources"]}
        sample = by_id["source"]
        self.assertEqual([v["id"] for v in sample["videos"]], [f"v{i:02}" for i in range(10, 0, -1)])
        self.assertEqual((sample["sample_count"], sample["deleted_videos"], sample["retained_cards"]), (10, 1, 2))
        self.assertEqual(by_id["empty"]["sample_count"], 0)
        self.assertEqual(len(statements), 5)
        text = json.dumps(result)
        for private in ("transcript_text", "raw_response", "prompt_text", "error_message", "delete_reason"):
            self.assertNotIn(private, text)

    def test_public_sources_and_bootstrap_have_no_private_metrics(self):
        sources = self.server.fetch_sources(self.conn)
        bootstrap = self.server.build_bootstrap_payload(self.conn)
        for payload in (sources, bootstrap):
            text = json.dumps(payload)
            for private in ("source_performance", "card_versions", "quality_cleanup", "technical_videos"):
                self.assertNotIn(private, text)

    def test_publication_order_wins_over_import_time_and_unknown_dates_sort_last(self):
        self.conn.execute("UPDATE videos SET published_at_ts='2026-01-01' WHERE id='v00'")
        original = self.conn.execute
        self.conn.execute = lambda statement, params=None: None if statement.startswith("SET TRANSACTION") else original(statement, params)
        sample = next(item for item in performance.fetch_performance(self.conn, "current")["sources"]
                      if item["source_id"] == "source")
        self.assertEqual(sample["videos"][0]["id"], "v00")
        self.assertEqual(sample["undated_videos"], 9)


if __name__ == "__main__":
    unittest.main()
