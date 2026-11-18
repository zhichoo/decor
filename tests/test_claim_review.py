"""Conservative extraction excludes uncertainty without a secondary approval workflow."""
import json
from pathlib import Path
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import test_claim_quality as quality
import test_pipeline_safety as pipeline
import test_public_site as public

ROOT = Path(__file__).resolve().parents[1]


class ClaimFilterRuleTests(unittest.TestCase):
    def test_broken_measurement_and_known_asr_are_signals_not_corrections(self):
        for quote in ("刷三的公分", "花洒刷一.8高", "除卫空调4平方", "散店官网水电开槽"):
            with self.subTest(quote=quote):
                issues = quality.server.claim_review.rule_issues({"source_quotes": [quote]})
                self.assertTrue(issues)
                self.assertEqual(issues[0]["quote"], quote)
        self.assertFalse(quality.server.claim_review.rule_issues({"source_quotes": ["主龙骨间距60公分，副龙骨30公分。"]}))

    def test_model_ambiguity_requires_real_quote_and_known_type(self):
        for issues in ({}, [{"type": "parameter", "quote": "假的原文", "reason": "歧义"}],
                       [{"type": "fact_check_passed", "quote": "真实原文", "reason": "不支持的类型"}]):
            with self.subTest(issues=issues), self.assertRaises(ValueError):
                quality.server.claim_review.model_issues(issues, "真实原文")

    def test_retired_approval_endpoints_never_reach_database_or_models(self):
        server = quality.server

        class QuietHandler(server.AppHandler):
            def log_message(self, *_args):
                pass

        http = server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(server, "connect") as database, patch.object(server, "call_deepseek") as model:
                for readonly in (False, True):
                    with patch.object(server, "PUBLIC_READ_ONLY", readonly):
                        for path in ("/api/admin/quality", "/api/videos/example/reviews", "/api/videos/example/reviews/candidate"):
                            for method in ("GET", "POST"):
                                with self.subTest(path=path, method=method, readonly=readonly):
                                    request = urllib.request.Request(f"http://127.0.0.1:{http.server_port}{path}",
                                        method=method, data=b'{"action":"approve"}' if method == "POST" else None,
                                        headers={"Content-Type": "application/json"})
                                    with self.assertRaises(urllib.error.HTTPError) as caught:
                                        urllib.request.urlopen(request, timeout=3)
                                    self.assertEqual(caught.exception.code, 410)
                database.assert_not_called()
                model.assert_not_called()
        finally:
            http.shutdown(); http.server_close(); thread.join()
        self.assertFalse(hasattr(server, "resolve_claim_review"))


class ClaimFilterDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(pipeline.PipelineSafetyTests.setUpClass.__func__)
    tearDownClass = classmethod(pipeline.PipelineSafetyTests.tearDownClass.__func__)
    setUp = pipeline.PipelineSafetyTests.setUp
    video = pipeline.PipelineSafetyTests.video
    claim = pipeline.PipelineSafetyTests.claim
    result = pipeline.PipelineSafetyTests.result
    extract_with = pipeline.PipelineSafetyTests.extract_with
    active = pipeline.PipelineSafetyTests.active
    claims = pipeline.PipelineSafetyTests.claims

    def flagged(self):
        # An independent clear card must cite a different occurrence, not the same tainted source.
        claim = self.claim("验收时检查插座接线。", "旧文案：装修验收时检查每个插座的接线是否安全。")
        claim["review_issues"] = [{"type": "scope", "quote": claim["source_quotes"][0], "reason": "无法确定对象与适用范围"}]
        return claim

    def test_missing_first_pass_contract_preserves_old_cards(self):
        response = json.loads(self.result([self.claim("检查插座接线。")]))
        content = json.loads(response["choices"][0]["message"]["content"])
        del content["extraction_contract"]
        response["choices"][0]["message"]["content"] = json.dumps(content)
        with self.assertRaisesRegex(ValueError, "missing_extraction_contract"):
            self.extract_with(json.dumps(response))
        self.assertEqual([card["id"] for card in self.active()], ["old"])

    def test_effect_only_card_is_filtered_before_storage(self):
        source = self.old_text + "\n窗户不用自己动手擦。"
        with self.server.connect() as conn:
            conn.execute("UPDATE videos SET transcript_text=%s, transcript_length=%s WHERE id=%s",
                         (source, len(source), self.video_id))
        last = len(self.server.claim_wire.segments(source))
        claim = self.claim("窗户不用自己动手擦。", "窗户不用自己动手擦。")
        claim["original_reasons"] = []
        response = json.loads(self.result([claim], transcript=source))
        content = json.loads(response["choices"][0]["message"]["content"])
        content["claims"][0]["statement"][1:] = [last, last]
        response["choices"][0]["message"]["content"] = json.dumps(content)
        claim = self.claim("窗户不用自己动手擦。", "窗户不用自己动手擦。")
        claim["object_name"] = "窗户自动清洁"
        result = self.extract_with(json.dumps(response))
        self.assertEqual(result["status"], "filtered")
        self.assertEqual(self.active(), [])
        self.assertEqual(result["dropped_claims"][0]["reason"], "no_actionable_information")

    def test_legacy_field_binding_cannot_bypass_wire_contract(self):
        response = json.loads(self.result([self.claim("检查插座接线。")]))
        content = json.loads(response["choices"][0]["message"]["content"])
        content["claims"][0]["field_evidence"] = {"original_conclusion": [9]}
        response["choices"][0]["message"]["content"] = json.dumps(content)
        with self.assertRaisesRegex(ValueError, "mixed_extraction_contract"):
            self.extract_with(json.dumps(response))
        self.assertEqual([card["id"] for card in self.active()], ["old"])

    def test_previous_protocol_cannot_replace_old_cards(self):
        response = json.loads(self.result([self.claim("检查插座接线。")]))
        content = json.loads(response["choices"][0]["message"]["content"])
        content = self.server.claim_wire.normalize(content, self.old_text)
        response["choices"][0]["message"]["content"] = json.dumps(content)
        with self.assertRaisesRegex(ValueError, "missing_extraction_contract_v18"):
            self.extract_with(json.dumps(response))
        self.assertEqual([card["id"] for card in self.active()], ["old"])

    def test_nested_optional_triple_is_failure_and_preserves_old_cards(self):
        response = json.loads(self.result([self.claim("检查插座接线。")]))
        content = json.loads(response["choices"][0]["message"]["content"])
        content["claims"][0]["reason"] = [["检查插座接线。", 2, 2]]
        response["choices"][0]["message"]["content"] = json.dumps(content)
        with self.assertRaisesRegex(ValueError, "invalid_evidence_pair:reason"):
            self.extract_with(json.dumps(response))
        self.assertEqual([card["id"] for card in self.active()], ["old"])

    def test_forged_quote_in_partial_output_cannot_replace_old_cards(self):
        response = self.result([self.claim("检查插座接线。"), self.claim("必须采用另一做法。", "原文中没有的引句不能被采用")])
        with self.assertRaisesRegex(ValueError, "invalid_evidence_span"):
            self.extract_with(response)
        self.assertEqual([card["id"] for card in self.active()], ["old"])

    def test_linked_top_ambiguity_excludes_candidate_with_one_model_call(self):
        response = json.loads(self.result([self.claim("检查插座接线。")]))
        content = json.loads(response["choices"][0]["message"]["content"])
        content["ambiguities"] = [{"type": "scope", "span": [2, 2], "blocking": "source",
                                   "reason": "核心主张不清", "affected_claim_ids": ["c1"], "blocked_terms": []}]
        response["choices"][0]["message"]["content"] = json.dumps(content)
        with patch.object(self.server, "call_deepseek", return_value=(json.dumps(response), None)) as model:
            with self.server.connect() as conn:
                result = self.server.extract_claims_for_video(conn, self.server.row_to_video(self.video()))
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["status"], "filtered")
        self.assertEqual(self.active(), [])

    def test_partial_extraction_keeps_clear_card_and_records_exclusion_without_task(self):
        with patch.object(self.server, "call_deepseek", return_value=(self.result([self.claim("检查插座接线。"), self.flagged()]), None)) as model:
            with self.server.connect() as conn:
                result = self.server.extract_claims_for_video(conn, self.server.row_to_video(self.video()))
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["claims"]), 1)
        self.assertEqual(result["excluded_claim_count"], 1)
        self.assertNotIn("pending_review_count", result)
        with self.server.connect() as conn:
            self.assertEqual(self.server.fetch_knowledge_page(conn)["total"], 1)
            self.assertEqual(self.server.fetch_video_page(conn)["videos"][0]["excluded_claim_count"], 1)
            self.assertEqual(self.server.fetch_progress_summary(conn)["待确认"], 0)
            run = conn.execute("SELECT * FROM extraction_runs WHERE id=%s", (result["run_id"],)).fetchone()
            self.assertEqual(run["status"], "completed")
            self.assertTrue(all(item["status"] == "excluded" and "claim" not in item for item in run["review_data"]["items"]))

    def test_unrelated_exclusion_cannot_turn_malformed_claim_into_empty_replacement(self):
        text = self.old_text + "另一个施工术语听不清需要略过。"
        with self.server.connect() as conn:
            conn.execute("UPDATE videos SET transcript_text=%s,transcript_length=%s", (text, len(text)))
        for field, value in (("content_type", "验收标准"), ("topic_tags", [7])):
            with self.subTest(field=field):
                response = json.loads(self.result([self.claim("检查插座接线。")], transcript=text))
                payload = json.loads(response["choices"][0]["message"]["content"])
                payload["claims"][0][field] = value
                last = len(self.server.claim_wire.segments(text))
                payload["ambiguities"] = [{"type": "transcription", "span": [last, last],
                    "blocking": "terms", "blocked_terms": ["听不清"], "reason": "无关术语不清"}]
                response["choices"][0]["message"]["content"] = json.dumps(payload)
                with self.assertRaisesRegex(ValueError, "invalid_claim_"):
                    self.extract_with(json.dumps(response))
                self.assertEqual([card["id"] for card in self.active()], ["old"])
                with self.server.connect() as conn:
                    statuses = conn.execute("SELECT status FROM extraction_runs").fetchall()
                    self.assertTrue(all(row["status"] == "parse_failed" for row in statuses))

    def test_source_ambiguity_blocks_reworded_neighbor_using_same_source(self):
        response = json.loads(self.result([self.claim("应确认每个插座的接线。"), self.flagged()]))
        content = json.loads(response["choices"][0]["message"]["content"])
        content["claims"][0]["statement"][1:] = content["claims"][1]["statement"][1:]
        response["choices"][0]["message"]["content"] = json.dumps(content)
        result = self.extract_with(json.dumps(response))
        self.assertEqual(result["status"], "filtered")
        self.assertEqual(self.active(), [])
        self.assertIn("dependency", json.dumps(result["dropped_claims"]))

    def test_missing_ambiguity_blocking_preserves_old_cards(self):
        response = json.loads(self.result([self.flagged()]))
        content = json.loads(response["choices"][0]["message"]["content"])
        del content["claims"][0]["review_issues"][0]["blocking"]
        response["choices"][0]["message"]["content"] = json.dumps(content)
        with self.assertRaisesRegex(ValueError, "missing_ambiguity_blocking"):
            self.extract_with(json.dumps(response))
        self.assertEqual([card["id"] for card in self.active()], ["old"])

    def test_successfully_excluding_all_replaces_old_cards_without_deleting_source(self):
        result = self.extract_with(self.result([self.flagged()]))
        self.assertEqual(result["status"], "filtered")
        self.assertEqual(self.active(), [])
        self.assertEqual(self.video()["status"], "claims_filtered")
        self.assertEqual(self.video()["transcript_text"], self.old_text)
        self.assertIsNone(self.video()["deleted_at"])
        self.assertEqual(len(self.claims()), 1)  # Old formal card remains recoverable via soft deletion.
        with self.server.connect() as conn:
            self.assertEqual(self.server.fetch_progress_summary(conn)["已完成"], 1)

    def test_unsupported_number_is_excluded_and_cannot_be_manually_admitted(self):
        result = self.extract_with(self.result([self.claim("建议插座预算300元。")]))
        self.assertEqual(result["status"], "filtered")
        self.assertEqual(result["excluded_claim_count"], 1)
        self.assertEqual(self.active(), [])
        self.assertIn("unsupported_numeric_detail", json.dumps(result["dropped_claims"]))

    def test_top_level_uncertainty_is_filtered_without_approval(self):
        response = json.loads(self.result([]))
        response["choices"][0]["message"]["content"] = json.dumps({"claims": [], "filter_reason": "speech_unclear",
            "extraction_contract": "v18", "promotion_context": {"has_promotion": False, "subjects": []},
            "ambiguities": [{"type": "transcription", "span": [2, 2], "blocking": "source", "reason": "对象不清", "affected_claim_ids": [], "blocked_terms": []}]})
        result = self.extract_with(json.dumps(response))
        self.assertEqual(result["status"], "filtered")
        self.assertEqual(result["excluded_claim_count"], 1)
        self.assertEqual(self.active(), [])

    def test_malformed_model_ambiguity_is_failure_not_successful_empty_selection(self):
        bad = self.flagged()
        bad["review_issues"][0]["quote"] = "模型编造的一句引文"
        with self.assertRaisesRegex(ValueError, "invalid_evidence_span"):
            self.extract_with(self.result([bad]))
        self.assertEqual([c["id"] for c in self.active()], ["old"])

    def test_automatic_queue_does_not_retry_successfully_filtered_input(self):
        self.extract_with(self.result([self.flagged()]))
        with patch.object(self.server, "call_deepseek") as model, self.server.connect() as conn:
            result = self.server.process_pending_queue(conn, limit=3)
        model.assert_not_called()
        self.assertEqual(result["remaining"], 0)

    def prepare_empty_queue_video(self):
        with self.server.connect() as conn:
            conn.execute("UPDATE claims SET deleted_at=77 WHERE video_id=%s", (self.video_id,))
            conn.execute("UPDATE videos SET status='transcript_saved',retry_count=0,last_error=NULL WHERE id=%s",
                         (self.video_id,))

    def test_queue_does_not_repeat_failed_model_on_same_transcript(self):
        self.prepare_empty_queue_video()
        with patch.object(self.server, "call_deepseek", return_value=(None, "deepseek_http_503: busy")) as model:
            with self.server.connect() as conn:
                first = self.server.process_pending_queue(conn, limit=3)
                second = self.server.process_pending_queue(conn, limit=3)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(len(first["failed"]), 1)
        self.assertEqual((first["remaining"], second["remaining"]), (0, 0))
        self.assertEqual(self.video()["retry_count"], 1)
        self.assertIn("503", self.video()["last_error"])
        self.assertEqual(self.video()["transcript_text"], self.old_text)
        self.assertEqual(self.active(), [])

    def test_queue_does_not_repeat_invalid_model_output(self):
        self.prepare_empty_queue_video()
        invalid = self.result([self.claim("检查插座接线。")])
        response = json.loads(invalid)
        content = json.loads(response["choices"][0]["message"]["content"])
        content["claims"][0]["statement"][1:] = [9999, 9999]
        response["choices"][0]["message"]["content"] = json.dumps(content)
        with patch.object(self.server, "call_deepseek", return_value=(json.dumps(response), None)) as model:
            with self.server.connect() as conn:
                result = self.server.process_pending_queue(conn, limit=3)
                self.assertEqual(conn.execute("SELECT status FROM extraction_runs").fetchone()["status"], "parse_failed")
        self.assertEqual(model.call_count, 1)
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(result["remaining"], 0)

    def test_queue_continues_to_another_video_instead_of_rescuing_failed_one(self):
        self.prepare_empty_queue_video()
        with self.server.connect() as conn:
            conn.execute("""INSERT INTO videos
                (id,platform,creator,title,source_url,transcript_text,has_transcript,transcript_length,status,created_at,updated_at)
                VALUES ('next-video','test','test','next','https://example.invalid/next',%s,true,%s,'transcript_saved',1,1)""",
                (self.old_text, len(self.old_text)))
            with patch.object(self.server, "call_deepseek", side_effect=[
                (None, "deepseek_http_503: busy"), (self.result([self.claim("检查插座接线。")]), None)
            ]) as model:
                result = self.server.process_pending_queue(conn, limit=3)
        self.assertEqual(model.call_count, 2)
        self.assertEqual([v["video_id"] for v in result["failed"]], [self.video_id])
        self.assertEqual([v["video_id"] for v in result["processed"]], ["next-video"])
        self.assertEqual(result["remaining"], 0)

    def test_automatic_entry_skips_prior_attempt_before_advertising_or_model_calls(self):
        self.extract_with(None, "model_unavailable")
        with self.server.connect() as conn:
            # A changed extraction version or superseded marker must not trigger a paid retry.
            conn.execute("UPDATE extraction_runs SET prompt_version='older-version',review_data=%s",
                         (self.server.Json({"superseded": True}),))
            with patch.object(self.server, "call_deepseek") as model, \
                 patch.object(self.server, "review_video_advertising") as advertising:
                result = self.server.extract_claims_for_video(conn, self.server.row_to_video(self.video()), automatic=True)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM extraction_runs").fetchone()["n"], 1)
        self.assertEqual(result["status"], "skipped_existing_extraction")
        model.assert_not_called()
        advertising.assert_not_called()
        self.assertEqual([c["id"] for c in self.active()], ["old"])

    def test_request_intent_is_recorded_before_submission_and_unexpected_error_preserves_old_cards(self):
        def request(_prompt):
            with self.server.connect() as conn:
                run = conn.execute("SELECT status,raw_response_json FROM extraction_runs").fetchone()
                self.assertEqual(run["status"], "request_started")
                self.assertIsNone(run["raw_response_json"])
            raise RuntimeError("unexpected_transport_failure")
        with patch.object(self.server, "call_deepseek", side_effect=request) as model:
            with self.server.connect() as conn, self.assertRaisesRegex(RuntimeError, "unexpected_transport_failure"):
                self.server.extract_claims_for_video(conn, self.server.row_to_video(self.video()))
        self.assertEqual(model.call_count, 1)
        self.assertEqual([c["id"] for c in self.active()], ["old"])
        with self.server.connect() as conn:
            self.assertEqual(conn.execute("SELECT status FROM extraction_runs").fetchone()["status"], "model_failed")

    def test_manual_extraction_can_retry_after_failed_attempt(self):
        self.extract_with(None, "model_unavailable")
        result = self.extract_with(self.result([self.claim("检查插座接线。")]))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.active()), 1)
        with self.server.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM extraction_runs").fetchone()["n"], 2)

    def test_explicit_full_retry_is_allowed_with_unchanged_transcript(self):
        self.extract_with(None, "model_unavailable")
        with patch.object(self.server, "fetch_transcript_from_transcriptgenerate", return_value={
            "transcript_text": self.old_text, "task_id": "mock-task"
        }), patch.object(self.server, "call_deepseek", return_value=(self.result([self.claim("检查插座接线。")]), None)) as model:
            result = self.server.retry_video_from_transcript(self.video_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(model.call_count, 1)

    def test_changed_transcript_is_eligible_without_reusing_failed_result(self):
        self.extract_with(None, "model_unavailable")
        self.prepare_empty_queue_video()
        text = self.old_text + "新增说明：验收前应核对设计图纸。"
        with self.server.connect() as conn:
            conn.execute("UPDATE videos SET transcript_text=%s,transcript_length=%s WHERE id=%s",
                         (text, len(text), self.video_id))
            with patch.object(self.server, "call_deepseek", return_value=(
                self.result([self.claim("检查插座接线。")], transcript=text), None)) as model:
                result = self.server.process_pending_queue(conn, limit=3)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(len(result["processed"]), 1)
        self.assertEqual(result["remaining"], 0)

    def test_unknown_interrupted_attempt_is_not_automatically_repeated(self):
        self.prepare_empty_queue_video()
        with self.server.connect() as conn:
            conn.execute("""INSERT INTO extraction_runs
                (id,video_id,model,prompt_version,input_hash,prompt_text,status,created_at)
                VALUES ('unknown-attempt',%s,'test','test',%s,'test','request_started',1)""",
                (self.video_id, self.server.hashlib.sha256(self.old_text.encode()).hexdigest()))
            with patch.object(self.server, "call_deepseek") as model:
                result = self.server.process_pending_queue(conn, limit=3)
        model.assert_not_called()
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(result["processed"], [])

    def test_queue_http_endpoints_do_not_offer_previously_failed_input(self):
        self.prepare_empty_queue_video()
        self.extract_with(None, "model_unavailable")
        server = self.server
        previous_db_status = dict(server.DB_STATUS)
        server.check_database()
        http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(server, "ADMIN_PASSWORD", "test-only"), \
                 patch.object(server, "ADMIN_SESSION_SECRET", "test-only-secret"), \
                 patch.object(server, "call_deepseek") as model:
                headers = {"Content-Type": "application/json",
                           "Cookie": f"{server.ADMIN_SESSION_COOKIE}={server.make_admin_session_value()}"}
                request = urllib.request.Request(f"http://127.0.0.1:{http.server_port}/api/queue/next", headers=headers)
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertIsNone(json.load(response)["next_extract"])
                request = urllib.request.Request(f"http://127.0.0.1:{http.server_port}/api/queue/extract-next",
                                                 data=b"{}", headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(json.load(response)["status"], "empty")
                model.assert_not_called()
        finally:
            http.shutdown()
            http.server_close()
            thread.join(timeout=5)
            server.DB_STATUS.update(previous_db_status)
            server.invalidate_bootstrap_cache()

    def test_legacy_pending_is_not_an_approval_task_or_automatic_retry(self):
        result = self.extract_with(self.result([self.flagged()]))
        with self.server.connect() as conn:
            run = conn.execute("SELECT review_data FROM extraction_runs WHERE id=%s", (result["run_id"],)).fetchone()
            legacy = run["review_data"]
            legacy["items"][0]["status"] = "pending"
            conn.execute("UPDATE extraction_runs SET review_data=%s,status='pending_review' WHERE id=%s", (self.server.Json(legacy), result["run_id"]))
            conn.execute("UPDATE videos SET status='transcript_saved' WHERE id=%s", (self.video_id,))
            self.assertEqual(self.server.fetch_progress_summary(conn)["待确认"], 0)
            self.assertEqual(self.server.fetch_progress_summary(conn)["已完成"], 1)
            with patch.object(self.server, "call_deepseek") as model:
                self.assertEqual(self.server.process_pending_queue(conn, limit=3)["remaining"], 0)
            model.assert_not_called()
            conn.execute("UPDATE videos SET transcript_text=transcript_text || '修正' WHERE id=%s", (self.video_id,))
            self.assertEqual(self.server.fetch_video_page(conn)["videos"][0]["excluded_claim_count"], 0)

    def test_new_extraction_supersedes_old_exclusion_counts(self):
        self.extract_with(self.result([self.flagged()]))
        self.extract_with(self.result([self.claim("检查插座接线是否安全。")]))
        with self.server.connect() as conn:
            self.assertEqual(self.server.fetch_video_page(conn)["videos"][0]["excluded_claim_count"], 0)
            self.assertEqual(self.server.fetch_knowledge_page(conn)["total"], 1)

    def test_failed_retry_is_not_hidden_by_previous_successful_filter(self):
        self.extract_with(self.result([self.flagged()]))
        self.assertEqual(self.extract_with(None, "model_unavailable")["status"], "model_unavailable")
        with self.server.connect() as conn:
            self.assertEqual(self.server.fetch_progress_summary(conn)["失败"], 1)
            self.assertEqual(self.server.fetch_progress_summary(conn)["已完成"], 0)

    def test_exclusion_record_failure_rolls_back_replacement(self):
        execute = self.server.PGConnection.execute

        def fail_record(connection, sql, params=None):
            if sql.startswith("UPDATE extraction_runs SET review_data=%s, status=%s"):
                raise RuntimeError("synthetic record failure")
            return execute(connection, sql, params)

        with patch.object(self.server.PGConnection, "execute", fail_record):
            with self.assertRaisesRegex(RuntimeError, "synthetic record failure"):
                self.extract_with(self.result([self.claim("检查插座。"), self.flagged()]))
        self.assertEqual([c["id"] for c in self.active()], ["old"])

    def test_public_export_excludes_diagnostic_evidence_and_no_candidate_leaks(self):
        self.extract_with(self.result([self.claim("验收时检查接线。"), self.flagged()]))
        with self.server.connect() as conn:
            videos = [dict(row) for row in conn.execute("SELECT * FROM videos").fetchall()]
            claims = [dict(row) for row in conn.execute("SELECT * FROM claims").fetchall()]
        snapshot = public.exporter.make_snapshot([], videos, claims)
        text = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("review_issues", text)
        self.assertNotIn("无法确定对象与适用范围", text)
        self.assertEqual(snapshot["stats"]["claim_count"], 1)


if __name__ == "__main__":
    unittest.main()
