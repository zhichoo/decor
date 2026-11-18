"""Upgrade inventory/trial safety; all samples are synthetic and model calls are mocked."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("decor_claim_upgrade", ROOT / "scripts/claim_upgrade.py")
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)

VERSION = "test-new-version"


def fixture(count=8):
    videos, claims, runs = [], [], []
    for index in range(count):
        video_id = f"v{index}"
        transcript = "明确材料范围，保留合同约定，避免追加费用。" * 12
        videos.append({"id": video_id, "title": f"装修 {index}", "creator": f"博主 {index % 3}",
                       "transcript_text": transcript, "deleted_at": None,
                       "ad_review_override": {"decision": "not_ad"}})
        claims.append({"id": f"c{index}", "video_id": video_id, "extraction_run_id": f"r{index}",
                       "deleted_at": None, "source_quotes": [], "author_stance": None, "content_type": None})
        runs.append({"id": f"r{index}", "video_id": video_id, "prompt_version": "old",
                     "input_hash": upgrade.text_hash(transcript), "status": "completed", "created_at": 1})
    return {"sources": [], "videos": videos, "claims": claims, "extraction_runs": runs}


class ClaimUpgradeTests(unittest.TestCase):
    def test_inventory_counts_legacy_cards_without_changing_input(self):
        snapshot = fixture()
        before = upgrade.digest(snapshot)
        report = upgrade.inventory(snapshot, VERSION)
        self.assertEqual(report["states"], {"outdated": 8})
        self.assertEqual(report["active_claim_versions"], {"old": 8})
        self.assertEqual(report["videos"][0]["missing_quotes"], 1)
        self.assertEqual(before, upgrade.digest(snapshot))

    def test_current_requires_prompt_hash_and_new_fields_not_just_latest_run(self):
        for mismatch in ("prompt", "hash", "fields", "bindings", "scope", "contract", "video", None):
            with self.subTest(mismatch=mismatch):
                snapshot = fixture(1)
                run, claim = snapshot["extraction_runs"][0], snapshot["claims"][0]
                run["prompt_version"] = VERSION
                claim.update(source_quotes=["明确材料范围，保留合同约定"], author_stance="赞成", content_type="施工做法",
                             object_name="材料范围", original_conclusion="保留合同约定", source_scope="general", scope_quote="",
                             evidence_contract=upgrade.claim_contract.VERSION,
                             field_evidence={"object_name": [0], "original_conclusion": [0]})
                if mismatch == "prompt":
                    run["prompt_version"] = "old"
                elif mismatch == "hash":
                    run["input_hash"] = "old-input"
                elif mismatch == "fields":
                    claim["source_quotes"] = []
                elif mismatch == "bindings":
                    claim["field_evidence"] = {"object_name": [0]}
                elif mismatch == "scope":
                    claim["source_scope"] = None
                elif mismatch == "contract":
                    claim["evidence_contract"] = None
                elif mismatch == "video":
                    run["video_id"] = "other-video"
                state = upgrade.inventory(snapshot, VERSION)["videos"][0]["state"]
                self.assertEqual(state, "current" if mismatch is None else "outdated")

    def test_new_unrelated_success_does_not_upgrade_old_active_cards(self):
        snapshot = fixture(1)
        snapshot["extraction_runs"].append({**snapshot["extraction_runs"][0], "id": "new-run",
                                            "prompt_version": VERSION, "created_at": 10})
        self.assertEqual(upgrade.inventory(snapshot, VERSION)["states"], {"outdated": 1})

    def test_filtered_current_input_is_not_repeated_but_changed_input_is_stale(self):
        snapshot = fixture(1)
        snapshot["claims"] = []
        snapshot["extraction_runs"][0].update(prompt_version=VERSION, status="filtered")
        self.assertEqual(upgrade.inventory(snapshot, VERSION)["states"], {"current_filtered": 1})
        snapshot["videos"][0]["transcript_text"] += "新内容"
        self.assertEqual(upgrade.inventory(snapshot, VERSION)["states"], {"outdated": 1})

    def test_manual_or_unknown_deletions_block_whole_video(self):
        for actor, reason, expected in (("admin", "manual_delete", "deletion_guard"),
                                       (None, None, "deletion_guard"),
                                       ("system", "cleanup", "deletion_guard"),
                                       ("system", "replace_extracted_claims", "outdated")):
            with self.subTest(actor=actor, reason=reason):
                snapshot = fixture(1)
                snapshot["claims"].append({"id": "deleted", "video_id": "v0", "deleted_at": 2,
                                            "deleted_by": actor, "delete_reason": reason})
                self.assertEqual(upgrade.inventory(snapshot, VERSION)["videos"][0]["state"], expected)

    def test_deleted_sources_missing_transcripts_and_advertising_are_not_upgrade_candidates(self):
        snapshot = fixture(5)
        snapshot["videos"][0]["deleted_at"] = 1
        snapshot["videos"][1]["transcript_text"] = snapshot["videos"][1]["title"]
        snapshot["videos"][2]["ad_review_override"] = {"decision": "advertising"}
        snapshot["videos"][3]["ad_review_override"] = {"decision": "uncertain"}
        snapshot["videos"][4]["transcript_text"] = "文案太短"
        report = upgrade.inventory(snapshot, VERSION)
        self.assertEqual([row["state"] for row in report["videos"]], [
            "deleted_video", "missing_transcript", "advertising", "ad_status_unresolved", "short_transcript"])
        self.assertEqual(report["active_claim_versions"], {"old": 4})

    def test_selection_is_reproducible_balances_creators_and_includes_ad_controls(self):
        snapshot = fixture(12)
        for row in snapshot["videos"][-2:]:
            row["ad_review_override"] = {"decision": "advertising"}
        report = upgrade.inventory(snapshot, VERSION)
        selected = upgrade.choose_samples(report)
        self.assertEqual(selected, upgrade.choose_samples(report))
        self.assertEqual(len(selected), 8)
        self.assertEqual(sum(row["state"] == "advertising" for row in selected), 2)
        self.assertEqual(len(set(row["creator"] for row in selected)), 3)
        for limit in (4, 11):
            with self.assertRaises(ValueError):
                upgrade.choose_samples(report, limit)

    def fake_server(self):
        return SimpleNamespace(PROMPT_VERSION=VERSION, active_model_name=lambda: "mock-only",
            build_extract_prompt=lambda video: video["transcript_text"],
            call_deepseek=Mock(return_value=(json.dumps({"claims": [], "filter_reason": "no_general_knowledge"}), None)),
            parse_deepseek_content=json.loads, partition_claims=lambda value, text, **kwargs: (value["claims"], [], []),
            FILTER_REASON_MESSAGES={"no_general_knowledge": "empty"})

    def test_trial_only_writes_private_files_and_resume_does_not_call_again(self):
        snapshot = fixture(5)
        before = upgrade.digest(snapshot)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            upgrade.save_json(workspace / "snapshot.private.json", snapshot)
            upgrade.save_json(workspace / "inventory.json", upgrade.inventory(snapshot, VERSION))
            server = self.fake_server()
            result = upgrade.stage_sample(workspace, server, 5)
            self.assertEqual(server.call_deepseek.call_count, 5)
            self.assertEqual(result["production_writes"], 0)
            self.assertEqual(result["gate"], "not_evaluated")
            upgrade.stage_sample(workspace, server, 5)
            self.assertEqual(server.call_deepseek.call_count, 5)
            self.assertEqual(before, upgrade.digest(json.loads((workspace / "snapshot.private.json").read_text())))
            self.assertEqual((workspace / "snapshot.private.json").stat().st_mode & 0o777, 0o600)

    def test_inflight_request_is_not_automatically_rebilled(self):
        snapshot = fixture(5)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            upgrade.save_json(workspace / "snapshot.private.json", snapshot)
            upgrade.save_json(workspace / "inventory.json", upgrade.inventory(snapshot, VERSION))
            server = self.fake_server()
            server.call_deepseek.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                upgrade.stage_sample(workspace, server, 5)
            server.call_deepseek.side_effect = None
            result = upgrade.stage_sample(workspace, server, 5)
            self.assertEqual(server.call_deepseek.call_count, 5)
            self.assertEqual(result["statuses"]["request_started_unknown_result"], 1)

    def test_snapshot_or_prompt_changes_require_new_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            snapshot = fixture(5)
            upgrade.save_json(workspace / "snapshot.private.json", snapshot)
            upgrade.save_json(workspace / "inventory.json", upgrade.inventory(snapshot, "wrong-version"))
            server = self.fake_server()
            with self.assertRaises(ValueError):
                upgrade.stage_sample(workspace, server, 5)
            server.call_deepseek.assert_not_called()

    def test_bad_output_is_failure_not_successful_empty_replacement(self):
        server = self.fake_server()
        for raw in ('[]', '{}', '{"claims":[],"filter_reason":"unknown"}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                upgrade.evaluate_response(server, raw, "文案")
        server.partition_claims = lambda value, text, **kwargs: ([], [{"reason": "bad_evidence"}], [])
        with self.assertRaisesRegex(ValueError, "quality_check_failed"):
            upgrade.evaluate_response(server, '{"claims":[{}]}', "文案")

    def test_explicit_same_group_rejects_changed_input_before_paid_calls(self):
        snapshot = fixture(8)
        report = upgrade.inventory(snapshot, VERSION)
        selected = upgrade.choose_samples(report)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            upgrade.save_json(workspace / "snapshot.private.json", snapshot)
            upgrade.save_json(workspace / "inventory.json", report)
            selected[0]["input_hash"] = "changed"
            upgrade.save_json(workspace / "previous.json", selected)
            server = self.fake_server()
            with self.assertRaisesRegex(ValueError, "previous sample input"):
                upgrade.stage_sample(workspace, server, 8, selection_from=workspace / "previous.json")
            server.call_deepseek.assert_not_called()

    def test_holdout_excludes_all_previous_sample_ids(self):
        snapshot = fixture(20)
        for row in snapshot["videos"][-4:]:
            row["ad_review_override"] = {"decision": "advertising"}
        report = upgrade.inventory(snapshot, VERSION)
        previous = {row["video_id"] for row in upgrade.choose_samples(report, 8)}
        holdout = upgrade.choose_samples(report, 5, previous)
        self.assertEqual(len(holdout), 5)
        self.assertFalse(previous & {row["video_id"] for row in holdout})

    def test_usage_is_saved_even_when_validation_fails(self):
        snapshot = fixture(5)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            upgrade.save_json(workspace / "snapshot.private.json", snapshot)
            upgrade.save_json(workspace / "inventory.json", upgrade.inventory(snapshot, VERSION))
            server = self.fake_server()
            server.call_deepseek.return_value = ('{"usage":{"total_tokens":123}}', None)
            upgrade.stage_sample(workspace, server, 5)
            for path in (workspace / "samples").glob("*.json"):
                result = json.loads(path.read_text())
                self.assertEqual(result["status"], "validation_failed")
                self.assertEqual(result["usage"]["total_tokens"], 123)

    def test_recheck_does_not_call_model_or_change_original_result(self):
        snapshot = fixture(5)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            upgrade.save_json(workspace / "snapshot.private.json", snapshot)
            upgrade.save_json(workspace / "inventory.json", upgrade.inventory(snapshot, VERSION))
            server = self.fake_server()
            upgrade.stage_sample(workspace, server, 5)
            before = {path.name: path.read_bytes() for path in (workspace / "samples").glob("*.json")}
            server.call_deepseek.reset_mock()
            result = upgrade.recheck_samples(workspace, server)
            server.call_deepseek.assert_not_called()
            self.assertEqual(result["model_calls"], 0)
            self.assertEqual(result["production_writes"], 0)
            self.assertEqual(before, {path.name: path.read_bytes() for path in (workspace / "samples").glob("*.json")})
            self.assertTrue(list((workspace / "rechecks").glob("*.json")))


if __name__ == "__main__":
    unittest.main()
