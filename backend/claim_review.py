"""Conservative ambiguity signals; these are not transcript correction or fact checks."""
import re


# Known high-risk ASR fragments from sample review. Never silently replace them.
ASR_FRAGMENTS = ("除卫空调", "散店官网", "深管接缝", "做泥包贴")
BROKEN_MEASUREMENT = re.compile(r"(?:[零一二两三四五六七八九十\d]+的(?:毫米|厘米|公分|米)|[一二两三四五六七八九]\.\d|[一二两三四五六七八九]\d+万)")
ISSUE_TYPES = ("transcription", "parameter", "scope", "attitude", "evidence")
GENERIC_PURCHASE = re.compile(
    r"(?:买|选|选用|用)?(?:好)?"
    r"(?:大品牌|知名品牌|品牌|太贵的|贵的|便宜的|好的|质量好的|杂牌子?|品牌货)"
    r"(?:就行|即可|没毛病|最好|更好|比较好|更靠谱)?$"
)
BARE_EVALUATION = re.compile(
    r"(?:非常|真的|很|挺|比较|更|太)?"
    r"(?:好用|实用|舒服|好看|美观|省事|不错|有必要|没毛病|值得买|性价比高|节能|防水|防潮|耐用)"
    r"(?:了|啊)?$|不实用(?:，)?不要做$"
)
EFFECT_ONLY = re.compile(
    r"^(?:窗户|热水|冰块|吹头发|洗脸|洗脸巾|特饮|鞋子|衣服|回家|睡觉|出门|拖地|洗澡|做饭)"
    r"[^。！？!?]{0,12}(?:不用|无需|不必|不需要|不会|可随时|可轻松|自动)"
    r"(?:自己|提前|动手|手动|弯腰|摸黑|晾|叠|烧|擦|拿|冷冻|清洁|换|关|开|做|喝|拖地)?"
)
ACTION_CUE = re.compile(
    r"安装|铺贴|铺设|预留|留出|检查|测量|清理|清洁|刷|打胶|施工|固定|连接|设置|控制|"
    r"更换|采用|处理|测试|验收|留缝|间距|高度|宽度|厚度|数量"
)
SPECIFIC_BRANDS = re.compile(
    r"海尔|美的|九牧|恒洁|箭牌|金杯|远东|雨虹|奥普|潜水艇|方太|老板|华帝|沁园|安吉尔|"
    r"美巢|美超|莱斯|日丰|伟星|飞雨|杜拉维特|科勒|TOTO|西门子|施耐德|公牛|正泰|德力西"
)


def low_information_kind(claim):
    """Find only clear effect-only or generic advice; absence here is not a quality pass."""
    conclusion = re.sub(r"\s+", "", claim.get("original_conclusion") or "")
    if not conclusion:
        return None
    supported = (
        any(str(value or "").strip() not in ("", "未提及") for value in claim.get("original_reasons") or [])
        or any(str(value or "").strip() not in ("", "未提及") for value in claim.get("alternatives") or [])
        or str(claim.get("conditions") or "").strip() not in ("", "未提及")
        or str(claim.get("price_info") or "").strip() not in ("", "未提及")
        or bool(re.search(r"\d|毫米|厘米|公分|平方米|小时|分钟|块钱|万元", conclusion))
    )
    if supported:
        return None
    clauses = [part for part in re.split(r"[，,。；;！？!?]", conclusion) if part]
    if (len(clauses) == 2 and re.fullmatch(r"(?:又|也)?(?:好|省|方便|安全|结实|耐用)", clauses[0])
            and re.fullmatch(r"(?:又|也)?(?:好|看|美观|实用|舒服|省事|耐用|防潮|防水|节能)", clauses[1])):
        return "bare_evaluation"
    if EFFECT_ONLY.search(conclusion):
        non_effect_clauses = [part for part in clauses if not EFFECT_ONLY.search(part)]
        if not any(ACTION_CUE.search(part) for part in non_effect_clauses):
            return "effect_only"
    compact = re.sub(r"[\s，,。！!、；;：:]", "", conclusion)
    purchase = re.sub(
        r"^(?:买|选|选用|用)?[^，,。！？!?]{0,8}?"
        r"(?:可|要|应该|建议|推荐|必须|最好|可以|直接|不必|不用|不要|别)?"
        r"(?:选择|选用|选|买|用|追求)?", "", compact)
    if len(compact) <= 30 and GENERIC_PURCHASE.search(purchase) and not SPECIFIC_BRANDS.search(compact):
        return "generic_purchase_advice"
    evidence = re.sub(r"\s+", "", " ".join(
        quote for quote in claim.get("source_quotes") or [] if isinstance(quote, str)))
    # Subjective wording alone is not enough to reject an otherwise actionable inspection or sizing card.
    if (ACTION_CUE.search(compact) or re.search(r"\d|毫米|厘米|公分|米|宽|窄|厚|薄", compact)
            or (evidence and (ACTION_CUE.search(evidence) or "检查" in evidence))):
        return None
    if len(compact) <= 20 and BARE_EVALUATION.search(compact):
        return "bare_evaluation"
    return None


def model_issues(value, transcript):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("invalid_review_issues")
    issues = []
    for item in value:
        if (not isinstance(item, dict) or item.get("type") not in ISSUE_TYPES
                or not isinstance(item.get("quote"), str) or not item["quote"].strip()
                or item["quote"] not in transcript
                or not isinstance(item.get("reason"), str) or not item["reason"].strip()):
            raise ValueError("invalid_review_evidence")
        issue = {"type": item["type"], "quote": item["quote"],
                 "reason": item["reason"][:1000], "source": "model"}
        if "affected_claim_ids" in item:
            refs = item["affected_claim_ids"]
            if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                raise ValueError("invalid_ambiguity_claim_reference")
            issue["affected_claim_ids"] = refs
        if "blocked_terms" in item:
            terms = item["blocked_terms"]
            if (not isinstance(terms, list) or len(terms) > 10
                    or any(not isinstance(term, str) or len(term.strip()) < 2 or term not in item["quote"] for term in terms)):
                raise ValueError("invalid_ambiguity_blocked_terms")
            issue["blocked_terms"] = terms
        if "blocking" in item:
            if item["blocking"] not in ("source", "terms"):
                raise ValueError("invalid_ambiguity_blocking")
            span = item.get("source_range")
            if (not isinstance(span, list) or len(span) != 2 or any(type(ref) is not int for ref in span)
                    or not 0 <= span[0] < span[1] <= len(transcript) or transcript[span[0]:span[1]] != item["quote"]):
                raise ValueError("invalid_ambiguity_source_range")
            issue["blocking"] = item["blocking"]
            issue["source_range"] = span[:]
        issues.append(issue)
    return issues


MATERIAL_MEASUREMENT = re.compile(
    r"(?P<value>[零一二两三四五六七八九十百\d]+(?:[.点][零一二两三四五六七八九\d]+)?)"
    r"\s*(?P<unit>毫米|厘米|公分|mm|cm)\s*(?:的)?\s*"
    r"(?P<material>欧松板|石膏板|木板|多层板|水泥板|密度板|铝板|钢板|玻璃)", re.IGNORECASE)
DIMENSION = re.compile(r"厚|宽|长|高|直径|间距|深")


def measurement_issues(claim, numbers=None):
    text = "\n".join([claim.get("object_name") or "", claim.get("original_conclusion") or "",
                       *(claim.get("original_reasons") or []), *(claim.get("alternatives") or []),
                       claim.get("conditions") or "", claim.get("price_info") or ""])
    issues = []
    for quote in claim.get("source_quotes") or []:
        for match in MATERIAL_MEASUREMENT.finditer(quote):
            before = quote[max(0, match.start() - 4):match.start()]
            if DIMENSION.search(before):
                continue
            # Missing dimension is relevant only if the card actually retains the measurement.
            compact = re.sub(r"\s+", "", text)
            retains_value = match["value"] + match["unit"] in compact
            if numbers is not None:
                value = numbers(match["value"] + match["unit"])
                retains_value = bool(value) and value.issubset(numbers(text))
            if match["material"] in compact and retains_value:
                issues.append({"type": "parameter", "quote": quote,
                               "reason": "材料尺寸未说明厚度、宽度等参数含义，不能直接生成可执行规格。",
                               "source": "rule", "blocked_terms": [match.group().strip()]})
    return issues


def rule_issues(claim):
    issues = []
    quotes = claim.get("source_quotes")
    for quote in quotes if isinstance(quotes, list) else []:
        if not isinstance(quote, str):
            continue
        if any(fragment in quote for fragment in ASR_FRAGMENTS):
            issues.append({"type": "transcription", "quote": quote,
                           "reason": "包含已知高风险转写片段，对象或做法无法可靠提取，不收录。", "source": "rule"})
        if BROKEN_MEASUREMENT.search(quote):
            issues.append({"type": "parameter", "quote": quote,
                           "reason": "参数表达断裂，不能自动补全数值或单位。", "source": "rule"})
    return issues
