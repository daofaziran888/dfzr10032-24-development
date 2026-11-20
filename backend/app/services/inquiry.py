"""站点追问业务规则：从隔离记录发起追问，明确“针对哪个响应”。

追问必须携带隔离记录与具体响应ID：证据冲突时，同一页面可能既有真实停办日期、
又命中占位标记，只有把追问钉到具体响应，站点侧才能复现同一页面。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "inquiry"
REQUIRED_FIELDS = ["追问编号", "隔离编号", "响应ID"]
STATUS_ORDER = ["待追问", "已发出", "已回复", "已关闭"]
ACTION_RULES = {"发出追问": "已发出", "记录回复": "已回复", "关闭追问": "已关闭"}
NEGATIVE_ACTIONS = []


class InquiryService:
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
            rows = [row for row in rows if keyword in str(row.get("追问编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if extra:
            for field, val in extra.items():
                rows = [row for row in rows if val in str(row.get(field, ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        new_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry = {"id": new_id, "追问编号": values.get("追问编号") or f"ASK-{new_id:04d}"}
        for field, val in values.items():
            if field != "action":
                entry[field] = val
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def raise_for_isolation(self, isolation_code: str, response_id: str, note: str = "") -> tuple[dict[str, Any] | None, str]:
        """从隔离记录生成追问：校验隔离存在、响应确实属于该隔离记录。"""
        record = next(
            (row for row in store.rows("soft_error") if str(row.get("隔离编号") or "") == str(isolation_code)),
            None,
        )
        if record is None:
            return None, f"隔离记录 {isolation_code} 不存在"
        response_ids = [str(item) for item in record.get("响应列表") or []]
        if response_id not in response_ids:
            return None, (
                f"响应 {response_id or '（未指定）'} 不属于隔离记录 {isolation_code}，"
                f"可选响应：{'、'.join(response_ids) or '无'}"
            )
        evidence = next(
            (item for item in record.get("证据") or [] if str(item.get("响应ID") or "") == response_id),
            None,
        )
        rows = store.rows(MODULE)
        new_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry = {
            "id": new_id,
            "追问编号": f"ASK-{new_id:04d}",
            "隔离编号": isolation_code,
            "来源站点": record.get("来源站点"),
            "错误模板": record.get("错误模板"),
            "分类": record.get("分类"),
            "响应ID": response_id,
            "页面地址": (evidence or {}).get("页面地址"),
            "采集状态码": ((evidence or {}).get("采集状态码") or {}).get("value"),
            "正文片段": ((evidence or {}).get("正文片段") or {}).get("snippet", ""),
            "命中标记": "、".join(
                sorted({str(hit.get("marker")) for hit in (evidence or {}).get("命中标记") or []})
            ) or "—",
            "追问问题": note or "该页面返回正常状态码但命中占位标记，请站点确认此响应是占位页还是正式公告。",
            "status": STATUS_ORDER[0],
            "pending": True,
            "abnormal": False,
        }
        rows.append(entry)
        return entry, f"已针对响应 {response_id} 生成追问 {entry['追问编号']}"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"追问 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于站点追问可执行范围"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target == "待追问"
        entry["abnormal"] = False
        return entry, f"追问已{action}"
