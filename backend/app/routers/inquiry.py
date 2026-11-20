"""站点追问接口：从隔离记录针对具体响应发起追问。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.inquiry import InquiryService

router = APIRouter(prefix="/api/inquiry", tags=["站点追问"])

service = InquiryService()

LIST_FIELDS = ["追问编号", "隔离编号", "来源站点", "错误模板", "响应ID", "页面地址", "采集状态码", "命中标记"]
STATUSES = ["待追问", "已发出", "已回复", "已关闭"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出追问清单。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "inquiry", "total": total, "items": items}


@router.post("/raise", response_model=ActionResult)
def raise_inquiry(payload: EntryPayload) -> ActionResult:
    """从隔离记录发起追问，必须指明针对哪个响应。"""
    values = payload.values or {}
    isolation_code = str(values.get("isolation_code") or "").strip()
    response_id = str(values.get("response_id") or "").strip()
    if not isolation_code:
        return ActionResult(ok=False, message="请提供隔离编号 isolation_code")
    if not response_id:
        return ActionResult(ok=False, message="请提供要追问的响应 response_id")
    entry, message = service.raise_for_isolation(isolation_code, response_id, str(values.get("note") or ""))
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按追问编号检索"),
    status: str | None = Query(default=None, description="待追问、已发出、已回复、已关闭"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按追问编号与状态过滤追问列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条追问明细。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"追问 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """手工登记一条追问，缺字段时说明原因。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="追问已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条追问执行发出追问、记录回复、关闭追问。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
