"""Source-attributed claims: no invented context, persistent quotes, legacy compatibility."""
import importlib.util
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
                     "不能推导", "不生成个性化推荐分数", "背景不自动等于适用限制", "个人感受"):
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
            self.assertEqual(stored["source_quotes"], claim["source_quotes"])
            self.assertEqual(stored["author_stance"], "中性陈述")
            self.assertEqual(stored["stance"], "未明确")

    def test_nullable_idempotent_migration_does_not_rewrite_old_claims(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        spec = importlib.util.spec_from_file_location("decor_context_migration", ROOT / "scripts/migrate_claim_context.py")
        migrator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migrator)
        with self.server.connect() as conn:
            before = dict(conn.execute("SELECT * FROM claims WHERE id='old'").fetchone())
            for column in ("author_stance", "content_type", "source_quotes"):
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
        from init_db import init_db
        self.assertFalse(init_db(self.dsn))


if __name__ == "__main__":
    unittest.main()
