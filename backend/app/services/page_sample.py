"""页面样本业务规则：采集成功返回的页面原样留存，正文完整性与软错误检测都基于样本判断。

设计要点：
- 样本是采集结果的唯一事实来源。原网页的状态码、正文片段、命中的错误标记全部留在样本里，
  下游（软错误隔离、去重、公告发布）只能引用样本字段，不能凭空补齐正文。
- 正文完整性只看样本里真实抓到的内容：正文选择器未命中或正文为空，一律判为缺失，
  不允许把样本落成一条没有正文的公告。
- 软错误检测要求“站点页面标记”和“页面实际内容”两类证据同时参与判断。
  同一站点的报错占位页和正式停办公告可能共用「未开放」标题和正文容器，所以标题标记本身
  不能作为唯一依据；正文里是否有真实内容（停办日期、停办公告措辞）才是关键。
- 两项证据冲突时（正文有真实停办日期、页尾却命中占位标记）单独标记为“证据冲突”，
  交给人工核实/站点追问，既不当作软错误静默丢弃，也不直接当成有效公告发布。
"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "page_sample"
REQUIRED_FIELDS = ["样本编号", "来源站点", "页面地址", "采集状态码"]

# 样本状态：解析成功只代表页面已取回并完成解析，不代表正文完整
STATUS_ORDER = ["待解析", "解析成功", "解析失败", "已归档"]
ACTION_RULES = {"标记解析成功": "解析成功", "标记解析失败": "解析失败", "归档样本": "已归档"}
NEGATIVE_ACTIONS = ["标记解析失败"]

# 正文缺失原因码：下游据此拒绝生成公告
MISSING_SELECTOR_MISS = "MISSING_SELECTOR_MISS"
MISSING_EMPTY_BODY = "MISSING_EMPTY_BODY"
MISSING_HTTP_STATUS = "MISSING_HTTP_STATUS"
MISSING_REASON_LABELS = {
    MISSING_SELECTOR_MISS: "正文选择器未配置",
    MISSING_EMPTY_BODY: "正文选择器未取到内容",
    MISSING_HTTP_STATUS: "缺少采集状态码",
}

# 已登记的站点占位/报错标记。标题上的「未开放」是站点共用文案，单独出现不作结论。
SITE_MARKERS = [
    "页面正在维护",
    "系统繁忙",
    "请稍后重试",
    "访问出错了",
    "页面不存在",
    "内容维护中",
    "页面维护中",
    "服务不可用",
    "暂无内容",
    "未开放",
    "尚未开放",
    "暂未开放",
]
GENERIC_MAINTENANCE_MARKERS = {"页面正在维护", "系统繁忙", "请稍后重试", "内容维护中", "页面维护中", "服务不可用"}
SHARED_TITLE_MARKERS = {"未开放", "尚未开放", "暂未开放"}

TITLE_FIELDS = ("页面标题", "标题")
# 正文容器里的标记是决定性证据；页尾占位标记同样来自原页面，可用于发现证据冲突
STRUCTURAL_FIELDS = ("正文", "正文容器", "正文片段", "页尾", "页尾占位", "页面标记")
MARKER_FIELDS = TITLE_FIELDS + STRUCTURAL_FIELDS

CLOSURE_KEYWORDS = ["停办", "停止办理", "暂停服务", "暂停办理", "迁址", "关闭", "终止", "不再受理", "停业"]
DATE_PATTERN = re.compile(r"(20\d{2})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?")
# 站点占位页常见的标题文案；和正文容器标记一样，单独出现不足以判定软错误
PLACEHOLDER_TITLE_PATTERN = re.compile(r"(系统提示|出错了|维护中|即将开放|未开放|暂未开放)")
SHORT_BODY_THRESHOLD = 20


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def extract_dates(text: str) -> list[str]:
    """提取正文中的日期并统一成 YYYY-MM-DD，去重后按出现顺序返回。"""
    dates: list[str] = []
    for year, month, day in DATE_PATTERN.findall(str(text or "")):
        value = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        if value not in dates:
            dates.append(value)
    return dates


def _find_markers(sample: dict[str, Any]) -> list[dict[str, str]]:
    """在样本的原始取数片段里逐条定位命中的站点标记。

    每一项都带 field / marker / snippet：field 指向样本里保存的原始字段，
    snippet 是该字段包含标记的原文，保证证据可以从原页面逐条核对。
    """
    hits: list[dict[str, str]] = []
    for field in MARKER_FIELDS:
        raw = _as_text(sample.get(field))
        if not raw:
            continue
        for marker in SITE_MARKERS:
            if marker in raw:
                hits.append({"field": field, "marker": marker, "snippet": raw[:200]})
    return hits


def _body_selector_hit(sample: dict[str, Any]) -> bool:
    """正文选择器是否真的取到了内容：选择器缺失或正文为空都算未命中。"""
    selector = _as_text(sample.get("正文选择器"))
    body = _as_text(sample.get("正文"))
    return bool(selector) and bool(body)


def body_integrity(sample: dict[str, Any]) -> dict[str, Any]:
    """校验正文完整性，返回可直接落库的结论与原因码。"""
    status_code = _as_text(sample.get("采集状态码"))
    body = _as_text(sample.get("正文"))
    selector_hit = _body_selector_hit(sample)
    reasons: list[str] = []
    if not status_code.isdigit():
        reasons.append(MISSING_HTTP_STATUS)
    if not _as_text(sample.get("正文选择器")):
        reasons.append(MISSING_SELECTOR_MISS)
    elif not body:
        reasons.append(MISSING_EMPTY_BODY)
    return {
        "ok": not reasons,
        "reasons": reasons,
        "reasonLabels": [MISSING_REASON_LABELS[code] for code in reasons],
        "bodyLength": len(_normalize(body)),
        "selectorHit": selector_hit,
        "hasBody": bool(body),
    }


def _real_content(text: str) -> tuple[bool, dict[str, list[str]]]:
    """判断正文里是否有真实公告内容：日期优先，停办措辞需要足够上下文。"""
    normalized = _normalize(text)
    dates = extract_dates(text)
    keywords = [word for word in CLOSURE_KEYWORDS if word in normalized]
    residual = normalized
    for marker in SITE_MARKERS:
        residual = residual.replace(marker, "")
    residual = re.sub(r"[\s，。；：、,.!?！？()（）\-—_]", "", residual)
    keyword_context = bool(keywords) and len(residual) >= 6
    return bool(dates) or keyword_context, {"dates": dates, "keywords": keywords}


def detect_soft_error(sample: dict[str, Any]) -> dict[str, Any]:
    """检测样本属于有效公告、软错误页、证据冲突还是正文缺失。

    判定矩阵（状态码正常的前提下）：
    - 正文缺失                                  -> missing_body（拦截，不生成公告）
    - 正文容器/页尾命中标记 + 正文有真实内容     -> conflict（证据冲突，人工核实）
    - 正文容器/页尾命中标记 + 正文无真实内容     -> soft_error（软错误页面）
    - 未命中结构性标记，正文有真实内容           -> valid（短正文同样有效）
    - 未命中结构性标记，正文无真实内容但可读     -> valid（低置信，仍可进入去重）
    标题上的「未开放」与正式公告共用，只作为旁证，不单独触发软错误。
    """
    status_code = _as_text(sample.get("采集状态码"))
    hits = _find_markers(sample)
    structural_hits = [hit for hit in hits if hit["field"] in STRUCTURAL_FIELDS]
    title_hits = [hit for hit in hits if hit["field"] in TITLE_FIELDS]
    title_shared = any(hit["marker"] in SHARED_TITLE_MARKERS for hit in title_hits)
    body = _as_text(sample.get("正文"))
    integrity = body_integrity(sample)
    real_content, signals = _real_content(body)
    short_body = 0 < integrity["bodyLength"] < SHORT_BODY_THRESHOLD

    if not integrity["ok"]:
        classification = "missing_body"
    elif status_code != "200":
        classification = "http_error"
    elif structural_hits and real_content:
        classification = "conflict"
    elif structural_hits:
        classification = "soft_error"
    else:
        classification = "valid"

    labels = {
        "valid": "有效公告（短正文）" if short_body else "有效公告",
        "soft_error": "软错误页面",
        "conflict": "证据冲突",
        "missing_body": "正文缺失",
        "http_error": "HTTP异常",
    }
    # 低置信只作为提示，不改变有效结论：短正文页面也可能是有效公告
    needs_review = classification == "valid" and not real_content and (short_body or title_shared)

    return {
        "classification": classification,
        "label": labels[classification],
        "isSoftError": classification == "soft_error",
        "evidenceConflict": classification == "conflict",
        "statusCode": status_code,
        "statusOkButErrorPage": status_code == "200" and classification in ("soft_error", "conflict"),
        "bodyComplete": integrity["ok"],
        "missingReasons": integrity["reasons"],
        "missingReasonLabels": integrity["reasonLabels"],
        "bodyLength": integrity["bodyLength"],
        "bodySnippet": body[:160],
        "selectorHit": integrity["selectorHit"],
        "shortBody": short_body,
        "realContent": real_content,
        "contentSignals": signals,
        "markers": hits,
        "structuralMarkers": structural_hits,
        "titleMarkers": title_hits,
        "titleShared": title_shared,
        "needsReview": needs_review,
    }


def derive_error_template(sample: dict[str, Any], result: dict[str, Any] | None = None) -> str:
    """归并错误模板：同站点同模板的拦截样本合并在一条隔离记录里。"""
    explicit = _as_text(sample.get("错误模板"))
    if explicit:
        return explicit
    result = result or detect_soft_error(sample)
    markers = {hit["marker"] for hit in result["structuralMarkers"]}
    # 「未开放」是站点报错占位和正式公告共用的标题文案，优先按它归并模板，
    # 避免同一站点的占位页因为页尾多一句“请稍后重试”被拆成两个模板。
    shared = any(marker in SHARED_TITLE_MARKERS for marker in markers) or result["titleShared"]
    if shared:
        return "未开放占位模板"
    if markers & GENERIC_MAINTENANCE_MARKERS:
        return "站点维护占位模板"
    if "页面不存在" in markers:
        return "页面不存在模板"
    if result["classification"] == "missing_body":
        return "正文缺失模板"
    if result["classification"] == "http_error":
        return "HTTP异常模板"
    return "未分类占位模板"


def announcement_title(sample: dict[str, Any]) -> str:
    """公告标题：优先公告标题字段，其次正文首行。

    站点共用标题（如「未开放」）不作为公告标题，避免把占位文案带到正式公告上。
    """
    explicit = _as_text(sample.get("公告标题"))
    if explicit:
        return explicit
    for line in str(sample.get("正文") or "").splitlines():
        line = line.strip()
        if line:
            return line[:80]
    title = _as_text(sample.get("标题"))
    if title and not PLACEHOLDER_TITLE_PATTERN.search(title):
        return title[:80]
    return _as_text(sample.get("样本编号")) or "未命名公告"


def build_evidence(sample: dict[str, Any], result: dict[str, Any] | None = None) -> dict[str, Any]:
    """构造可回查的证据：状态码、正文片段、命中的标记都指向样本原始字段。"""
    result = result or detect_soft_error(sample)
    body = _as_text(sample.get("正文"))
    raw_fields = {field: sample.get(field) for field in MARKER_FIELDS if sample.get(field) is not None}
    return {
        "响应ID": sample.get("响应ID"),
        "样本编号": sample.get("样本编号"),
        "页面地址": sample.get("页面地址"),
        "采集状态码": {"field": "采集状态码", "value": result["statusCode"]},
        "正文片段": {
            "field": "正文",
            "selector": sample.get("正文选择器"),
            "snippet": body[:200],
            "length": result["bodyLength"],
        },
        "命中标记": result["markers"],
        "内容信号": result["contentSignals"],
        "原始取值": raw_fields,
        "可核对": {
            "状态码": bool(_as_text(sample.get("采集状态码"))),
            "正文": bool(body),
            "标记": all(bool(_as_text(sample.get(hit["field"]))) for hit in result["markers"]),
        },
    }


class PageSampleService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        extra: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("样本编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if extra:
            for field, val in extra.items():
                rows = [row for row in rows if val in str(row.get(field, ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self.decorate(row) for row in rows[start:start + size]], total

    def decorate(self, row: dict[str, Any]) -> dict[str, Any]:
        """给列表补上实时检测结论，不覆盖样本里的原始字段。"""
        result = detect_soft_error(row)
        enriched = dict(row)
        enriched["正文完整性"] = body_integrity(row)
        enriched["检测结论"] = result["label"]
        enriched["正文长度"] = result["bodyLength"]
        enriched["短正文"] = result["shortBody"]
        enriched["软错误"] = result["isSoftError"]
        enriched["证据冲突"] = result["evidenceConflict"]
        enriched["命中标记"] = "、".join(sorted({hit["marker"] for hit in result["markers"]})) or "—"
        enriched["错误模板"] = derive_error_template(row, result) if result["classification"] != "valid" else "—"
        return enriched

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self.decorate(row) if row else None

    def find_by_response(self, response_id: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("响应ID") or "") == response_id:
                return self.decorate(row)
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field, val in values.items():
            if field not in entry and field != "action":
                entry[field] = val
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        integrity = body_integrity(entry)
        entry["abnormal"] = not integrity["ok"]
        rows.append(entry)
        return self.decorate(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"页面样本 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于页面样本可执行范围"
        target = ACTION_RULES[action]
        integrity = body_integrity(entry)
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS or (target == "解析成功" and not integrity["ok"])
        message = f"页面样本已{action}"
        if target == "解析成功" and not integrity["ok"]:
            message += f"，但正文不完整（{'、'.join(integrity['reasonLabels'])}），不能生成公告"
        return self.decorate(entry), message

    def evidence(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        result = detect_soft_error(row)
        return {
            "sample": self.decorate(row),
            "analysis": result,
            "evidence": build_evidence(row, result),
        }
