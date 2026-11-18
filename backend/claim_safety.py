"""Deterministic first-pass guards, not factual or unrestricted semantic verification."""
import re
import unicodedata
from decimal import Decimal


NUMBER = r"(?:[-+]?\d+(?:\.\d+)?(?:亿|万|千)?|负?[零〇一二两三四五六七八九十百千万亿]+(?:点[零〇一二三四五六七八九]+)?)"
UNIT = (r"毫米|厘米|公分|千米|公里|平方米|平方厘米|平方毫米|平米|平方|平|"
        r"万元|千元|亿元|元|块钱|块|小时|分钟|秒钟|秒|天|个月|月|年|"
        r"千瓦|瓦|毫升|升|毫米|米|遍|层|个|条|扇|级|成|%|㎡|mm|cm|km|m²|m2|m|kW|W|ml|L")
QUANTITY = re.compile(r"(?P<number>" + NUMBER + r")\s*(?P<unit>" + UNIT + r")", re.I)
PERCENT = re.compile(r"百分之(?P<number>" + NUMBER + r")")
UNITS = {
    "毫米": ("length", "1"), "mm": ("length", "1"), "厘米": ("length", "10"),
    "公分": ("length", "10"), "cm": ("length", "10"), "米": ("length", "1000"),
    "m": ("length", "1000"), "千米": ("length", "1000000"), "公里": ("length", "1000000"), "km": ("length", "1000000"),
    "平方米": ("area", "1"), "平米": ("area", "1"), "平方": ("area", "1"), "平": ("area", "1"),
    "㎡": ("area", "1"), "m²": ("area", "1"), "m2": ("area", "1"),
    "平方厘米": ("area", ".0001"), "平方毫米": ("area", ".000001"),
    "元": ("money", "1"), "块": ("money", "1"), "块钱": ("money", "1"),
    "万元": ("money", "10000"), "千元": ("money", "1000"), "亿元": ("money", "100000000"),
    "秒": ("duration", "1"), "秒钟": ("duration", "1"), "分钟": ("duration", "60"), "小时": ("duration", "3600"),
    "天": ("duration", "86400"), "个月": ("month", "1"), "月": ("month", "1"), "年": ("month", "12"),
    "瓦": ("power", "1"), "w": ("power", "1"), "千瓦": ("power", "1000"), "kw": ("power", "1000"),
    "毫升": ("volume", "1"), "ml": ("volume", "1"), "升": ("volume", "1000"), "l": ("volume", "1000"),
    "%": ("ratio", ".01"), "成": ("ratio", ".1"),
}
ROLES = {"厚": "厚度", "厚度": "厚度", "宽": "宽度", "宽度": "宽度", "高": "高度", "高度": "高度",
         "长": "长度", "长度": "长度", "深": "深度", "深度": "深度", "间距": "间距", "直径": "直径",
         "单价": "单价", "总价": "总价"}
ROLE = re.compile(r"厚度|宽度|高度|长度|深度|间距|直径|单价|总价|厚|宽|高|长|深")


def number_value(text, numbers):
    match = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)(亿|万|千)?", text)
    if match:
        return Decimal(match[1]) * {None: 1, "千": 1000, "万": 10000, "亿": 100000000}[match[2]]
    values = numbers(text.removeprefix("负") + "元")
    return next(iter(values)) * (-1 if text.startswith("负") else 1) if len(values) == 1 else None


def quantities(text, numbers):
    text = unicodedata.normalize("NFKC", text or "")
    matches = []
    for match in PERCENT.finditer(text):
        matches.append((match, "ratio", Decimal(".01")))
    for match in QUANTITY.finditer(text):
        if any(start.start() <= match.start() < start.end() for start, _, _ in matches):
            continue
        unit = match["unit"].lower()
        kind, scale = UNITS.get(unit, ("count:" + unit, "1"))
        matches.append((match, kind, Decimal(scale)))
    result = []
    for match, kind, scale in sorted(matches, key=lambda item: item[0].start()):
        if result and match.start() < result[-1]["end"]:
            continue
        value = number_value(match["number"], numbers)
        prefix = re.split(r"[，,。；;！？!?\n]", text[:match.start()])[-1][-16:]
        roles = list(ROLE.finditer(prefix)) if kind in ("length", "money") else []
        role = ROLES[roles[-1].group()] if roles else None
        # A bare adjective far from the value is not a dimension label.
        if roles and len(roles[-1].group()) == 1 and roles[-1].end() < len(prefix) - 5:
            role = None
        suffix = text[match.end():]
        if kind == "length" and not role:
            trailing_role = re.match(r"(?:的)?(厚度|宽度|高度|长度|深度|间距|直径|厚|宽|高|长|深)", suffix)
            if trailing_role:
                role = ROLES[trailing_role[1]]
        denominator = None
        rate = re.match(r"\s*(?:/|每|一)\s*(平方米|平米|平方|平|米|小时|天|个|遍)", suffix) if kind == "money" else None
        preceding_rate = re.search(r"每(平方米|平米|平方|平|米|小时|天|个|遍)\s*$", text[:match.start()]) if kind == "money" else None
        if rate or preceding_rate:
            unit = (rate or preceding_rate)[1]
            denominator = {"平方米": "area", "平米": "area", "平方": "area", "平": "area"}.get(unit, unit)
            role = role or "单价"
        result.append({"value": value * scale if value is not None else None, "kind": kind,
                       "role": role, "denominator": denominator, "text": match.group(),
                       "raw_number": match["number"], "scale": scale,
                       "start": match.start(), "end": match.end() + (rate.end() if rate else 0)})
    return text, result


def numeric_errors(text, evidence, numbers):
    normalized, output = quantities(text, numbers)
    _, source = quantities(evidence, numbers)
    errors = []
    for item in output:
        supported = any(
            (item["kind"], item["value"], item["denominator"]) == (q["kind"], q["value"], q["denominator"])
            and (item["value"] is not None or (item["raw_number"], item["scale"]) == (q["raw_number"], q["scale"]))
            and (not item["role"] or item["role"] == q["role"]) for q in source)
        if not supported:
            errors.append("unsupported_quantity:" + item["text"])
    remainder = normalized
    for item in reversed(output):
        remainder = remainder[:item["start"]] + " " + remainder[item["end"]:]
    if not numbers(remainder).issubset(numbers(evidence)):
        errors.append("unsupported_numeric_value")
    for match in re.finditer(r"占(?:比)?(?:是|为)?\s*(?P<value>\d+(?:\.\d+)?)", normalized):
        tail = normalized[match.end():]
        if not re.match(r"\s*(?:" + UNIT + r"|[/:：]|分之)", tail, re.I):
            errors.append("missing_allocation_unit:" + match.group())
    # A verbatim ASR number is still unusable when a dimension has lost its unit.
    for match in re.finditer(
        r"(?:留缝|缝宽|缝隙宽度|厚度|宽度|高度|间距)"
        r"(?:\s|必须|至少|最多|保持|做到|控制在|不超过|约|为|是|要|在)*"
        r"\d+(?:\.\d+)?(?=\s*(?:左右|上下)?\s*(?:[，,。；;！？!?]|$))", normalized
    ):
        errors.append("missing_measurement_unit:" + match.group())
    return errors


def certainty_errors(text, evidence):
    """Reject explicit strengthening, not general paraphrases or factual claims."""
    strong = r"保证|确保|绝对|必定|一定|才能"
    if re.search(strong, text) and not re.search(strong, evidence):
        return ["unsupported_certainty"]
    return []


def vague_cost_fragment(claim):
    text = claim.get("original_conclusion") or ""
    match = re.fullmatch(r"(?P<action>[^，,。；;]{2,20})[，,](?:费用|价格|成本)(?:确实|很|比较|会|就|太)*(?:高|贵|低|便宜)[。！!]?", text)
    if not match or claim.get("original_reasons") or claim.get("alternatives"):
        return False
    if claim.get("price_info") not in (None, "", "未提及"):
        return False
    condition = claim.get("conditions") or "未提及"
    return condition == "未提及" or condition.strip("，,。 ") == match["action"]


def source_text_key(text, numbers):
    normalized, values = quantities(text, numbers)
    for item in reversed(values):
        if item["value"] is not None:
            token = f"[{item['kind']}:{item['value'].normalize()}]"
            normalized = normalized[:item["start"]] + token + normalized[item["end"]:]
    return re.sub(r"[^\w<>=%\[\]:.-]", "", normalized).lower()


def source_rewrite_errors(text, evidence, numbers):
    """Allow deletion, not invented words; this alone cannot prove preserved meaning."""
    output, source = source_text_key(text, numbers), source_text_key(evidence, numbers)
    cursor = iter(source)
    if not all(any(char == candidate for candidate in cursor) for char in output):
        return ["source_text_rewritten"]
    return source_negation_errors(text, evidence, numbers)


def source_negation_errors(text, evidence, numbers):
    """Catch a retained literal action losing its explicit negation, not arbitrary paraphrases."""
    output = source_text_key(text, numbers)
    for match in re.finditer(r"(?P<neg>不建议|不推荐|不能|不要|不必|无需|严禁|禁止|千万别|别)"
                             r"(?P<action>[^，,。；;！？!?\n]{4,40})", evidence):
        action = source_text_key(match["action"], numbers)
        for occurrence in re.finditer(re.escape(action), output):
            prefix = output[max(0, occurrence.start() - 8):occurrence.start()]
            if not re.search(r"(?:不(?:建议|推荐|能|要|必)?|无需|严禁|禁止|千万别|别)\w{0,3}$", prefix):
                return ["source_negation_removed"]
    return []


PRICE_SCOPE_GROUPS = (
    (r"橱柜|地柜|吊柜|台面", r"地柜|吊柜|橱柜"),
    (r"衣柜|鞋柜|定制", r"衣柜|鞋柜|定制"),
    (r"窗|封阳台", r"窗|阳台"),
    (r"硬装|全屋装修|房屋装修", r"房子|房屋|住宅"),
)


def price_scope_issues(claim, transcript, numbers):
    """Keep nearby, explicitly sized quotation scope; not general scene inference."""
    if not money_atoms((claim.get("original_conclusion") or "") + (claim.get("price_info") or ""), numbers):
        return []
    refs = (claim.get("field_evidence") or {}).get("original_conclusion", [])
    quotes = claim.get("source_quotes") or []
    subject = " ".join([claim.get("object_name") or "", claim.get("original_conclusion") or "",
                        *(quotes[ref] for ref in refs if type(ref) is int and 0 <= ref < len(quotes))])
    groups = [source for target, source in PRICE_SCOPE_GROUPS if re.search(target, subject)]
    if not groups:
        return []
    output = "\n".join(claim.get(field) or "" for field in ("original_conclusion", "conditions", "price_info"))
    span = (claim.get("evidence_spans") or {}).get("original_conclusion")
    if not span:
        return []
    start = span[0]
    # Same-sentence prefix plus at most one preceding sentence, bounded to local context.
    stops = list(re.finditer(r"[。！？!?\n]", transcript[:start].rstrip("\r\n")))
    left = stops[-2].end() if len(stops) >= 2 else 0
    context = transcript[max(left, start - 160):span[1]]
    topic = list(re.finditer(r"(?:下一个|另一个话题|再说一下)", context))
    if topic:
        context = context[topic[-1].end():]
    def sized_objects(text):
        found = list(re.finditer("|".join(groups), text))
        for index, match in enumerate(found):
            right = min(match.end() + 16, found[index + 1].start() if index + 1 < len(found) else len(text))
            phrase = re.split(r"[。！？!?\n，,]", text[match.start():right])[0]
            for q in quantities(phrase, numbers)[1]:
                if q["kind"] in ("length", "area", "count:个", "count:套") and q["value"] is not None:
                    yield (match.group(), q["kind"], q["value"]), phrase

    output_sizes = {key for key, _ in sized_objects(output)}
    return [{"type": "scope", "quote": context, "reason": "quotation_size_scope_not_preserved",
             "source": "validator", "scope": phrase}
            for key, phrase in sized_objects(context) if key not in output_sizes]


MONEY_ATOM = re.compile(r"(?P<number>" + NUMBER + r")\s*(?P<unit>块钱|元|块)?")
SUBTOTAL = re.compile(r"合计|总计|共计|总价|一共|合起来|加起来")


def money_atoms(text, numbers):
    atoms = []
    for match in MONEY_ATOM.finditer(text):
        token = match["number"]
        # Bare prices such as 两千五 are common, but counts and dimensions are not prices.
        if not match["unit"] and not re.search(r"百|千|万|亿", token):
            continue
        if re.match(r"\s*(?:平方|平米|米|毫米|厘米|公分|年|月|天|小时|个|套|户|次|遍|层|%|㎡)", text[match.end():]):
            continue
        value = number_value(token, numbers)
        key = ("value", value) if value is not None else ("literal", token)
        atoms.append((match.start(), match.end(), key))
    return atoms


def subtotal_scope_errors(text, evidence, numbers):
    """Catch omitted priced components, not arbitrary price/object semantics or arithmetic."""
    output = {item[2] for item in money_atoms(text, numbers)}
    source = money_atoms(evidence, numbers)
    errors = []
    for marker in SUBTOTAL.finditer(evidence):
        total = next((atom for atom in source if marker.end() <= atom[0] < marker.end() + 35), None)
        if total is None or total[2] not in output:
            continue
        prior = {atom[2] for atom in source if atom[1] <= marker.start()}
        if len(prior) < 2 or prior.issubset(output):
            continue
        # A clearly labelled whole bundle may retain only its quoted total, not a partial item list.
        if len(output) == 1 and re.search(r"整套|全部项目|整组|本组|所有项目|整项|上述全部", text):
            continue
        errors.append("subtotal_omitted_priced_components")
    return errors


def tradeoff_issues(claim, transcript, numbers):
    """Preserve explicit local costs; do not invent unstated limitations."""
    output = condition_key((claim.get("original_conclusion") or "") + "\n" + (claim.get("conditions") or ""), numbers)
    output = re.sub(r"露出(?:一)?个", "露出", output)
    issues, seen = [], set()
    quotes = claim.get("source_quotes") or []
    refs = (claim.get("field_evidence") or {}).get("original_conclusion", range(len(quotes)))
    for ref in refs:
        quote = quotes[ref]
        span = (claim.get("evidence_spans") or {}).get("original_conclusion")
        ends = [span[1]] if span and transcript[span[0]:span[1]] == quote else [m.end() for m in re.finditer(re.escape(quote), transcript)]
        for end in ends:
            tail = re.match(r"(?:[^。！？!?\n]*[。！？!?\n]?){0,2}", transcript[end:end + 180]).group()
            tail = re.split(r"下一个|另一个话题|再说一下", tail)[0]
            context = quote + tail
            for match in re.finditer(r"(?:但|不过|只是)(?P<body>[^。！？!?\n]{3,100})|(?:代价|缺点)(?:是|为)(?P<cost>[^。！？!?\n]{3,100})", context):
                body = match["body"] or match["cost"]
                if match["body"]:
                    if not re.search(r"会|得接受|需要接受", body) or re.match(r"(?:是)?(?:如果|假如|要是|我|你|不喜欢)", body):
                        continue
                    body = re.split(r"会", body, maxsplit=1)[-1]
                body = re.split(r"[，,]?(?:你|您)?(?:得|需要|要)接受", body)[0].strip(" ，,")
                key = re.sub(r"露出(?:一)?个", "露出", condition_key(body, numbers))
                if len(key) >= 3 and key not in output and key not in seen:
                    seen.add(key)
                    issues.append({"type": "scope", "quote": match.group(), "reason": "explicit_tradeoff_not_preserved",
                                   "source": "validator", "tradeoff": body})
    return issues


CONDITIONS = (
    re.compile(r"(?:^|[，,。；;！？!?\n])(?:你|您)?(?P<condition>[^。！？!?\n，,]{2,60}?)的话[，,]"),
    re.compile(r"只有(?P<condition>[^。！？!?\n]{2,160}?)(?:才|方可|方能)"),
    re.compile(r"(?:如果|假如|若是)(?P<condition>[^。！？!?\n，,]{2,120}?)[，,]"
               r"(?=\s*(?:那么|则|就会|会))"),
    re.compile(r"(?:如果|假如|要是|若是)(?P<condition>[^。！？!?\n，,]{2,120}?)[，,]"
               r"(?=\s*(?:那么|那|则)?(?:就)?(?:建议|推荐|可以|可|应该|应当|应|需要|必须|一定|要|"
               r"不建议|不要|不能|不必|选择|选用|先|别|立即|马上|尽快))"),
    re.compile(r"前提(?:是|为)(?:什么呢[？?]\s*)?(?P<condition>[^。！？!?\n]{2,120})(?:[。！？!?\n]|$)"),
    re.compile(r"除非(?P<condition>[^。！？!?\n，,]{2,120})(?:[，,]|否则)"),
    re.compile(r"(?:仅适用|只适用|仅限)(?:于)?(?P<condition>[^。！？!?\n]{2,120})(?:[。！？!?\n]|$)"),
)


def condition_key(text, numbers):
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"^(?:一个|一种|这些|以下)(?:地方|情况|场景|条件)[，,\s]*(?:就是|是)?", "", text)
    for pattern, value in ((r"大于等于|不少于|不低于|至少|≥", ">="), (r"小于等于|不超过|至多|≤", "<="),
                           (r"超过|高于|大于", ">"), (r"低于|小于|不足", "<")):
        text = re.sub(pattern, value, text)
    normalized, values = quantities(text, numbers)
    for item in reversed(values):
        if item["value"] is not None:
            token = f"[{item['kind']}:{item['value'].normalize()}]"
            normalized = normalized[:item["start"]] + token + normalized[item["end"]:]
    normalized = re.sub(r"[\s，,。；;、：:]", "", normalized)
    normalized = re.sub(r"(特殊|明确|具体|相同|不同|相应)的", r"\1", normalized)
    normalized = re.sub(r"^(?:一个|一种|这些|以下)(?:地方|情况|场景|条件)(?:就是|是)?", "", normalized)
    normalized = re.sub(r"(?:的情况下|的时候|的话|时)$", "", normalized)
    normalized = re.sub(r"^(?:你(?:家|屋里)?(?:的)?|您(?:的)?|咱们(?:家)?(?:的)?)", "", normalized)
    return re.sub(r"^(?:有|出现|发现|存在)", "", normalized)


def condition_issues(claim, transcript, numbers):
    bindings = claim.get("field_evidence") or {}
    quotes = claim.get("source_quotes") or []
    refs = bindings.get("original_conclusion", list(range(len(quotes))))
    output = condition_key((claim.get("original_conclusion") or "") + "\n" + (claim.get("conditions") or ""), numbers)
    issues, seen = [], set()
    for ref in refs:
        quote = quotes[ref]
        # Include the same sentence's antecedent when the model cites only its consequence.
        contexts = [quote]
        span = (claim.get("evidence_spans") or {}).get("original_conclusion")
        occurrences = [span] if span and transcript[span[0]:span[1]] == quote else [
            [m.start(), m.end()] for m in re.finditer(re.escape(quote), transcript)]
        for start, end in occurrences:
            left = max((transcript.rfind(char, 0, start) for char in "。！？!?\n"), default=-1) + 1
            right = end if quote[-1:] in "。！？!?\n" else min(
                (pos for char in "。！？!?\n" if (pos := transcript.find(char, end)) >= 0),
                default=len(transcript))
            contexts.append(transcript[left:right])
        for context in contexts:
            for pattern in CONDITIONS:
                for match in pattern.finditer(context):
                    condition = match["condition"].strip(" ，,：:")
                    if re.fullmatch(r"(?:什么|啥)(?:呢|啊)?|(?:这|那)(?:个|块|项|一项|部分|些|里)", condition):
                        continue
                    if condition in seen:
                        continue
                    seen.add(condition)
                    parts = re.split(r"并且|而且|同时|且", condition)
                    if any(condition_key(part, numbers) not in output for part in parts if part.strip()):
                        issues.append({"type": "scope", "quote": match.group().rstrip("。！？!?\n"),
                                       "reason": "explicit_condition_not_preserved", "source": "validator",
                                       "condition": condition})
    return issues
