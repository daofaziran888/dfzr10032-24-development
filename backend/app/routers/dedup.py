"""采集去重接口：维护去重策略，并提供有效内容 / 拦截样本的分流与执行。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.dedup import BLOCKED_MODULE, VALID_MODULE, DedupService, run_dedup, split_view
from app.store import store

router = APIRouter(prefix="/api/dedup", tags=["采集去重"])

service = DedupService()

LIST_FIELDS = ["策略编号", "输入来源", "去重键", "排序字段", "保留策略", "时间窗口", "重复阈值", "策略状态"]
STATUSES = ["草稿", "已配置", "生效中", "已停用"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出采集去重清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "dedup", "total": total, "items": items}


@router.get("/split", response_model=dict)
def get_split() -> dict[str, Any]:
    """分流预览：按当前页面样本给出有效内容与拦截样本，不落库。"""
    return split_view()


@router.get("/valid", response_model=dict)
def list_valid() -> dict[str, Any]:
    """去重后的有效内容；已保留的公告正文不会被重复写入。"""
    rows = store.rows(VALID_MODULE)
    return {"total": len(rows), "items": rows}


@router.get("/blocked", response_model=dict)
def list_blocked() -> dict[str, Any]:
    """拦截样本：按错误模板合并，不改写任何公告正文记录。"""
    rows = store.rows(BLOCKED_MODULE)
    return {"total": len(rows), "items": rows}


@router.post("/run", response_model=dict)
def run() -> dict[str, Any]:
    """执行去重分流，把有效内容与拦截样本分别落库。"""
    return run_dedup()


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按策略编号检索"),
    status: str | None = Query(default=None, description="草稿、已配置、生效中、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按策略编号与状态过滤采集去重列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条去重策略明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"去重策略 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条去重策略，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="去重策略已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条去重策略执行提交配置、启用策略、停用策略；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
