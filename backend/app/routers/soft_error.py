"""软错误页面隔离接口：扫描页面样本，按错误模板合并生成隔离结果。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.soft_error import SoftErrorService, scan

router = APIRouter(prefix="/api/soft_error", tags=["软错误页面隔离"])

service = SoftErrorService()

LIST_FIELDS = ["隔离编号", "来源站点", "错误模板", "分类", "样本编号", "响应ID", "命中标记", "状态码"]
STATUSES = ["待处理", "已追问", "已确认", "已关闭"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出软错误页面隔离清单。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "soft_error", "total": total, "items": items}


@router.post("/scan", response_model=dict)
def run_scan(payload: EntryPayload | None = None) -> dict[str, Any]:
    """重新扫描页面样本并增量维护隔离结果；同一错误模板下的记录合并为一条。"""
    overwrite = bool((payload.values if payload else {}).get("overwrite_status"))
    return scan(overwrite_status=overwrite)


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按隔离编号检索"),
    status: str | None = Query(default=None, description="待处理、已追问、已确认、已关闭"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按隔离编号与状态过滤隔离结果；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条隔离记录明细；证据包含每个响应可回查的原始字段。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"隔离记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """手工登记一条隔离记录；没有样本来源时说明原因。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="隔离记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条隔离记录执行发起核实、标记已追问、确认占位页、关闭隔离。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
