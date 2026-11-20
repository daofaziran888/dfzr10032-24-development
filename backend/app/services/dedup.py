"""采集去重业务规则：状态流转、字段校验与筛选口径都收在这里。

去重同时承担“有效内容 / 拦截样本”的分流：
- 有效内容：来自解析成功的页面样本，按站点 + 标题 + 正文指纹去重，保留一条公告正文记录；
- 拦截样本：来自软错误页面隔离结果，按「站点 + 错误模板」单独合并，只记录条数与证据，
  不改写、不覆盖已保留的公告正文记录。
"""
from __future__ import annotations

from typing import Any

from app.digest import body_fingerprint, normalize_text
from app.services import page_sample, soft_error
from app.store import store

MODULE = "dedup"
REQUIRED_FIELDS = ["策略编号", "输入来源", "去重键"]
STATUS_ORDER = ["草稿", "已配置", "生效中", "已停用"]
ACTION_RULES = {"提交配置": "已配置", "启用策略": "生效中", "停用策略": "已停用"}
NEGATIVE_ACTIONS = ["停用策略"]

# 去重结果表；和策略配置分开存放，避免策略行被结果覆盖
VALID_MODULE = "dedup_valid"
BLOCKED_MODULE = "dedup_blocked"

# 已发布公告的正文记录，去重只读取，不写回
ANNOUNCEMENT_MODULE = "announcement"


def content_key(site: str, title: str, body: str) -> str:
    """有效内容去重键：同站点同标题同正文视为重复公告。"""
    raw = "|".join([str(site or "").strip(), normalize_text(title), body_fingerprint(body)])
    return body_fingerprint(raw)


def _valid_samples() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """有效公告样本：正文完整、无结构性错误标记；短正文公告同样算有效。"""
    rows = []
    for row in store.rows("page_sample"):
        result = page_sample.detect_soft_error(row)
        if result["classification"] == "valid":
            rows.append((row, result))
    return rows


def _blocked_groups() -> dict[str, dict[str, Any]]:
    """拦截样本按「站点 + 错误模板」合并：同一模板下的多个响应只保留一组。

    合并只发生在拦截样本之间，不触碰 announcement / dedup_valid 里的公告正文记录。
    """
    groups: dict[str, dict[str, Any]] = {}
    for row in store.rows(soft_error.MODULE):
        if row.get("status") == "已关闭":
            continue
        key = soft_error.isolation_fingerprint(
            str(row.get("来源站点") or ""),
            str(row.get("错误模板") or ""),
        )
        group = groups.setdefault(key, {
            "来源站点": row.get("来源站点"),
            "错误模板": row.get("错误模板"),
            "分类": row.get("分类"),
            "分类标签": row.get("分类标签"),
            "隔离编号": [],
            "样本列表": [],
            "响应列表": [],
            "冲突响应": [],
            "证据": [],
        })
        group["隔离编号"].append(str(row.get("隔离编号") or ""))
        group["样本列表"].extend(row.get("样本列表") or [])
        group["响应列表"].extend(row.get("响应列表") or [])
        group["冲突响应"].extend(row.get("冲突响应") or [])
        group["证据"].extend(row.get("证据") or [])
        classes = group.setdefault("分类列表", [])
        for label in row.get("分类列表") or [row.get("分类标签")]:
            if label and label not in classes:
                classes.append(label)
        # 只要组内有一条证据冲突，整组按冲突优先处理
        if row.get("分类") == "conflict":
            group["分类"] = "conflict"
            group["分类标签"] = "证据冲突"
    return groups


def run_dedup() -> dict[str, Any]:
    """执行一次去重分流。

    有效内容按去重键合并并写入 dedup_valid；已存在的公告正文不重写，只在结果里标注保留。
    拦截样本按错误模板合并写入 dedup_blocked，与公告正文记录完全隔离。
    """
    valid_rows = store.rows(VALID_MODULE)
    valid_by_key = {str(row.get("去重键")): row for row in valid_rows}
    published_by_key = {
        str(row.get("去重键") or "") or content_key(
            str(row.get("来源站点") or ""),
            str(row.get("标题") or ""),
            str(row.get("正文") or ""),
        ): row
        for row in store.rows(ANNOUNCEMENT_MODULE)
    }
    kept = added = duplicates = 0
    for sample, result in _valid_samples():
        key = content_key(
            str(sample.get("来源站点") or ""),
            page_sample.announcement_title(sample),
            str(sample.get("正文") or ""),
        )
        if key in valid_by_key:
            duplicates += 1
            existing_row = valid_by_key[key]
            sample_no = str(sample.get("样本编号") or "")
            sample_list = existing_row.setdefault("样本列表", [str(existing_row.get("样本编号") or "")])
            if sample_no and sample_no not in sample_list:
                sample_list.append(sample_no)
            continue
        if key in published_by_key:
            # 已保留的公告正文：登记为有效内容并指向原公告，绝不改写公告记录
            published = published_by_key[key]
            new_id = max((int(row.get("id", 0)) for row in valid_rows), default=0) + 1
            row = {
                "id": new_id,
                "去重键": key,
                "来源站点": sample.get("来源站点"),
                "标题": page_sample.announcement_title(sample),
                "正文": sample.get("正文"),
                "正文指纹": body_fingerprint(str(sample.get("正文") or "")),
                "停办日期": "、".join(result["contentSignals"]["dates"]) or "",
                "样本编号": sample.get("样本编号"),
                "样本列表": [str(sample.get("样本编号") or "")],
                "响应ID": sample.get("响应ID"),
                "响应列表": [str(sample.get("响应ID") or "")] if sample.get("响应ID") else [],
                "页面地址": sample.get("页面地址"),
                "采集状态码": sample.get("采集状态码"),
                "正文长度": result["bodyLength"],
                "短正文": result["shortBody"],
                "分类": result["classification"],
                "结论": result["label"],
                "状态": "有效内容（已发布，正文保留）",
                "保留公告": published.get("公告编号"),
            }
            valid_rows.append(row)
            valid_by_key[key] = row
            duplicates += 1
            continue
        new_id = max((int(row.get("id", 0)) for row in valid_rows), default=0) + 1
        row = {
            "id": new_id,
            "去重键": key,
            "来源站点": sample.get("来源站点"),
            "标题": page_sample.announcement_title(sample),
            "正文": sample.get("正文"),
            "正文指纹": body_fingerprint(str(sample.get("正文") or "")),
            "停办日期": "、".join(result["contentSignals"]["dates"]) or "",
            "样本编号": sample.get("样本编号"),
            "样本列表": [str(sample.get("样本编号") or "")],
            "响应ID": sample.get("响应ID"),
            "响应列表": [str(sample.get("响应ID") or "")] if sample.get("响应ID") else [],
            "页面地址": sample.get("页面地址"),
            "采集状态码": sample.get("采集状态码"),
            "正文长度": result["bodyLength"],
            "短正文": result["shortBody"],
            "分类": result["classification"],
            "结论": result["label"],
            "状态": "有效内容",
        }
        valid_rows.append(row)
        valid_by_key[key] = row
        added += 1
    kept = len(valid_rows)

    blocked_rows = store.rows(BLOCKED_MODULE)
    blocked_by_key = {str(row.get("合并键")): row for row in blocked_rows}
    blocked_added = blocked_merged = 0
    for key, group in _blocked_groups().items():
        aggregated = {
            "合并键": key,
            "来源站点": group["来源站点"],
            "错误模板": group["错误模板"],
            "分类": group["分类"],
            "分类标签": group["分类标签"],
            "分类列表": group.get("分类列表") or [],
            "隔离编号": "、".join(group["隔离编号"]),
            "记录数": len(group["样本列表"]),
            "样本列表": group["样本列表"],
            "响应列表": group["响应列表"],
            "冲突响应": group.get("冲突响应") or [],
            "证据": group["证据"],
            "状态": "拦截样本",
        }
        existing = blocked_by_key.get(key)
        if existing is None:
            aggregated["id"] = max((int(row.get("id", 0)) for row in blocked_rows), default=0) + 1
            blocked_rows.append(aggregated)
            blocked_by_key[key] = aggregated
            blocked_added += 1
        else:
            existing.update(aggregated)
            blocked_merged += 1

    return {
        "ok": True,
        "valid": {"added": added, "duplicates": duplicates, "total": kept},
        "blocked": {"added": blocked_added, "merged": blocked_merged, "total": len(blocked_rows)},
        "message": (
            f"去重完成：有效内容新增 {added} 条、重复 {duplicates} 条；"
            f"拦截样本合并 {blocked_added + blocked_merged} 组"
        ),
    }


def split_view() -> dict[str, Any]:
    """只读分流视图：不落库，按当前样本给出有效内容与拦截样本。"""
    valid: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample, result in _valid_samples():
        key = content_key(
            str(sample.get("来源站点") or ""),
            page_sample.announcement_title(sample),
            str(sample.get("正文") or ""),
        )
        valid.append({
            "去重键": key,
            "重复": key in seen,
            "样本编号": sample.get("样本编号"),
            "响应ID": sample.get("响应ID"),
            "来源站点": sample.get("来源站点"),
            "标题": page_sample.announcement_title(sample),
            "正文": sample.get("正文"),
            "停办日期": "、".join(result["contentSignals"]["dates"]) or "",
            "正文长度": result["bodyLength"],
            "短正文": result["shortBody"],
            "结论": result["label"],
            "分类": result["classification"],
        })
        seen.add(key)
    blocked = []
    for group in _blocked_groups().values():
        blocked.append({
            "来源站点": group["来源站点"],
            "错误模板": group["错误模板"],
            "分类": group["分类"],
            "分类标签": group["分类标签"],
            "分类列表": group.get("分类列表") or [],
            "隔离编号": "、".join(group["隔离编号"]),
            "记录数": len(group["样本列表"]),
            "样本列表": group["样本列表"],
            "响应列表": group["响应列表"],
            "冲突响应": group.get("冲突响应") or [],
        })
    return {"valid": valid, "blocked": blocked}


class DedupService:
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
            rows = [row for row in rows if keyword in str(row.get("策略编号", ""))]
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
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"去重策略 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于采集去重可执行范围"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"去重策略已{action}"
