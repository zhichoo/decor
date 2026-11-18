"""Read-only exclusion provenance, including current-input and private-field boundaries."""
import hashlib
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import claim_exclusions
import test_pipeline_safety as pipeline


class ExclusionProjectionTests(unittest.TestCase):
    def test_optional_fields_keep_their_own_action_and_plain_language_reason(self):
        item = {"reason": "unsupported_optional_field", "object_name": "小砖", "private": "not-public",
                "issues": [{"type": "evidence", "field": "price_info", "quote": "小砖工费高",
                            "reason": "unsupported_field_numeric_detail:price_info", "details": "private-validator-details"}]}
        result = claim_exclusions.project_item(item, "原文：小砖工费高。")
        self.assertEqual(result, {"object": "小砖", "action": "字段省略", "quotes": ["小砖工费高"],
                                  "reasons": ["价格信息：数值缺少原文依据"]})
        self.assertNotIn("private", json.dumps(result))

    def test_legacy_quotes_must_exist_in_current_transcript_and_do_not_expose_proposed_claim(self):
        item = {"reason": "ambiguous_content", "claim": {"object_name": "衣柜", "original_conclusion": "模型猜测",
                "source_quotes": ["原句", "编造引句"]}, "issues": [{"type": "scope", "quote": "原句", "reason": "指代不清"}]}
        result = claim_exclusions.project_item(item, "这是原句。")
        self.assertEqual(result["quotes"], ["原句"])
        self.assertEqual(result["action"], "未收录")
        self.assertEqual(result["reasons"], ["指代不清"])
        self.assertNotIn("模型猜测", json.dumps(result, ensure_ascii=False))


class ExclusionDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(pipeline.PipelineSafetyTests.setUpClass.__func__)
    tearDownClass = classmethod(pipeline.PipelineSafetyTests.tearDownClass.__func__)
    setUp = pipeline.PipelineSafetyTests.setUp

    def test_only_current_unsuperseded_items_match_list_count_without_writes(self):
        digest = hashlib.sha256(self.old_text.encode()).hexdigest()
        quote = "装修验收时检查每个插座的接线是否安全。"
        item = {"status": "excluded", "reason": "ambiguous_content", "object_name": "插座",
                "issues": [{"type": "scope", "quote": quote, "reason": "范围不清"}]}
        optional = {**item, "reason": "unsupported_optional_field"}
        with self.server.connect() as conn:
            for run_id, input_hash, superseded, items in (
                ("current", digest, False, [item, optional, {**item, "status": "approved"}]),
                ("legacy-pending", digest, False, [{**item, "status": "pending"}]),
                ("superseded", digest, True, [item]),
                ("old-transcript", "old-hash", False, [item]),
            ):
                conn.execute("""INSERT INTO extraction_runs
                    (id,video_id,model,prompt_version,input_hash,prompt_text,status,created_at,review_data)
                    VALUES (%s,%s,'test','test',%s,'private-prompt','completed',1,%s)""",
                    (run_id, self.video_id, input_hash, self.server.Json({"superseded": superseded, "items": items})))
            count = conn.execute(f"SELECT {self.server.excluded_claim_count_sql()} AS n FROM videos v WHERE id=%s",
                                 (self.video_id,)).fetchone()["n"]
            before = conn.execute("SELECT row_to_json(v)::text AS data FROM videos v WHERE id=%s", (self.video_id,)).fetchone()
        with self.server.connect() as conn:
            result = claim_exclusions.fetch_records(conn, self.video_id)
        self.assertEqual(result["total"], count)
        self.assertEqual(result["total"], 3)
        self.assertEqual([row["action"] for row in result["items"]].count("字段省略"), 1)
        self.assertNotIn("private-prompt", json.dumps(result))
        with self.server.connect() as conn:
            self.assertEqual(conn.execute("SELECT row_to_json(v)::text AS data FROM videos v WHERE id=%s", (self.video_id,)).fetchone(), before)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM claims").fetchone()["n"], 1)

    def test_missing_and_deleted_videos_do_not_expose_items(self):
        with self.server.connect() as conn:
            self.assertIsNone(claim_exclusions.fetch_records(conn, "not-found"))
        with self.server.connect() as conn:
            conn.execute("UPDATE videos SET deleted_at=100 WHERE id=%s", (self.video_id,))
        with self.server.connect() as conn:
            self.assertIsNone(claim_exclusions.fetch_records(conn, self.video_id))


if __name__ == "__main__":
    unittest.main()
