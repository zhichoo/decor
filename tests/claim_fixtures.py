"""Translate synthetic legacy fixtures to segment references; not a runtime fallback."""
import copy
import re


def wire_payload(payload, transcript, wire):
    result = copy.deepcopy(payload)
    result["extraction_contract"] = wire.VERSION
    pieces = wire.segments(transcript)

    def span(text):
        if not text or text not in transcript:
            return [99999, 99999]
        options = []
        for match in re.finditer(re.escape(text), transcript):
            covered = [piece for piece in pieces if piece["start"] < match.end() and piece["end"] > match.start()]
            options.append(covered)
        covered = min(options, key=lambda group: group[-1]["end"] - group[0]["start"])
        ids = [piece["id"] for piece in covered]
        return [ids[0], ids[-1]]

    def issues(values):
        for issue in values or []:
            issue["span"] = span(issue.pop("quote"))
            issue.setdefault("blocking", "terms" if issue.get("blocked_terms") else "source")

    for claim in result["claims"]:
        scope_quote = claim.pop("scope_quote", "")
        claim["scope_span"] = span(scope_quote) if scope_quote else None
        for field in ("statement", "condition", "price"):
            if claim.get(field) is not None:
                value = claim[field]
                claim[field] = [value["text"], *span(value["quote"])]
        for field in ("reasons", "alternatives"):
            claim[field] = [[value["text"], *span(value["quote"])] for value in claim.get(field, [])]
            if wire.VERSION == "v18":
                if len(claim[field]) > 1:
                    raise ValueError("fixture requires at most one " + field)
                claim["reason" if field == "reasons" else "alternative"] = next(iter(claim.pop(field)), None)
        issues(claim.get("review_issues"))
    issues(result.get("ambiguities"))
    for subject in result.get("promotion_context", {}).get("subjects", []):
        subject["span"] = span(subject.pop("quote"))
    return result
