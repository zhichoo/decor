"""Source-attributed claims: no invented context, persistent quotes, legacy compatibility."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import test_claim_quality as quality
import test_pipeline_safety as pipeline

ROOT = Path(__file__).resolve().parents[1]


class ClaimContextQualityTests(unittest.TestCase):
    def test_context_fields_are_independent_and_legacy_storage_is_derived(self):
        source = "这次安装插座花了不少钱，使用时插拔也不顺手，所以我不推荐这款。"
        claim = {"object_name": "插座选购", "author_stance": "反对", "content_type": "个人体验",
                 "original_conclusion": "作者因本次安装投入较多且插拔不顺手，不推荐这款插座。",
                 "original_reasons": [], "conditions": "未提及", "source_quotes": [source]}
        kept, dropped = quality.server.sanitize_claims([claim], source, require_evidence=True)
        self.assertEqual(dropped, [])
        self.assertEqual(kept[0]["stance"], "明确不推荐")
        self.assertEqual(kept[0]["author_stance"], "反对")
        self.assertEqual(kept[0]["content_type"], "个人体验")
        self.assertEqual(kept[0]["conditions"], "未提及")

    def test_invalid_or_incomplete_context_is_not_silently_relabelled(self):
        source = "装修验收时检查每个插座的接线是否安全。"
        for fields in ({"author_stance": "有条件", "content_type": "价格信息"},
                       {"author_stance": "赞成"}, {"content_type": "系统推荐"}):
            with self.subTest(fields=fields):
                claim = {"object_name": "插座", "original_conclusion": "验收时检查插座接线。",
                         "source_quotes": [source], **fields}
                kept, dropped = quality.server.sanitize_claims([claim], source, require_evidence=True)
                self.assertFalse(kept)
                self.assertEqual(dropped[0]["reason"], "invalid_claim_context")

    def test_quote_cannot_be_rewritten_even_if_characters_match(self):
        source = "检查插座接线，确认安全。"
        claim = {"object_name": "插座", "original_conclusion": "检查插座接线。",
                 "source_quotes": ["检查插座接线确认安全"]}
        kept, dropped = quality.server.sanitize_claims([claim], source, require_evidence=True)
        self.assertFalse(kept)
        self.assertEqual(dropped[0]["reason"], "unsupported_source_evidence")

    def test_prompt_keeps_source_attitude_separate_from_applicability(self):
        prompt = quality.server.build_extract_prompt({"id": "v", "title": "测试", "creator": "作者",
            "platform": "抖音", "source_url": "https://example.invalid", "transcript_text": "无主灯别做，贵又不好用。"})
        for rule in ("author_stance", "content_type", "不要求补齐户型", "缺少条件不应单独成为过滤理由",
                     "不能推导", "不生成个性化推荐分数", "背景不自动等于适用限制", "个人感受",
                     "每个数字必须由本卡 source_quotes 支撑", "不能改写成所有施工方", "该酒店",
                     "作者态度必须与对象和结论方向一致"):
            self.assertIn(rule, prompt)
        self.assertNotIn('"stance":', prompt)


class ClaimContextDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(pipeline.PipelineSafetyTests.setUpClass.__func__)
    tearDownClass = classmethod(pipeline.PipelineSafetyTests.tearDownClass.__func__)
    setUp = pipeline.PipelineSafetyTests.setUp
    video = pipeline.PipelineSafetyTests.video
    claim = pipeline.PipelineSafetyTests.claim
    result = pipeline.PipelineSafetyTests.result
    extract_with = pipeline.PipelineSafetyTests.extract_with

    def test_extract_api_and_facets_preserve_context_and_verbatim_quotes(self):
        claim = self.claim("验收时检查插座接线。")
        claim.update(author_stance="中性陈述", content_type="验收要求")
        result = self.extract_with(self.result([claim]))
        self.assertEqual(result["status"], "completed")
        with self.server.connect() as conn:
            for query, expected in (({"author_stance": ["中性陈述"]}, 1),
                                    ({"author_stance": ["反对"]}, 0),
                                    ({"content_type": ["验收要求"]}, 1)):
                page = self.server.fetch_knowledge_page(conn, query)
                self.assertEqual(page["total"], expected)
                self.assertEqual(page["facets"]["author_stances"], {"中性陈述": 1})
                self.assertEqual(page["facets"]["content_types"], {"验收要求": 1})
            stored = self.server.fetch_knowledge_page(conn)["claims"][0]
            self.assertEqual(stored["source_quotes"], [claim["source_quotes"][0] + "。"])
            self.assertEqual(stored["author_stance"], "中性陈述")
            self.assertEqual(stored["stance"], "未明确")

    def test_unclassified_counts_and_filter_use_one_name(self):
        with self.server.connect() as conn:
            for value in ("未分类", "旧版未分类"):
                result = self.server.fetch_knowledge_page(conn, {"content_type": [value]})
                self.assertEqual(result["total"], 1)
                self.assertEqual(result["facets"]["content_types"], {"未分类": 1})
                self.assertIsNone(result["claims"][0]["content_type"])

    def test_nullable_idempotent_migration_does_not_rewrite_old_claims(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        spec = importlib.util.spec_from_file_location("decor_context_migration", ROOT / "scripts/migrate_claim_context.py")
        migrator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migrator)
        with self.server.connect() as conn:
            before = dict(conn.execute("SELECT * FROM claims WHERE id='old'").fetchone())
            for column in ("author_stance", "content_type", "source_quotes", "field_evidence",
                           "source_scope", "scope_quote", "evidence_contract"):
                conn.execute(f"ALTER TABLE claims DROP COLUMN {column}")
        migrator.migrate(self.dsn)
        migrator.migrate(self.dsn)
        with self.server.connect() as conn:
            after = dict(conn.execute("SELECT * FROM claims WHERE id='old'").fetchone())
            self.assertEqual(before, after)
            public = self.server.fetch_knowledge_page(conn)["claims"][0]
            self.assertIsNone(public["author_stance"])
            self.assertIsNone(public["content_type"])
            self.assertEqual(public["source_quotes"], [])
            for key in ("field_evidence", "source_scope", "scope_quote", "evidence_contract"):
                self.assertIsNone(after[key])
                self.assertNotIn(key, public)
        from init_db import init_db
        self.assertFalse(init_db(self.dsn))

    def test_extraction_persists_scope_bindings_and_existing_version_lineage(self):
        for scope in ("general", "case", "personal", "comparison"):
            claim = self.claim("验收时检查插座接线。")
            quote = claim["source_quotes"][0]
            claim.update(source_scope=scope, scope_quote="" if scope == "general" else quote)
            result = self.extract_with(self.result([claim]))
            self.assertEqual(result["status"], "completed")
            with self.server.connect() as conn:
                row = conn.execute("SELECT * FROM claims WHERE deleted_at IS NULL").fetchone()
                run = conn.execute("SELECT * FROM extraction_runs WHERE id=%s", (row["extraction_run_id"],)).fetchone()
                with self.subTest(scope=scope):
                    self.assertEqual(row["source_scope"], scope)
                    self.assertEqual(row["scope_quote"], claim["scope_quote"] + "。" if scope != "general" else "")
                    self.assertEqual(row["evidence_contract"], self.server.claim_contract.VERSION)
                    self.assertEqual(row["field_evidence"], {"object_name": [0], "original_conclusion": [0],
                                                             "original_reasons.0": [0]})
                    self.assertEqual(run["video_id"], self.video_id)
                    self.assertEqual(run["prompt_version"], self.server.PROMPT_VERSION)
                    self.assertEqual(run["input_hash"], self.server.hashlib.sha256(self.old_text.encode()).hexdigest())
                    self.server.claim_contract.validate_stored_evidence(dict(row), self.old_text)
                    public = self.server.fetch_knowledge_page(conn)["claims"][0]
                    for field in ("field_evidence", "source_scope", "scope_quote", "evidence_contract"):
                        self.assertNotIn(field, public)
                        self.assertNotIn(field, result["claims"][0])

    def test_optional_pruning_persists_only_final_bindings(self):
        claim = self.claim("验收时检查插座接线。")
        payload = json.loads(self.result([claim]))
        content = json.loads(payload["choices"][0]["message"]["content"])
        content["claims"][0]["price"] = ["三百元", 2, 2]
        payload["choices"][0]["message"]["content"] = json.dumps(content)
        result = self.extract_with(json.dumps(payload))
        self.assertEqual(result["status"], "completed")
        with self.server.connect() as conn:
            row = conn.execute("SELECT * FROM claims WHERE deleted_at IS NULL").fetchone()
            self.assertEqual(row["price_info"], "未提及")
            self.assertNotIn("price_info", row["field_evidence"])
            self.server.claim_contract.validate_stored_evidence(dict(row), self.old_text)

    def test_invalid_lineage_is_rejected_before_old_cards_are_deleted(self):
        payload = json.loads(json.loads(self.result([self.claim("验收时检查插座接线。")]))["choices"][0]["message"]["content"])
        claims, _, _ = self.server.partition_claims(payload, self.old_text, require_contract=True)
        with self.server.connect() as conn:
            conn.execute("""INSERT INTO videos (id, platform, creator, title, source_url, created_at, updated_at)
                VALUES ('other-video', 'test', 'test', 'test', 'https://example.invalid/other', 1, 1)""")
            before = dict(conn.execute("SELECT * FROM claims WHERE id='old'").fetchone())
            for run_id, video_id, input_hash, prompt_version in (
                (None, self.video_id, "unused", "test"),
                ("stale", self.video_id, "stale-hash", "test"),
                ("wrong-video", "other-video", self.server.hashlib.sha256(self.old_text.encode()).hexdigest(), "test"),
                ("no-version", self.video_id, self.server.hashlib.sha256(self.old_text.encode()).hexdigest(), ""),
            ):
                if run_id:
                    conn.execute("""INSERT INTO extraction_runs
                        (id, video_id, model, prompt_version, input_hash, prompt_text, status, created_at)
                        VALUES (%s, %s, 'test', %s, %s, 'test', 'completed', 1)""",
                        (run_id, video_id, prompt_version, input_hash))
                with self.subTest(run_id=run_id), self.assertRaisesRegex(ValueError, "invalid_claim_extraction_lineage"):
                    self.server.insert_claims(conn, self.video(), run_id, claims)
                self.assertEqual(dict(conn.execute("SELECT * FROM claims WHERE id='old'").fetchone()), before)

    def test_pruned_reason_and_remaining_alternative_indexes_are_rebased_before_storage(self):
        self.old_text += "板材厚度9毫米。也可请专业人员检查。"
        with self.server.connect() as conn:
            conn.execute("UPDATE videos SET transcript_text=%s WHERE id=%s", (self.old_text, self.video_id))
        payload = json.loads(self.result([self.claim("验收时检查插座接线。")]))
        content = json.loads(payload["choices"][0]["message"]["content"])
        content["claims"][0]["reason"] = ["板材厚度9厘米", len(self.server.claim_wire.segments(self.old_text)) - 1,
                                           len(self.server.claim_wire.segments(self.old_text)) - 1]
        content["claims"][0]["alternative"] = ["也可请专业人员检查", len(self.server.claim_wire.segments(self.old_text)),
                                                len(self.server.claim_wire.segments(self.old_text))]
        payload["choices"][0]["message"]["content"] = json.dumps(content)
        result = self.extract_with(json.dumps(payload))
        self.assertEqual(result["status"], "completed")
        with self.server.connect() as conn:
            row = conn.execute("SELECT * FROM claims WHERE deleted_at IS NULL").fetchone()
            self.assertEqual(row["original_reasons"], [])
            self.assertEqual(row["alternatives"], ["也可请专业人员检查"])
            self.assertEqual(row["field_evidence"], {"object_name": [0], "original_conclusion": [0],
                                                     "alternatives.0": [1]})
            self.assertEqual(row["source_quotes"], ["装修验收时检查每个插座的接线是否安全。", "也可请专业人员检查。"])
            self.server.claim_contract.validate_stored_evidence(dict(row), self.old_text)

    def test_invalid_metadata_rolls_back_replacement(self):
        import copy
        self.extract_with(self.result([self.claim("验收时检查插座接线。")]))
        with self.server.connect() as conn:
            row = dict(conn.execute("SELECT * FROM claims WHERE deleted_at IS NULL").fetchone())
            before = [dict(item) for item in conn.execute("SELECT * FROM claims ORDER BY id").fetchall()]
            for field, value in (("field_evidence", {"original_conclusion": [42]}),
                                 ("scope_quote", "编造不存在的来源引句。"),
                                 ("source_scope", "system_recommendation"),
                                 ("evidence_contract", None)):
                bad = copy.deepcopy(row)
                bad[field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    self.server.replace_claims_and_status(conn, self.video(), row["extraction_run_id"],
                                                          [bad], "claims_extracted")
                after = [dict(item) for item in conn.execute("SELECT * FROM claims ORDER BY id").fetchall()]
                self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
