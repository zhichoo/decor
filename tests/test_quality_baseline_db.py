"""Baseline integration tests against disposable PostgreSQL, never the configured database."""
import json
import unittest

import test_pipeline_safety as pipeline
import test_quality_baseline as offline


class QualityBaselineDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(pipeline.PipelineSafetyTests.setUpClass.__func__)
    tearDownClass = classmethod(pipeline.PipelineSafetyTests.tearDownClass.__func__)
    setUp = pipeline.PipelineSafetyTests.setUp

    def signature(self):
        with self.server.connect() as conn:
            return {table: json.dumps(conn.execute("SELECT * FROM " + table + " ORDER BY id").fetchall(),
                                      sort_keys=True, default=str)
                    for table in ("sources", "videos", "claims", "extraction_runs")}

    def test_real_export_freezes_legacy_fields_without_business_data_writes(self):
        before = self.signature()
        raw = offline.quality.read_database(self.dsn)
        frozen = offline.quality.freeze(raw)
        offline.quality.validate_dataset(frozen)
        labels = offline.quality.annotation_template(frozen)
        result = offline.quality.report(frozen, labels)
        self.assertEqual(frozen["sampling"]["selected"], {"random": 1, "challenge": 1, "whole_video": 1})
        self.assertIsNone(result["groups"]["random"]["failed_units"]["rate"])
        self.assertEqual(frozen["snapshot"]["claims"][0]["source_quotes"], [])
        self.assertEqual(before, self.signature())

    def test_deleted_claims_and_videos_are_excluded_from_real_queries(self):
        with self.server.connect() as conn:
            conn.execute("UPDATE claims SET deleted_at=100 WHERE id='old'")
        raw = offline.quality.read_database(self.dsn)
        self.assertEqual(len(raw["videos"]), 1)
        self.assertEqual(raw["claims"], [])
        with self.server.connect() as conn:
            conn.execute("UPDATE claims SET deleted_at=NULL WHERE id='old'")
            conn.execute("UPDATE videos SET deleted_at=100 WHERE id=%s", (self.video_id,))
        raw = offline.quality.read_database(self.dsn)
        self.assertEqual(raw, {"videos": [], "claims": [], "runs": []})


if __name__ == "__main__":
    unittest.main()
