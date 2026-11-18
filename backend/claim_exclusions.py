"""Read-only, allowlisted views of stored extraction exclusions."""
import re


ISSUE_LABELS = {"transcription": "文案不清", "parameter": "参数不清", "scope": "对象或范围不清",
                "attitude": "立场不清", "evidence": "原文依据不足"}
FIELD_LABELS = {"object_name": "对象", "original_conclusion": "观点", "author_stance": "作者态度",
                "conditions": "适用条件", "price_info": "价格信息"}
RULE_LABELS = {
    "unsupported_field_numeric_detail": "数值缺少原文依据",
    "unsupported_numeric_detail": "数值缺少原文依据",
    "unsupported_certainty": "表述比原文更确定",
    "subtotal_scope_not_preserved": "局部价格被扩大为整体价格",
    "unsupported_source_title": "标题缺少原文依据",
    "source_text_not_preserved": "改写偏离原文",
    "source_negation_removed": "原文否定含义未保留",
    "unsupported_field_location": "地点缺少原文依据",
    "fragmentary_cost_opinion": "价格信息不完整",
    "quotation_size_scope_not_preserved": "价格对应范围未保留",
    "explicit_tradeoff_not_preserved": "原文提到的代价未保留",
    "explicit_condition_not_preserved": "原文适用条件未保留",
}


def field_label(value):
    if not isinstance(value, str):
        return ""
    if value in FIELD_LABELS:
        return FIELD_LABELS[value]
    match = re.fullmatch(r"(original_reasons|alternatives)\.(\d+)", value or "")
    if match:
        return ("理由" if match[1] == "original_reasons" else "替代做法") + f" {int(match[2]) + 1}"
    return ""


def describe_issue(issue):
    reason = issue.get("reason") if isinstance(issue.get("reason"), str) else ""
    code = reason.split(":", 1)[0]
    label = RULE_LABELS.get(code)
    if not label:
        label = reason[:1000] if re.search(r"[\u4e00-\u9fff]", reason) else ISSUE_LABELS.get(issue.get("type"), "未通过提取校验")
    field = field_label(issue.get("field"))
    return f"{field}：{label}" if field else label


def project_item(item, transcript):
    optional = item.get("reason") == "unsupported_optional_field"
    promotion = item.get("reason") == "promotion_related_content"
    issues = [issue for issue in item.get("issues") or [] if isinstance(issue, dict)]
    reasons = list(dict.fromkeys(describe_issue(issue) for issue in issues))
    if not reasons:
        reasons = ["关联推广产品" if promotion else "内容存在歧义或缺少原文依据"]
    legacy_claim = item.get("claim") if isinstance(item.get("claim"), dict) else {}
    legacy_quotes = legacy_claim.get("source_quotes")
    candidates = [issue.get("quote") for issue in issues] + (legacy_quotes if isinstance(legacy_quotes, list) else [])
    quotes = list(dict.fromkeys(quote for quote in candidates
                               if isinstance(quote, str) and quote.strip() and quote in transcript))
    title = item.get("object_name") or legacy_claim.get("object_name")
    return {
        "object": title if isinstance(title, str) else "",
        "action": "字段省略" if optional else "未收录",
        "reasons": reasons,
        "quotes": quotes,
    }


def fetch_records(conn, video_id):
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        video = conn.execute("SELECT id, title, transcript_text FROM videos WHERE id=%s AND deleted_at IS NULL",
                             (video_id,)).fetchone()
        if not video:
            return None
        # Match the list count: current transcript, unsuperseded runs, excluded/pending items.
        rows = conn.execute("""SELECT r.review_data FROM extraction_runs r JOIN videos v ON v.id=r.video_id
            WHERE v.id=%s AND COALESCE(r.review_data->>'superseded','false')='false'
              AND r.input_hash=encode(sha256(convert_to(COALESCE(v.transcript_text,''),'UTF8')),'hex')
            ORDER BY r.created_at DESC, r.id DESC""", (video_id,)).fetchall()
        items = [project_item(item, video["transcript_text"] or "")
                 for row in rows for item in (row["review_data"] or {}).get("items", [])
                 if isinstance(item, dict) and item.get("status") in ("pending", "excluded")]
    return {"video": {"id": video["id"], "title": video["title"]}, "total": len(items), "items": items}
