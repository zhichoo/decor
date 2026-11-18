"""Offline quality baselines: reproducibility, private snapshots, and honest denominators."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("decor_quality_baseline", ROOT / "scripts/quality_baseline.py")
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)
STAMP = "2026-10-29T10:00:00+08:00"


def fixture():
    videos = [
        {"id": "v1", "title": "Example one", "creator": "A", "platform": "test",
         "transcript_text": "Keep the original scope. Price is 200元. 不推荐这样做。",
         "source_url": "https://example.invalid/v1?token=private-token#secret", "deleted_at": None,
         "transcript_job": {"password": "private-job"},
         "ad_review_override": {"decision": "not_ad", "reason": "private-review-note"}},
        {"id": "v2", "title": "Example two", "creator": "B", "platform": "test",
         "transcript_text": "Another statement. 防水高度三的公分。", "deleted_at": None},
        {"id": "empty", "title": "Empty", "transcript_text": "", "deleted_at": None},
        {"id": "placeholder", "title": "Placeholder", "transcript_text": "Placeholder"},
        {"id": "deleted-video", "title": "Deleted", "deleted_at": 1},
    ]
    claims = [
        {"id": "c1", "video_id": "v1", "extraction_run_id": "r1", "object_name": "Scope",
         "original_conclusion": "Keep the original scope.", "source_quotes": ["Keep the original scope."]},
        {"id": "c2", "video_id": "v1", "extraction_run_id": "r1", "object_name": "Price",
         "original_conclusion": "Price is 200元.", "source_quotes": ["Price is 200元."]},
        {"id": "c3", "video_id": "v2", "object_name": "Legacy", "source_quotes": None},
        {"id": "c4", "video_id": "v1", "object_name": "Bad quote", "source_quotes": ["Invented quotation."]},
        {"id": "c5", "video_id": "v2", "object_name": "ASR", "source_quotes": ["防水高度三的公分。"]},
        {"id": "deleted-claim", "video_id": "v1", "deleted_at": 1},
        {"id": "claim-on-deleted-video", "video_id": "deleted-video"},
    ]
    runs = [{"id": "r1", "video_id": "v1", "model": "example-model", "prompt_version": "example-v1",
             "input_hash": "example-input-hash", "raw_response_json": "private-response", "prompt_text": "private-prompt"}]
    return {"videos": videos, "claims": claims, "runs": runs, "DATABASE_URL": "private-dsn"}


def dataset(**kwargs):
    return quality.freeze(fixture(), created_at=STAMP, **kwargs)


def finish(entry, verdict="pass", method="transcript"):
    entry.update(verdict=verdict, review_method=method, reviewer="test-admin",
                 reviewed_at=STAMP, review_seconds=12)
    return entry


def error(kind="scope", severity="moderate", evidence="Keep the original scope.", source="transcript"):
    return {"type": kind, "severity": severity, "evidence": evidence,
            "evidence_source": source, "note": "Test annotation, not a real factual judgment."}


def reference(disposition, matched=None, text="Keep the original scope."):
    return {"text": text, "evidence": "Keep the original scope.", "evidence_source": "transcript",
            "disposition": disposition, "matched_claim_ids": matched or [], "reason": "Test reference."}


def entry_for(labels, key):
    return next(e for e in labels["entries"] if e["sample_id"] == key)


class SamplingTests(unittest.TestCase):
    def test_sampling_reproduces_when_input_order_changes(self):
        raw = fixture()
        first = quality.freeze(raw, random_count=3, challenge_count=2, video_count=1, created_at=STAMP)
        for rows in (raw["videos"], raw["claims"], raw["runs"]):
            rows.reverse()
        second = quality.freeze(raw, random_count=3, challenge_count=2, video_count=1, created_at=STAMP)
        self.assertEqual(first, second)
        quality.validate_dataset(first)

    def test_seed_changes_ordering_without_modifying_input(self):
        raw = fixture()
        before = deepcopy(raw)
        first = quality.freeze(raw, seed=1, random_count=3, challenge_count=0, video_count=0)
        second = quality.freeze(raw, seed=2, random_count=3, challenge_count=0, video_count=0)
        self.assertNotEqual(first["samples"], second["samples"])
        self.assertEqual(raw, before)

    def test_underfilled_groups_overlap_and_deleted_records(self):
        frozen = dataset()
        self.assertEqual(frozen["sampling"]["selected"], {"random": 5, "challenge": 4, "whole_video": 2})
        self.assertEqual(len(frozen["samples"]), 7)
        self.assertTrue(any(s["groups"] == ["random", "challenge"] for s in frozen["samples"]))
        self.assertNotIn("deleted-video", {v["id"] for v in frozen["snapshot"]["videos"]})
        self.assertEqual({c["id"] for c in frozen["snapshot"]["claims"]}, {"c1", "c2", "c3", "c4", "c5"})

    def test_snapshot_allowlist_drops_secrets_and_url_tokens(self):
        text = json.dumps(dataset(), ensure_ascii=False)
        for secret in ("private-token", "private-dsn", "private-response", "private-prompt", "private-review-note", "private-job"):
            self.assertNotIn(secret, text)
        self.assertIn("https://example.invalid/v1", text)
        self.assertEqual(quality.source_url("https://user:password@example.invalid/a"), "")
        self.assertEqual(quality.source_url("javascript:alert(1)"), "")

    def test_legacy_fields_and_absent_run_metadata_stay_missing(self):
        raw = fixture()
        raw["runs"] = []
        frozen = quality.freeze(raw)
        legacy = next(c for c in frozen["snapshot"]["claims"] if c["id"] == "c3")
        self.assertEqual(legacy["source_quotes"], [])
        self.assertIsNone(legacy["author_stance"])
        self.assertEqual(frozen["snapshot"]["runs"], [])

    def test_missing_and_invalid_quotes_are_risk_hints_not_findings(self):
        signals = dataset()["sampling"]["risk_signals"]
        self.assertEqual(signals["c1"], [])
        self.assertIn("numeric", signals["c2"])
        self.assertIn("missing_quotes", signals["c3"])
        self.assertIn("quote_mismatch", signals["c4"])
        self.assertIn("rule_parameter", signals["c5"])

    def test_old_datasets_do_not_replay_new_risk_heuristics(self):
        frozen = dataset()
        with patch.object(quality, "risk_signals", side_effect=AssertionError("must use frozen signals")):
            quality.validate_dataset(frozen)
            quality.annotation_template(frozen)

    def test_empty_snapshot_and_zero_samples(self):
        frozen = quality.freeze({"videos": [], "claims": []})
        self.assertEqual(frozen["samples"], [])
        quality.validate_dataset(frozen)
        self.assertEqual(dataset(random_count=0, challenge_count=0, video_count=0)["samples"], [])

    def test_duplicate_ids_or_orphans_are_rejected(self):
        for category in ("videos", "claims", "runs"):
            raw = fixture()
            raw[category].append(deepcopy(raw[category][0]))
            with self.subTest(category=category), self.assertRaisesRegex(ValueError, "duplicate"):
                quality.freeze(raw)
        raw = fixture()
        raw["claims"][0]["video_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "missing video"):
            quality.freeze(raw)

    def test_invalid_counts_and_array_types_are_rejected(self):
        for value in (-1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                dataset(random_count=value)
        raw = fixture()
        raw["claims"][0]["source_quotes"] = "not an array"
        with self.assertRaisesRegex(ValueError, "source_quotes"):
            quality.freeze(raw)

    def test_run_must_correspond_to_claim_video(self):
        raw = fixture()
        raw["runs"][0]["video_id"] = "v2"
        with self.assertRaisesRegex(ValueError, "mismatch"):
            quality.freeze(raw)

    def test_tampered_snapshot_or_sampling_is_rejected(self):
        frozen = dataset()
        frozen["snapshot"]["claims"][0]["conditions"] = "changed"
        with self.assertRaisesRegex(ValueError, "integrity"):
            quality.validate_dataset(frozen)
        frozen = dataset()
        frozen["samples"].pop()
        frozen["dataset_id"] = quality.digest({k: v for k, v in frozen.items() if k != "dataset_id"})
        with self.assertRaisesRegex(ValueError, "sampling"):
            quality.validate_dataset(frozen)


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.dataset = dataset()
        self.labels = quality.annotation_template(self.dataset)

    def validate(self):
        return quality.validate_annotations(self.dataset, self.labels)

    def test_template_is_pending_only_and_valid(self):
        self.validate()
        self.assertTrue(all(e["verdict"] == "pending" for e in self.labels["entries"]))

    def test_multilabel_error_and_valid_pass(self):
        entry = finish(entry_for(self.labels, "claim:c1"), "fail")
        entry["errors"] = [error(), error("attitude", "severe")]
        finish(entry_for(self.labels, "claim:c2"))
        self.validate()

    def test_pending_unable_and_pass_are_not_interchangeable(self):
        entry = entry_for(self.labels, "claim:c1")
        entry["errors"] = [error()]
        with self.assertRaisesRegex(ValueError, "pending"):
            self.validate()
        entry["errors"] = []
        finish(entry, "unable", "unavailable")
        with self.assertRaisesRegex(ValueError, "reason"):
            self.validate()
        entry["notes"] = "Original video inaccessible; no reliable judgment."
        self.validate()
        entry["verdict"] = "pass"
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.validate()

    def test_no_pass_with_errors_or_fail_without_errors(self):
        entry = finish(entry_for(self.labels, "claim:c1"))
        entry["errors"] = [error()]
        with self.assertRaisesRegex(ValueError, "contradicts"):
            self.validate()
        entry["errors"] = []
        entry["verdict"] = "fail"
        with self.assertRaisesRegex(ValueError, "contradicts"):
            self.validate()

    def test_exact_quote_or_original_video_review_required(self):
        entry = finish(entry_for(self.labels, "claim:c1"), "fail")
        entry["errors"] = [error(evidence="Paraphrased unsupported quote")]
        with self.assertRaisesRegex(ValueError, "exact"):
            self.validate()
        entry["errors"][0]["evidence_source"] = "original_video"
        with self.assertRaisesRegex(ValueError, "video review"):
            self.validate()
        entry["review_method"] = "original_video"
        self.validate()

    def test_claim_text_can_evidence_an_invented_quote(self):
        entry = finish(entry_for(self.labels, "claim:c4"), "fail")
        entry["errors"] = [error("evidence", evidence="Invented quotation.", source="claim")]
        self.validate()

    def test_duplicate_error_or_unknown_enum_rejected(self):
        entry = finish(entry_for(self.labels, "claim:c1"), "fail")
        for errors in ([error(), error()], [error("typo-category")], [error(severity="critical-typo")]):
            entry["errors"] = errors
            with self.subTest(errors=errors), self.assertRaises(ValueError):
                self.validate()

    def test_review_timestamp_and_cost_are_required_and_finite(self):
        entry = finish(entry_for(self.labels, "claim:c1"))
        for field, value in (("reviewer", ""), ("reviewed_at", "2026-10-29T10:00:00"),
                             ("reviewed_at", "not a date"), ("review_seconds", float("nan")),
                             ("review_seconds", float("inf")), ("review_seconds", True), ("review_seconds", -1)):
            old = entry[field]
            entry[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.validate()
            entry[field] = old

    def test_unknown_duplicate_missing_and_cross_dataset_labels_rejected(self):
        originals = deepcopy(self.labels)
        for change in (lambda x: x["entries"].pop(),
                       lambda x: x["entries"].append(deepcopy(x["entries"][0])),
                       lambda x: x.update(dataset_id="other"),
                       lambda x: x["entries"][0].update(snapshot_hash="stale"),
                       lambda x: x["entries"][0].update(sample_id="claim:unknown"),
                       lambda x: x["entries"][0].update(verdit="pass")):
            self.labels = deepcopy(originals)
            change(self.labels)
            with self.assertRaises(ValueError):
                self.validate()

    def test_whole_video_omissions_need_original_video_review(self):
        entry = finish(entry_for(self.labels, "video:v1"), "fail", "transcript")
        entry["reference_claims"] = [reference("omitted")]
        with self.assertRaisesRegex(ValueError, "original video"):
            self.validate()
        entry["review_method"] = "both"
        self.validate()

    def test_covered_reference_must_match_same_video(self):
        entry = finish(entry_for(self.labels, "video:v1"), method="both")
        entry["reference_claims"] = [reference("covered", ["c3"])]
        with self.assertRaisesRegex(ValueError, "another video"):
            self.validate()
        entry["reference_claims"][0]["matched_claim_ids"] = ["c1"]
        self.validate()

    def test_excluded_reference_needs_reason_and_no_matched_ids(self):
        entry = finish(entry_for(self.labels, "video:v1"), method="both")
        entry["reference_claims"] = [reference("excluded", ["c1"])]
        with self.assertRaisesRegex(ValueError, "only covered"):
            self.validate()
        entry["reference_claims"][0]["matched_claim_ids"] = []
        entry["reference_claims"][0]["reason"] = ""
        with self.assertRaisesRegex(ValueError, "reason"):
            self.validate()

    def test_no_reference_video_review_needs_explanation(self):
        entry = finish(entry_for(self.labels, "video:v1"), method="original_video")
        with self.assertRaisesRegex(ValueError, "explanation"):
            self.validate()
        entry["notes"] = "No reusable claims; product showcase only."
        self.validate()


class ReportTests(unittest.TestCase):
    def test_inventory_counts_keyword_candidates_without_asserting_independence(self):
        result = quality.inventory(dataset(), ["Price", "Price", "not present"])
        self.assertEqual(result["totals"], {"videos": 4, "claims": 5, "claims_with_quotes": 4})
        self.assertEqual(len(result["topics"]), 2)
        self.assertEqual(result["topics"][0]["claim_ids"], ["c2"])
        self.assertEqual(result["topics"][1]["video_count"], 0)
        self.assertIn("not independently verified", " ".join(result["limits"]))

    def test_no_human_labels_means_no_estimated_error_rate(self):
        frozen = dataset()
        result = quality.report(frozen, quality.annotation_template(frozen))
        for group in quality.GROUPS:
            self.assertIsNone(result["groups"][group]["failed_units"]["rate"])
        self.assertEqual(result["unique_samples"], 7)
        self.assertEqual(result["overlap_claims"], 4)
        self.assertEqual(len(result["unresolved"]), 7)
        self.assertNotIn("risk_signals", result["sampling"])
        self.assertEqual(result["underfilled_groups"], ["random", "challenge", "whole_video"])
        self.assertEqual(result["input_provenance"]["claims_missing_run_metadata"], 3)

    def test_groups_are_separate_and_multilabel_denominators_are_explicit(self):
        frozen = dataset()
        labels = quality.annotation_template(frozen)
        failed = finish(entry_for(labels, "claim:c2"), "fail")
        failed["errors"] = [error("parameter", "severe", "Price is 200元."),
                            error("scope", "moderate", "Price is 200元.")]
        finish(entry_for(labels, "claim:c1"))
        unable = finish(entry_for(labels, "claim:c3"), "unable", "unavailable")
        unable["notes"] = "Cannot access original."
        result = quality.report(frozen, labels)
        random = result["groups"]["random"]
        self.assertEqual(random["failed_units"], {"numerator": 1, "denominator": 2, "rate": 0.5})
        self.assertEqual(random["units_by_error_type"]["parameter"], 1)
        self.assertEqual(random["units_by_error_type"]["scope"], 1)
        self.assertEqual(random["error_occurrences"], 2)
        self.assertEqual(random["verdicts"]["unable"], 1)
        self.assertEqual(random["review_seconds"]["total"], 36)
        self.assertEqual(result["groups"]["challenge"]["failed_units"]["rate"], 1)
        text = quality.markdown_report(result)
        self.assertIn("not be pooled", text)

    def test_video_omissions_exclude_excluded_references_from_denominator(self):
        frozen = dataset()
        labels = quality.annotation_template(frozen)
        video = finish(entry_for(labels, "video:v1"), "fail", "both")
        video["reference_claims"] = [reference("covered", ["c1"]),
                                    reference("omitted", text="Another useful idea"),
                                    reference("excluded", text="Product slogan")]
        result = quality.report(frozen, labels)
        self.assertEqual(result["groups"]["whole_video"]["omissions"],
                         {"numerator": 1, "denominator": 2, "rate": 0.5})


class FilesAndCommandTests(unittest.TestCase):
    def test_documented_synthetic_fixture_remains_usable(self):
        raw = quality.load_json(ROOT / "tests/fixtures/quality-baseline-input.json")
        frozen = quality.freeze(raw)
        quality.validate_dataset(frozen)
        self.assertEqual(frozen["sampling"]["selected"]["random"], 2)
        labels = quality.annotation_template(frozen)
        entry = finish(entry_for(labels, "claim:demo-claim-1"), "fail")
        entry["errors"] = [error("scope", evidence="我家客厅没有吊顶，使用吸顶灯。")]
        quality.validate_annotations(frozen, labels)

    def test_new_files_are_private_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "private" / "dataset.json"
            quality.write_new(path, {"example": True})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            with self.assertRaises(FileExistsError):
                quality.write_new(path, "must not overwrite")
            self.assertEqual(quality.load_json(path), {"example": True})

    def test_duplicate_json_keys_and_nonfinite_values_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.json"
            for value in ('{"id":1,"id":2}', '{"cost":NaN}', '{"cost":Infinity}'):
                path.write_text(value)
                with self.subTest(value=value), self.assertRaises(ValueError):
                    quality.load_json(path)

    def test_cli_end_to_end_offline(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            folder = Path(folder)
            raw, frozen, labels, report, markdown = [folder / name for name in
                ("input.json", "dataset.json", "annotations.json", "report.json", "report.md")]
            quality.write_new(raw, fixture())
            self.assertEqual(quality.main(["freeze", "--input", str(raw), "--output", str(frozen)]), 0)
            self.assertEqual(quality.main(["template", "--dataset", str(frozen), "--output", str(labels)]), 0)
            self.assertEqual(quality.main(["validate", "--dataset", str(frozen), "--annotations", str(labels)]), 0)
            self.assertEqual(quality.main(["report", "--dataset", str(frozen), "--annotations", str(labels),
                                           "--output", str(report), "--markdown", str(markdown)]), 0)
            self.assertEqual(quality.load_json(report)["groups"]["random"]["verdicts"]["pending"], 5)
            path = folder / "inventory.json"
            self.assertEqual(quality.main(["inventory", "--dataset", str(frozen), "--query", "Price",
                                           "--output", str(path)]), 0)
            self.assertEqual(quality.load_json(path)["topics"][0]["claim_count"], 1)

    def test_database_failure_does_not_print_connection_secrets(self):
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, redirect_stderr(stderr), \
                patch.dict(os.environ, {"QUALITY_TEST_DSN": "private-password"}), \
                patch.object(quality, "read_database", side_effect=RuntimeError("private-password")):
            result = quality.main(["freeze", "--database", "--database-env", "QUALITY_TEST_DSN",
                                   "--output", str(Path(folder) / "out.json")])
        self.assertEqual(result, 1)
        self.assertNotIn("private-password", stderr.getvalue())

    def test_safe_validation_errors_are_actionable(self):
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, redirect_stderr(stderr):
            path = Path(folder) / "raw.json"
            quality.write_new(path, fixture())
            result = quality.main(["freeze", "--input", str(path), "--random-count", "-1",
                                   "--output", str(Path(folder) / "out.json")])
        self.assertEqual(result, 1)
        self.assertIn("cannot be negative", stderr.getvalue())

    def test_database_access_is_readonly_repeatable_read_and_allowlisted(self):
        calls = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def execute(self, sql):
                calls.append(sql)

            def fetchall(self):
                return []

        class Connection:
            closed = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def cursor(self):
                return Cursor()

            def set_session(self, **kwargs):
                self.settings = kwargs

            def close(self):
                self.closed = True

        conn = Connection()
        psycopg = types.ModuleType("psycopg2")
        psycopg.connect = lambda *_args, **_kwargs: conn
        extras = types.ModuleType("psycopg2.extras")
        extras.RealDictCursor = object()
        with patch.dict(sys.modules, {"psycopg2": psycopg, "psycopg2.extras": extras}):
            self.assertEqual(quality.read_database("test-only"), {"videos": [], "claims": [], "runs": []})
        self.assertEqual(conn.settings, {"readonly": True, "isolation_level": "REPEATABLE READ"})
        self.assertTrue(conn.closed)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(sql.startswith(("SET LOCAL", "SELECT")) for sql in calls))
        self.assertFalse(any("raw_response_json" in sql or "prompt_text" in sql or "review_data" in sql for sql in calls))


if __name__ == "__main__":
    unittest.main()
