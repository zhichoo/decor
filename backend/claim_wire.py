"""Small model-facing format; evidence indexes are generated, never guessed."""
import copy
import re

VERSION = "v18"
MAX_SEGMENT_CHARS = 120
MAX_SPAN_CHARS = 480
MAX_SPAN_SEGMENTS = 16


def segments(transcript, *, clauses=True):
    """Partition raw text with stable offsets; never normalize whitespace or punctuation."""
    pattern = r"[。！？!?；;\n]+|，|(?<!\d),(?!\d)" if clauses else r"[。！？!?；;\n]+"
    boundaries = [match.end() for match in re.finditer(pattern, transcript)]
    if not boundaries or boundaries[-1] != len(transcript):
        boundaries.append(len(transcript))
    result, start = [], 0
    for boundary in boundaries:
        while start < boundary:
            end = min(start + MAX_SEGMENT_CHARS, boundary)
            if end < boundary:
                comma = max(transcript.rfind(char, start + MAX_SEGMENT_CHARS // 2, end)
                            for char in "，,、 ")
                if comma >= 0:
                    end = comma + 1
            result.append({"id": len(result) + 1, "start": start, "end": end, "text": transcript[start:end]})
            start = end
    return result


def prompt_segments(transcript):
    """Expose legal end-ID bounds without changing evidence or repairing model output."""
    pieces = segments(transcript)
    result = []
    for index, piece in enumerate(pieces):
        valid = []
        for last in pieces[index:index + MAX_SPAN_SEGMENTS]:
            text = transcript[piece["start"]:last["end"]]
            if len(text.strip()) > MAX_SPAN_CHARS:
                break
            if len(re.sub(r"[\W_]+", "", text)) >= 6:
                valid.append(last["id"])
        result.append({"id": piece["id"], "text": piece["text"],
                       "allowed_last": [valid[0], valid[-1]] if valid else None})
    return result


def normalize(payload, transcript, title=""):
    if not isinstance(payload, dict) or payload.get("extraction_contract") != VERSION:
        raise ValueError("missing_extraction_contract_" + VERSION)
    return _normalize_segments(payload, transcript, title, source_dependencies=True, clauses=True)


def normalize_historical(payload, transcript, title=""):
    """Explicit offline reader; never accepted by the production entry point."""
    if isinstance(payload, dict) and payload.get("extraction_contract") in ("v14", "v16", "v17"):
        return _normalize_segments(payload, transcript, title,
                                   source_dependencies=payload["extraction_contract"] in ("v16", "v17"),
                                   clauses=payload["extraction_contract"] == "v17")
    return normalize_legacy(payload, transcript)


def _normalize_segments(payload, transcript, title, *, source_dependencies, clauses):
    modern = payload.get("extraction_contract") == VERSION
    pieces = segments(transcript, clauses=clauses)

    def quote(span, *, allow_title=False):
        if (not isinstance(span, list) or len(span) != 2 or any(type(ref) is not int for ref in span)):
            raise ValueError("invalid_evidence_span")
        first, last = span
        if allow_title and first == last == 0 and len(title.strip()) >= 6:
            return title
        limit = MAX_SPAN_SEGMENTS if clauses else 8
        if not 1 <= first <= last <= len(pieces) or last - first + 1 > limit:
            raise ValueError("invalid_evidence_span")
        text = transcript[pieces[first - 1]["start"]:pieces[last - 1]["end"]]
        if not 6 <= len(text.strip()) <= MAX_SPAN_CHARS:
            raise ValueError("evidence_span_size")
        return text

    def pair(value, field):
        if value is None:
            return None
        if not isinstance(value, list) or len(value) != 3 or not isinstance(value[0], str):
            raise ValueError("invalid_evidence_pair:" + field)
        return {"text": value[0], "quote": quote(value[1:])}

    def issues(values):
        if values is None:
            return None
        if not isinstance(values, list) or len(values) > 20:
            raise ValueError("invalid_review_issues")
        result = []
        for issue in values:
            if not isinstance(issue, dict) or "quote" in issue:
                raise ValueError("invalid_review_evidence")
            item = copy.deepcopy(issue)
            span = item.pop("span", None)
            item["quote"] = quote(span)
            if source_dependencies:
                if set(item) - {"type", "quote", "reason", "blocked_terms", "blocking", "affected_claim_ids"}:
                    raise ValueError("invalid_review_evidence")
                if item.get("blocking") not in ("source", "terms"):
                    raise ValueError("missing_ambiguity_blocking")
                if clauses and item.get("type") == "parameter" and item["blocking"] != "source":
                    raise ValueError("parameter_requires_source_blocking")
                if item["blocking"] == "source":
                    item.setdefault("blocked_terms", [])
                elif not item.get("blocked_terms"):
                    raise ValueError("missing_ambiguity_blocked_terms")
                item["source_range"] = [pieces[span[0] - 1]["start"], pieces[span[1] - 1]["end"]]
            result.append(item)
        return result

    claims = payload.get("claims")
    if not isinstance(claims, list) or len(claims) > 40:
        raise ValueError("invalid_claims_shape")
    converted = copy.deepcopy(payload)
    converted["extraction_contract"] = "v12"
    converted["ambiguities"] = issues(payload.get("ambiguities")) or []
    context = converted.get("promotion_context")
    if not isinstance(context, dict) or not isinstance(context.get("subjects"), list):
        raise ValueError("invalid_promotion_context")
    for subject in context["subjects"]:
        if not isinstance(subject, dict) or "quote" in subject:
            raise ValueError("invalid_promotion_evidence")
        subject["quote"] = quote(subject.pop("span", None), allow_title=True)
    converted["claims"] = []
    allowed = {"object_name", "author_stance", "content_type", "process_stage", "space_tags", "topic_tags",
               "source_scope", "scope_span", "promotion_relation", "review_issues", "statement", "condition",
               "price", "reasons", "alternatives"}
    if modern:
        allowed = (allowed - {"reasons", "alternatives"}) | {"reason", "alternative"}
    ranges = []
    for raw in claims:
        if not isinstance(raw, dict):
            raise ValueError("invalid_claim_type")
        if set(raw) - allowed:
            raise ValueError("mixed_extraction_contract")
        claim = copy.deepcopy(raw)
        scope_span = claim.pop("scope_span", None)
        claim["scope_quote"] = "" if scope_span is None else quote(scope_span)
        for field in ("statement", "condition", "price"):
            claim[field] = pair(raw.get(field), field)
        list_values = {}
        for field, single in (("reasons", "reason"), ("alternatives", "alternative")):
            if modern:
                value = pair(raw.get(single), single)
                claim.pop(single, None)
                claim[field] = [] if value is None else [value]
                list_values[field] = [] if value is None else [raw[single]]
                continue
            values = raw.get(field, [])
            if not isinstance(values, list) or len(values) > 2:
                raise ValueError("invalid_evidence_list:" + field)
            claim[field] = [pair(value, field) for value in values]
            list_values[field] = values
        if "review_issues" in raw:
            claim["review_issues"] = issues(raw["review_issues"])
        converted["claims"].append(claim)
        bindings = {}
        for field, value in (("original_conclusion", raw.get("statement")), ("conditions", raw.get("condition")),
                             ("price_info", raw.get("price")),
                             *((f"original_reasons.{i}", value) for i, value in enumerate(list_values["reasons"])),
                             *((f"alternatives.{i}", value) for i, value in enumerate(list_values["alternatives"]))):
            if value is not None:
                bindings[field] = [pieces[value[1] - 1]["start"], pieces[value[2] - 1]["end"]]
        if "original_conclusion" in bindings:
            bindings["object_name"] = bindings["original_conclusion"][:]
        ranges.append(bindings)
    normalized = normalize_legacy(converted, transcript)
    if source_dependencies:
        for claim, bindings in zip(normalized["claims"], ranges):
            claim["evidence_spans"] = bindings
            if modern:
                claim["source_title_mode"] = "grounded_excerpt"
            elif clauses:
                claim["source_text_mode"] = "deletion_only"
    return normalized


def normalize_legacy(payload, transcript):
    """Read historical v12 responses offline; production must use normalize()."""
    if not isinstance(payload, dict) or payload.get("extraction_contract") != "v12":
        raise ValueError("missing_extraction_contract_v12")
    claims = payload.get("claims")
    if not isinstance(claims, list) or len(claims) > 100:
        raise ValueError("invalid_claims_shape")
    result = copy.deepcopy(payload)
    result["extraction_contract"] = "v11"  # Internal validator, not the model-facing protocol.
    result["claims"] = []
    for index, raw in enumerate(claims, 1):
        if not isinstance(raw, dict):
            raise ValueError("invalid_claim_type")
        if any(key in raw for key in ("claim_id", "source_quotes", "field_evidence", "original_conclusion",
                                      "original_reasons", "conditions", "price_info")):
            raise ValueError("mixed_extraction_contract")
        claim = {key: copy.deepcopy(raw[key]) for key in (
            "object_name", "author_stance", "content_type", "process_stage", "space_tags", "topic_tags",
            "source_scope", "scope_quote", "promotion_relation", "review_issues") if key in raw}
        claim.update(claim_id=f"c{index}", source_quotes=[], field_evidence={})

        def pair(value, field, required=False):
            if value is None and not required:
                return "未提及"
            if (not isinstance(value, dict) or set(value) != {"text", "quote"}
                    or not isinstance(value["text"], str)):
                raise ValueError("invalid_evidence_pair:" + field)
            quote = value["quote"]
            if not isinstance(quote, str) or len(quote.strip()) < 6 or quote not in transcript:
                raise ValueError("quality_check_failed")
            if quote not in claim["source_quotes"]:
                claim["source_quotes"].append(quote)
            if value["text"].strip() not in ("", "未提及"):
                claim["field_evidence"][field] = [claim["source_quotes"].index(quote)]
            elif field != "original_conclusion":
                raise ValueError("invalid_evidence_pair:" + field)
            return value["text"]

        claim["original_conclusion"] = pair(raw.get("statement"), "original_conclusion", required=True)
        claim["field_evidence"]["object_name"] = [0]
        claim["conditions"] = pair(raw.get("condition"), "conditions")
        claim["price_info"] = pair(raw.get("price"), "price_info")
        for wire_name, name in (("reasons", "original_reasons"), ("alternatives", "alternatives")):
            values = raw.get(wire_name, [])
            if not isinstance(values, list) or len(values) > 3:
                raise ValueError("invalid_evidence_list:" + wire_name)
            claim[name] = [pair(value, f"{name}.{i}", required=True) for i, value in enumerate(values)]
        if len(claim["source_quotes"]) > 3:
            raise ValueError("too_many_source_quotes")
        result["claims"].append(claim)
    for issue in result.get("ambiguities") or []:
        if isinstance(issue, dict):
            issue.setdefault("affected_claim_ids", [])
    return result
