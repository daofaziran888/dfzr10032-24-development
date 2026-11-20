"""公告办事台接口：发布去重后的有效公告，按日期追溯采用公告与追问响应。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.announcement import AnnouncementService

router = APIRouter(prefix="/api/announcement", tags=["公告办事台"])

service = AnnouncementService()

LIST_FIELDS = ["公告编号", "来源站点", "标题", "停办日期", "正文指纹", "样本编号", "响应ID", "核对状态"]
STATUSES = ["待发布", "已发布", "已撤回"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出公告清单：保留正文与指纹，便于离线核对。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "announcement", "total": total, "items": items}


@router.get("/day", response_model=dict)
def day_summary(date: str = Query(description="日期，形如 2026-11-20")) -> dict[str, Any]:
    """查清某一天采用的是哪份公告、相关隔离记录与追问分别针对哪个响应。"""
    return service.day_summary(date)


@router.post("/publish", response_model=ActionResult)
def publish(payload: EntryPayload) -> ActionResult:
    """按去重结果发布公告；正文缺失或被隔离的样本一律拒绝发布。"""
    values = payload.values or {}
    dedup_id = values.get("dedup_id")
    dedup_key = values.get("dedup_key")
    if dedup_id is None and not dedup_key:
        return ActionResult(ok=False, message="请提供去重结果编号 dedup_id 或去重键 dedup_key")
    entry, message = service.publish_from_dedup(
        dedup_id=int(dedup_id) if dedup_id is not None else None,
        dedup_key=str(dedup_key) if dedup_key else None,
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按公告编号检索"),
    status: str | None = Query(default=None, description="待发布、已发布、已撤回"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按公告编号与状态过滤公告列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}/verify", response_model=dict)
def verify(entry_id: int) -> dict:
    """按已留存的正文重新计算指纹，独立核对公告正文是否被改写。"""
    check, message = service.verify(entry_id)
    if check is None:
        raise HTTPException(status_code=404, detail=message)
    return check


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条公告明细。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"公告 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条公告草稿，正文为空时拒绝登记。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"公告正文或必填字段缺失：{'、'.join(missing)}")
    return ActionResult(ok=True, message="公告已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条公告执行发布公告、撤回公告；正文为空时拒绝发布。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
