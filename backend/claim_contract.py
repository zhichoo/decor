"""First-pass extraction metadata checks, not a second model or approval workflow."""
import copy
import re

VERSION = "v11"
SCOPES = ("general", "case", "personal", "comparison")
RELATIONS = ("independent", "related", "uncertain")
CONTENT_TYPES = ("选购建议", "施工做法", "验收要求", "价格信息", "个人体验", "中性说明", "其他")
LOCATIONS = {
    "卧室": ("卧室", "卧房"), "阳台": ("阳台",), "厨房": ("厨房",),
    "卫生间": ("卫生间", "厕所", "卫浴", "主卫", "次卫"), "客厅": ("客厅", "起居室"),
}


def validate(extracted, transcript, title="", known_ad=False):
    if extracted.get("extraction_contract") != VERSION:
        raise ValueError("missing_extraction_contract_" + VERSION)
    context = extracted.get("promotion_context")
    if (not isinstance(context, dict) or type(context.get("has_promotion")) is not bool
            or not isinstance(context.get("subjects"), list) or len(context["subjects"]) > 20):
        raise ValueError("invalid_promotion_context")
    if context["has_promotion"] and not context["subjects"]:
        raise ValueError("missing_promotion_subject")
    if not context["has_promotion"] and (known_ad or context["subjects"]):
        raise ValueError("promotion_context_conflict")
    for subject in context["subjects"]:
        if (not isinstance(subject, dict) or not isinstance(subject.get("name"), str) or not subject["name"].strip()
                or not isinstance(subject.get("quote"), str) or len(subject["quote"].strip()) < 6
                or not (subject["quote"] in transcript or subject["quote"] in title)):
            raise ValueError("invalid_promotion_evidence")
    claims = extracted.get("claims")
    if not isinstance(claims, list) or len(claims) > 100:
        raise ValueError("invalid_claims_shape")
    ids = set()
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("invalid_claim_type")
        key = claim.get("claim_id")
        if not isinstance(key, str) or not re.fullmatch(r"c[1-9][0-9]{0,2}", key) or key in ids:
            raise ValueError("invalid_or_duplicate_claim_id")
        ids.add(key)
        if claim.get("promotion_relation") not in RELATIONS or claim.get("source_scope") not in SCOPES:
            raise ValueError("missing_claim_boundaries")
        quote = claim.get("scope_quote")
        if not isinstance(quote, str) or (quote and quote not in transcript):
            raise ValueError("invalid_scope_evidence")
        if claim["source_scope"] != "general" and len(quote.strip()) < 6:
            raise ValueError("missing_scope_evidence")
        if claim.get("author_stance") not in ("赞成", "反对", "中性陈述", "未明确"):
            raise ValueError("missing_claim_context")
        if claim.get("content_type") not in CONTENT_TYPES:
            raise ValueError("invalid_claim_context")
        if any(name in claim and (not isinstance(claim[name], list) or any(not isinstance(value, str) for value in claim[name]))
               for name in ("original_reasons", "alternatives")):
            raise ValueError("invalid_claim_field")
        validate_field_evidence(claim, transcript)
    for issue in extracted.get("ambiguities") or []:
        refs = issue.get("affected_claim_ids") if isinstance(issue, dict) else None
        if not isinstance(refs, list) or any(not isinstance(key, str) or key not in ids for key in refs):
            raise ValueError("invalid_ambiguity_claim_reference")
    for issue in [*(extracted.get("ambiguities") or []),
                  *(issue for claim in claims for issue in (claim.get("review_issues") or []))]:
        validate_blocked_terms(issue)
    return context


def field_values(claim):
    values = {}
    for name in ("object_name", "original_conclusion", "conditions", "price_info"):
        text = claim.get(name)
        if isinstance(text, str) and text.strip() not in ("", "未提及"):
            values[name] = text
    for name in ("original_reasons", "alternatives"):
        for index, text in enumerate(claim.get(name) or []):
            if isinstance(text, str) and text.strip() not in ("", "未提及"):
                values[f"{name}.{index}"] = text
    return values


def validate_field_evidence(claim, transcript):
    quotes, bindings = claim.get("source_quotes"), claim.get("field_evidence")
    if (not isinstance(quotes, list) or not 1 <= len(quotes) <= 3
            or any(not isinstance(q, str) or len(q.strip()) < 6 or q not in transcript for q in quotes)):
        raise ValueError("quality_check_failed")
    if not isinstance(bindings, dict) or set(bindings) != set(field_values(claim)):
        raise ValueError("incomplete_field_evidence")
    for refs in bindings.values():
        if (not isinstance(refs, list) or not refs or len(refs) != len(set(ref for ref in refs if type(ref) is int))
                or any(type(ref) is not int or not 0 <= ref < len(quotes) for ref in refs)):
            raise ValueError("invalid_field_evidence_reference")
    if set(ref for refs in bindings.values() for ref in refs) != set(range(len(quotes))):
        raise ValueError("unused_source_evidence")


def validate_stored_evidence(claim, transcript):
    """Check durable attribution without interpreting it as factual verification."""
    if claim.get("evidence_contract") != VERSION:
        raise ValueError("unsupported_evidence_contract")
    validate_field_evidence(claim, transcript)
    if claim.get("source_scope") not in SCOPES:
        raise ValueError("missing_claim_boundaries")
    quote = claim.get("scope_quote")
    if not isinstance(quote, str) or (quote and quote not in transcript):
        raise ValueError("invalid_scope_evidence")
    if claim["source_scope"] != "general" and len(quote.strip()) < 6:
        raise ValueError("missing_scope_evidence")


def validate_blocked_terms(issue):
    terms = issue.get("blocked_terms") if isinstance(issue, dict) else None
    if (not isinstance(terms, list) or len(terms) > 10
            or any(not isinstance(term, str) or len(term.strip()) < 2 or term not in issue.get("quote", "") for term in terms)):
        raise ValueError("invalid_ambiguity_blocked_terms")


def dependency_issues(claim, issues):
    # Restrict propagation to this response, never a permanent cross-video word blacklist.
    values = field_values(claim)
    result = []
    for issue in issues:
        quotes, bindings = claim.get("source_quotes") or [], claim.get("field_evidence") or {}
        lexical_fields = [field for field, text in values.items()
                          if any(term in text or (issue.get("blocking") == "source" and
                                                  any(term in quotes[ref] for ref in bindings.get(field, [])
                                                      if type(ref) is int and 0 <= ref < len(quotes)))
                                 for term in issue.get("blocked_terms", []))]
        source_range = issue.get("source_range") if issue.get("blocking") == "source" else None
        fields = [field for field, span in (claim.get("evidence_spans") or {}).items()
                  if source_range and max(span[0], source_range[0]) < min(span[1], source_range[1])]
        fields = sorted(set(fields + lexical_fields))
        if fields:
            result.append({**issue, "source": "dependency", "fields": fields})
    return result


def literal_title_supported(title, evidence):
    compact = lambda text: re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return isinstance(title, str) and 2 <= len(title.strip()) <= 24 and compact(title) in compact(evidence) and bool(compact(title))


def title_supported(claim, evidence):
    # A heading can name the claim as written; it must not add an extra action.
    title = claim.get("object_name")
    return (literal_title_supported(title, evidence)
            or literal_title_supported(title, claim.get("original_conclusion") or ""))


def prune_optional_fields(claim, fields):
    result = copy.deepcopy(claim)
    spans = result.get("evidence_spans", {})
    bindings = result["field_evidence"]
    if "price_info" in fields:
        result["price_info"] = "未提及"
        bindings.pop("price_info", None)
        spans.pop("price_info", None)
    for name in ("original_reasons", "alternatives"):
        kept, refs, kept_spans = [], [], []
        for index, text in enumerate(result.get(name) or []):
            key = f"{name}.{index}"
            binding = bindings.pop(key, None)
            span = spans.pop(key, None)
            if key not in fields:
                kept.append(text)
                refs.append(binding)
                kept_spans.append(span)
        if name in result:
            result[name] = kept
        for index, binding in enumerate(refs):
            if binding is not None:
                bindings[f"{name}.{index}"] = binding
        for index, span in enumerate(kept_spans):
            if span is not None:
                spans[f"{name}.{index}"] = span
    used = sorted({ref for refs in bindings.values() for ref in refs})
    renumber = {old: new for new, old in enumerate(used)}
    result["source_quotes"] = [result["source_quotes"][ref] for ref in used]
    result["field_evidence"] = {name: [renumber[ref] for ref in refs] for name, refs in bindings.items()}
    return result


def linked_issues(raw, issues):
    # Term-based ASR issues use dependencies; a noisy subclause alone must not erase a clear neighbor.
    quotes = raw.get("source_quotes")
    quotes = quotes if isinstance(quotes, list) else []
    return [issue for issue in issues if raw.get("claim_id") in issue.get("affected_claim_ids", [])
            or ("blocking" not in issue and not issue.get("affected_claim_ids") and (issue["quote"] in quotes
                or (not issue.get("blocked_terms") and any(issue["quote"] in quote for quote in quotes))))]


def attributed(claim):
    result = dict(claim)
    conclusion = result["original_conclusion"]
    scope = result.get("source_scope")
    markers = {
        "case": (r"该.*(?:案例|施工方|酒店)|视频.*(?:案例|施工方|酒店)", "该视频案例中，"),
        "personal": (r"作者.*(?:自家|个人|本次|经历|使用)|自家|个人体验", "作者根据个人经历认为，"),
        "comparison": (r"作者.*(?:比较|对比)|相比|相较", "作者比较认为，"),
    }
    if scope in markers:
        pattern, prefix = markers[scope]
        if not re.search(pattern, conclusion):
            result["original_conclusion"] = prefix + conclusion
    elif result.get("price_info") not in (None, "", "未提及") and not re.search(r"作者|视频|案例|报价", conclusion):
        result["original_conclusion"] = "作者给出的报价中，" + conclusion
    return result


def duplicate_key(claim):
    def compact(value):
        # Keep decimals, ratios and ranges distinct; punctuation is not all cosmetic.
        return re.sub(r"\s+", "", str(value or "")).rstrip("。.! ").lower()
    return (compact(claim.get("original_conclusion")), compact(claim.get("conditions")),
            claim.get("author_stance"), claim.get("source_scope"), compact(claim.get("price_info")),
            tuple(compact(value) for value in claim.get("original_reasons") or []),
            tuple(compact(value) for value in claim.get("alternatives") or []))
