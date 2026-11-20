"""软错误页面隔离业务规则：把“状态码正常、实际是站点占位页”的样本集中隔离。

隔离结果按「站点 + 错误模板」合并：同一错误模板下的多个响应只留一条隔离记录，
原始响应逐条列在证据里。分类（软错误 / 证据冲突 / 正文缺失 / HTTP异常）记在样本级，
模板级分类取最需要人工介入的那一档。隔离结果只读页面样本，不修改任何公告正文记录。
"""
from __future__ import annotations

import hashlib
from typing import Any

from app.services import page_sample
from app.store import store

MODULE = "soft_error"
REQUIRED_FIELDS = ["隔离编号", "来源站点", "错误模板"]
STATUS_ORDER = ["待处理", "已追问", "已确认", "已关闭"]
ACTION_RULES = {"发起核实": "待处理", "标记已追问": "已追问", "确认占位页": "已确认", "关闭隔离": "已关闭"}
NEGATIVE_ACTIONS = ["确认占位页"]

CLASSIFICATION_LABELS = {
    "soft_error": "软错误页面",
    "conflict": "证据冲突",
    "missing_body": "正文缺失",
    "http_error": "HTTP异常",
}
CLASSIFICATION_ADVICE = {
    "soft_error": "按错误模板合并拦截，不进入公告",
    "conflict": "证据冲突，转人工核实并向站点追问",
    "missing_body": "正文缺失，拒绝生成公告",
    "http_error": "HTTP 状态异常，按失败重试",
}
ISOLATED_CLASSES = ("soft_error", "conflict", "missing_body", "http_error")


def isolation_fingerprint(site: str, template: str) -> str:
    """隔离指纹：同一站点同一错误模板合并到同一条隔离记录。

    分类（软错误 / 证据冲突 / 正文缺失）记在样本级，不影响模板归并：
    同一站点共用「未开放」标题的报错占位页和证据冲突样本属于同一模板家族，
    合并后仍能按响应逐条区分。
    """
    raw = "|".join([str(site or "").strip(), str(template or "").strip()])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _collect_groups() -> dict[str, dict[str, Any]]:
    """按「站点 + 错误模板」聚合所有非有效样本。"""
    groups: dict[str, dict[str, Any]] = {}
    for row in store.rows("page_sample"):
        result = page_sample.detect_soft_error(row)
        classification = result["classification"]
        if classification not in ISOLATED_CLASSES:
            continue
        template = page_sample.derive_error_template(row, result)
        key = isolation_fingerprint(str(row.get("来源站点") or ""), template)
        group = groups.setdefault(key, {
            "指纹": key,
            "来源站点": row.get("来源站点"),
            "错误模板": template,
            "样本": [],
        })
        group["样本"].append((row, result))
    return groups


def _group_classification(results: list[dict[str, Any]]) -> str:
    """模板级分类：只要有一条证据冲突或正文缺失，就不能按普通软错误处理。"""
    classes = [result["classification"] for result in results]
    for dominant in ("conflict", "missing_body", "soft_error", "http_error"):
        if dominant in classes:
            return dominant
    return classes[0] if classes else "soft_error"


def _render_group(group: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """把聚合结果渲染成一条隔离记录；已有记录保留编号与处理状态。"""
    samples = group["样本"]
    rows = [row for row, _ in samples]
    results = [result for _, result in samples]
    evidence = [page_sample.build_evidence(row, result) for row, result in samples]
    marker_names = sorted({hit["marker"] for result in results for hit in result["markers"]})
    response_ids = [str(row.get("响应ID") or "") for row in rows if row.get("响应ID")]
    status_codes = sorted({result["statusCode"] for result in results})
    classification = _group_classification(results)
    status = (existing or {}).get("status") or "待处理"
    per_sample = [
        {
            "样本编号": row.get("样本编号"),
            "响应ID": row.get("响应ID"),
            "分类": result["classification"],
            "分类标签": result["label"],
            "采集状态码": result["statusCode"],
            "正文片段": result["bodySnippet"],
            "命中标记": "、".join(sorted({hit["marker"] for hit in result["markers"]})) or "—",
        }
        for row, result in samples
    ]
    conflict_responses = [
        str(row.get("响应ID") or "")
        for row, result in samples
        if result["evidenceConflict"] and row.get("响应ID")
    ]
    entry = {
        "id": (existing or {}).get("id"),
        "隔离编号": (existing or {}).get("隔离编号"),
        "来源站点": group["来源站点"],
        "错误模板": group["错误模板"],
        "分类": classification,
        "分类标签": CLASSIFICATION_LABELS[classification],
        "分类列表": sorted({result["label"] for result in results}),
        "样本编号": "、".join(str(row.get("样本编号") or "") for row in rows),
        "样本列表": [str(row.get("样本编号") or "") for row in rows],
        "响应ID": "、".join(response_ids),
        "响应列表": response_ids,
        "记录数": len(rows),
        "状态码": "、".join(status_codes),
        "命中标记": "、".join(marker_names) or "—",
        "样本明细": per_sample,
        "冲突响应": conflict_responses,
        "证据": evidence,
        "指纹": group["指纹"],
        "建议": CLASSIFICATION_ADVICE[classification],
        "status": status,
        "pending": status == "待处理",
        "abnormal": classification in ("conflict", "missing_body", "soft_error"),
        "更新时间": max(
            [str((existing or {}).get("更新时间") or "")]
            + [str(row.get("采集时间") or "") for row in rows]
        ),
    }
    return entry


def scan(overwrite_status: bool = False) -> dict[str, Any]:
    """重新扫描页面样本，增量维护隔离记录。

    - 同一指纹已存在时更新样本清单与证据，保留原编号和人工处理状态；
    - 不改写任何公告正文记录；
    - 返回本次新增/更新/消解的数量，方便页面提示。
    """
    rows = store.rows(MODULE)
    existing_by_fp = {str(row.get("指纹")): row for row in rows}
    groups = _collect_groups()
    created = updated = 0
    for fingerprint, group in groups.items():
        existing = existing_by_fp.get(fingerprint)
        entry = _render_group(group, existing)
        if existing is None:
            new_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
            entry["id"] = new_id
            entry["隔离编号"] = f"ISO-{new_id:04d}"
            rows.append(entry)
            created += 1
        else:
            if overwrite_status:
                entry["status"] = "待处理"
                entry["pending"] = True
            existing.update(entry)
            updated += 1
    resolved = 0
    for fingerprint, row in existing_by_fp.items():
        if fingerprint in groups:
            continue
        if row.get("status") != "已关闭":
            row["status"] = "已关闭"
            row["pending"] = False
            row["abnormal"] = False
            resolved += 1
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "resolved": resolved,
        "isolated": len(groups),
        "message": f"隔离扫描完成：新增 {created} 条、更新 {updated} 条、消解 {resolved} 条",
    }


def isolation_for_sample(sample_no: str) -> dict[str, Any] | None:
    for row in store.rows(MODULE):
        if sample_no in (row.get("样本列表") or []):
            return row
    return None


class SoftErrorService:
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
            rows = [row for row in rows if keyword in str(row.get("隔离编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if extra:
            for field, val in extra.items():
                rows = [row for row in rows if val in str(row.get(field, ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self.summarize(row) for row in rows[start:start + size]], total

    def summarize(self, row: dict[str, Any]) -> dict[str, Any]:
        """列表视图：证据明细保留在详情里，列表只给摘要。"""
        item = {key: value for key, value in row.items() if key != "证据"}
        item["证据条数"] = len(row.get("证据") or [])
        return item

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def find_by_code(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("隔离编号") or "") == code:
                return row
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        new_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry = {
            "id": new_id,
            "隔离编号": values.get("隔离编号") or f"ISO-{new_id:04d}",
            "来源站点": values.get("来源站点"),
            "错误模板": values.get("错误模板"),
            "分类": values.get("分类") or "soft_error",
            "分类标签": CLASSIFICATION_LABELS.get(str(values.get("分类") or "soft_error"), "软错误页面"),
            "样本编号": values.get("样本编号") or "",
            "样本列表": values.get("样本列表") or [],
            "响应ID": values.get("响应ID") or "",
            "响应列表": values.get("响应列表") or [],
            "记录数": int(values.get("记录数") or 0),
            "状态码": values.get("状态码") or "",
            "命中标记": values.get("命中标记") or "—",
            "证据": values.get("证据") or [],
            "指纹": isolation_fingerprint(
                str(values.get("来源站点") or ""),
                str(values.get("错误模板") or ""),
            ),
            "建议": CLASSIFICATION_ADVICE.get(str(values.get("分类") or "soft_error"), ""),
            "status": STATUS_ORDER[0],
            "pending": True,
            "abnormal": True,
            "更新时间": values.get("更新时间") or "",
        }
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"隔离记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于软错误隔离可执行范围"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target == "待处理"
        entry["abnormal"] = target not in ("已确认", "已关闭")
        return entry, f"隔离记录已{action}"
