"""Saved trials apply transactionally without another model request."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

import test_pipeline_safety as pipeline

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import apply_claim_upgrade as apply


class ApplyClaimUpgradeTests(unittest.TestCase):
    setUpClass = classmethod(pipeline.PipelineSafetyTests.setUpClass.__func__)
    tearDownClass = classmethod(pipeline.PipelineSafetyTests.tearDownClass.__func__)
    setUp = pipeline.PipelineSafetyTests.setUp
    video = pipeline.PipelineSafetyTests.video
    claims = pipeline.PipelineSafetyTests.claims
    active = pipeline.PipelineSafetyTests.active
    claim = pipeline.PipelineSafetyTests.claim
    result = pipeline.PipelineSafetyTests.result

    def sample(self):
        with self.server.connect() as conn:
            conn.execute("UPDATE videos SET ad_review=%s WHERE id=%s", (
                self.server.Json({"decision": "not_ad", "version": self.server.advertising.VERSION,
                                  "input_hash": self.server.advertising.input_hash(self.video())}),
                self.video_id))
            snapshot = {"videos": [dict(conn.execute("SELECT * FROM videos WHERE id=%s", (self.video_id,)).fetchone())],
                        "claims": [dict(c) for c in conn.execute("SELECT * FROM claims ORDER BY id").fetchall()]}
        video = self.server.row_to_video(snapshot["videos"][0])
        prompt = self.server.build_extract_prompt(video)
        saved = {"video_id": self.video_id, "status": "completed", "prompt_version": self.server.PROMPT_VERSION,
                 "model": self.server.active_model_name(), "input_hash": apply.upgrade.text_hash(self.old_text),
                 "fingerprint": apply.upgrade.digest([self.server.PROMPT_VERSION, self.server.active_model_name(), prompt]),
                 "raw_response": self.result([self.claim("验收时检查插座接线。")]), "created_at": 100}
        return saved, snapshot

    def run_sample(self, saved, snapshot, execute=False):
        with patch.object(self.server, "call_deepseek") as model, self.server.connect() as conn:
            result = apply.apply_sample(conn, self.server, saved, snapshot, execute=execute)
        model.assert_not_called()
        return result

    def test_dry_run_preserves_cards_and_runs(self):
        saved, snapshot = self.sample()
        result = self.run_sample(saved, snapshot)
        self.assertEqual(result["status"], "ready")
        self.assertEqual([c["id"] for c in self.active()], ["old"])
        with self.server.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM extraction_runs").fetchone()["n"], 0)

    def test_apply_and_idempotent_rerun(self):
        saved, snapshot = self.sample()
        result = self.run_sample(saved, snapshot, True)
        self.assertEqual(result["new_claims"], 1)
        self.assertNotEqual(self.active()[0]["id"], "old")
        self.assertEqual(self.run_sample(saved, snapshot, True)["status"], "skipped_current")
        with self.server.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM extraction_runs").fetchone()["n"], 1)

    def test_failed_response_rolls_back_without_overwriting_old(self):
        saved, snapshot = self.sample()
        saved["raw_response"] = '{}'
        with self.assertRaises(ValueError):
            self.run_sample(saved, snapshot, True)
        self.assertEqual([c["id"] for c in self.active()], ["old"])

    def test_input_change_and_manual_deletion_are_rejected(self):
        for change in ("UPDATE videos SET transcript_text='changed'", "UPDATE claims SET deleted_at=88,deleted_by='admin'"):
            self.setUp()
            saved, snapshot = self.sample()
            with self.server.connect() as conn:
                conn.execute(change)
            with self.assertRaisesRegex(ValueError, "sample_input_changed|manual_deletion_guard"):
                self.run_sample(saved, snapshot, True)

    def test_updated_card_is_not_overwritten_from_stale_snapshot(self):
        saved, snapshot = self.sample()
        with self.server.connect() as conn:
            conn.execute("UPDATE claims SET original_conclusion='edited'")
        with self.assertRaisesRegex(ValueError, "sample_old_cards_changed"):
            self.run_sample(saved, snapshot, True)

    def test_advertising_or_unknown_cannot_be_applied_as_regular_upgrade(self):
        saved, snapshot = self.sample()
        with self.server.connect() as conn:
            conn.execute("UPDATE videos SET ad_review=NULL")
        with self.assertRaisesRegex(ValueError, "sample_advertising_or_unresolved"):
            self.run_sample(saved, snapshot, True)

    def test_insert_failure_rolls_back_run_and_card_soft_deletion(self):
        saved, snapshot = self.sample()
        with patch.object(self.server, "insert_claims", side_effect=ValueError("write_failed")):
            with self.assertRaisesRegex(ValueError, "write_failed"):
                self.run_sample(saved, snapshot, True)
        self.assertEqual([c["id"] for c in self.active()], ["old"])
        with self.server.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM extraction_runs").fetchone()["n"], 0)


if __name__ == "__main__":
    unittest.main()
