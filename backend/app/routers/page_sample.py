"""页面样本接口：留存解析成功返回的页面样本，提供正文完整性与软错误检测视图。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.page_sample import PageSampleService, detect_soft_error

router = APIRouter(prefix="/api/page_sample", tags=["页面样本"])

service = PageSampleService()

LIST_FIELDS = ["样本编号", "来源站点", "页面地址", "采集状态码", "正文选择器", "页面标题", "标题", "正文", "页尾", "错误模板", "响应ID"]
STATUSES = ["待解析", "解析成功", "解析失败", "已归档"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出页面样本清单：原样返回样本字段与检测结论。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "page_sample", "total": total, "items": items}


@router.get("/analysis")
def analysis() -> dict[str, Any]:
    """样本检测汇总：有效公告、软错误页、证据冲突、正文缺失各多少条。"""
    items, _ = service.list_entries(page=1, size=10000)
    counts: dict[str, int] = {}
    conflicts: list[dict[str, Any]] = []
    for item in items:
        result = detect_soft_error(item)
        counts[result["classification"]] = counts.get(result["classification"], 0) + 1
        if result["evidenceConflict"]:
            conflicts.append({
                "样本编号": item.get("样本编号"),
                "响应ID": item.get("响应ID"),
                "正文片段": result["bodySnippet"],
                "命中标记": result["markers"],
            })
    return {
        "counts": counts,
        "labels": {
            "valid": "有效公告",
            "soft_error": "软错误页面",
            "conflict": "证据冲突",
            "missing_body": "正文缺失",
            "http_error": "HTTP异常",
        },
        "conflicts": conflicts,
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按样本编号检索"),
    status: str | None = Query(default=None, description="待解析、解析成功、解析失败、已归档"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按样本编号与状态过滤页面样本列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}/evidence", response_model=dict)
def get_evidence(entry_id: int) -> dict:
    """读取单条样本的可回查证据：状态码、正文片段、命中的错误标记都指向原始字段。"""
    payload = service.evidence(entry_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"页面样本 {entry_id} 不存在或已归档")
    return payload


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条页面样本明细，附带实时检测结论。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"页面样本 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条页面样本，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="页面样本已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条页面样本执行标记解析成功、标记解析失败、归档样本。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
