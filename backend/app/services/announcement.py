"""公告办事台业务规则：只发布去重后的有效公告，并保留可独立核对的正文。

发布口径：
- 公告正文只来源于去重结果（dedup_valid），不接受手工拼接的正文；
- 正文为空、或来源样本被隔离（软错误 / 证据冲突 / 正文缺失），一律拒绝发布，
  避免缺失正文落成一条空公告；
- 发布时记录正文指纹、样本编号与响应ID，停办日期取正文中真实出现的日期；
- 已发布公告的正文不再被任何后续流程改写，核对时按原文重新计算指纹即可独立验证。
"""
from __future__ import annotations

from typing import Any

from app.digest import body_fingerprint
from app.services import page_sample
from app.store import store

MODULE = "announcement"
REQUIRED_FIELDS = ["公告编号", "来源站点", "标题", "正文"]
STATUS_ORDER = ["待发布", "已发布", "已撤回"]
ACTION_RULES = {"发布公告": "已发布", "撤回公告": "已撤回"}
NEGATIVE_ACTIONS = ["撤回公告"]

VALID_SOURCE_CLASS = "valid"


class AnnouncementService:
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
            rows = [row for row in rows if keyword in str(row.get("公告编号", ""))]
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
        body = str(values.get("正文") or "")
        if not body.strip():
            return None, ["正文"]
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field, val in values.items():
            if field not in entry and field != "action":
                entry[field] = val
        entry["正文指纹"] = body_fingerprint(body)
        entry["停办日期"] = "、".join(page_sample.extract_dates(body))
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["核对状态"] = "未核对"
        rows.append(entry)
        return entry, []

    def publish_from_dedup(self, dedup_id: int | None = None, dedup_key: str | None = None) -> tuple[dict[str, Any] | None, str]:
        """从去重后的有效公告发布停办日期。"""
        from app.services import dedup  # 延迟导入，避免模块间循环

        row = None
        for candidate in store.rows(dedup.VALID_MODULE):
            if dedup_id is not None and int(candidate.get("id", 0)) == int(dedup_id):
                row = candidate
                break
            if dedup_key and str(candidate.get("去重键") or "") == str(dedup_key):
                row = candidate
                break
        if row is None:
            return None, "去重结果中没有这条有效内容，不能发布公告"

        body = str(row.get("正文") or "")
        if not body.strip():
            return None, "去重结果的正文为空，拒绝发布空公告"

        sample_no = str(row.get("样本编号") or "")
        sample = next((item for item in store.rows("page_sample") if str(item.get("样本编号") or "") == sample_no), None)
        if sample is None:
            return None, f"来源样本 {sample_no or '（未登记）'} 不存在，不能发布公告"
        result = page_sample.detect_soft_error(sample)
        if result["classification"] != VALID_SOURCE_CLASS:
            return None, (
                f"来源样本 {sample_no} 属于「{result['label']}」，已被隔离，不能作为公告发布"
            )
        if body_fingerprint(body) != body_fingerprint(str(sample.get("正文") or "")):
            return None, "去重正文与来源样本不一致，不能发布公告"

        dates = page_sample.extract_dates(body)
        rows = store.rows(MODULE)
        existing = next(
            (item for item in rows if str(item.get("去重键") or "") and str(item.get("去重键")) == str(row.get("去重键"))),
            None,
        )
        if existing is not None:
            # 同一公告再次发布：正文已经保留，不重写已发布的正文记录
            if body_fingerprint(str(existing.get("正文") or "")) == body_fingerprint(body):
                return existing, (
                    f"公告 {existing.get('公告编号')} 已存在且正文一致，保留原记录，"
                    f"停办日期 {existing.get('停办日期') or '未识别'}"
                )
            if existing.get("status") == "已发布":
                return None, f"公告 {existing.get('公告编号')} 已发布且正文不同，不能覆盖已保留的公告正文"
        if existing is None:
            new_id = max((int(item.get("id", 0)) for item in rows), default=0) + 1
            existing = {"id": new_id, "公告编号": f"ANNO-{new_id:04d}"}
            rows.append(existing)
        existing.update({
            "来源站点": row.get("来源站点"),
            "标题": row.get("标题"),
            "正文": body,
            "正文指纹": body_fingerprint(body),
            "停办日期": "、".join(dates),
            "样本编号": sample_no,
            "响应ID": row.get("响应ID"),
            "页面地址": row.get("页面地址"),
            "采集状态码": row.get("采集状态码"),
            "去重键": row.get("去重键"),
            "status": "已发布",
            "pending": False,
            "abnormal": False,
            "核对状态": "未核对",
            "发布来源": "去重结果",
        })
        return existing, f"公告 {existing.get('公告编号')} 已按去重结果发布，停办日期 {existing['停办日期'] or '未识别'}"

    def verify(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        """按已留存的正文重新计算指纹，独立核对公告正文是否被改写。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"公告 {entry_id} 不存在或已归档"
        body = str(entry.get("正文") or "")
        fingerprint = body_fingerprint(body)
        stored = str(entry.get("正文指纹") or "")
        matches = bool(body.strip()) and bool(stored) and fingerprint == stored
        entry["核对状态"] = "一致" if matches else "不一致"
        entry["最近核对时间"] = entry.get("最近核对时间") or ""
        check = {
            "公告编号": entry.get("公告编号"),
            "正文指纹": fingerprint,
            "留存指纹": stored,
            "一致": matches,
            "正文长度": len(body),
            "正文片段": body[:160],
            "停办日期": entry.get("停办日期"),
            "来源样本": entry.get("样本编号"),
            "来源响应": entry.get("响应ID"),
            "核对依据": "按公告记录中留存的正文原文重新计算指纹，不依赖采集现场",
        }
        if not body.strip():
            return check, f"公告 {entry.get('公告编号')} 正文为空，无法核对"
        return check, f"公告 {entry.get('公告编号')} 正文核对{'一致' if matches else '不一致'}"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"公告 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于公告办事台可执行范围"
        if action == "发布公告":
            if not str(entry.get("正文") or "").strip():
                return None, f"公告 {entry.get('公告编号')} 正文为空，拒绝发布"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target == "待发布"
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"公告已{action}"

    def day_summary(self, date: str) -> dict[str, Any]:
        """查清某一天采用的公告、相关隔离与追问分别针对哪个响应。

        - 采用公告：去重后有效公告里，停办日期覆盖该日期的已发布公告；
        - 隔离记录：证据正文片段里出现该日期的拦截样本；
        - 追问：涉及该日期、或针对采用公告来源响应的隔离记录发出的追问。
        """
        target = str(date or "").strip()
        announcements = [
            row for row in store.rows(MODULE)
            if target and target in str(row.get("停办日期") or "")
        ]
        adopted = next((row for row in announcements if row.get("status") == "已发布"), None)
        isolation = []
        for row in store.rows("soft_error"):
            for item in row.get("证据") or []:
                snippet = str((item.get("正文片段") or {}).get("snippet") or "")
                if target and target in snippet:
                    isolation.append(row)
                    break
        related_responses = {
            str(item.get("响应ID") or "")
            for record in isolation
            for item in record.get("证据") or []
        }
        if adopted is not None:
            related_responses.add(str(adopted.get("响应ID") or ""))
        inquiries = [
            row for row in store.rows("inquiry")
            if (target and target in str(row.get("涉及日期") or ""))
            or (target and target in str(row.get("正文片段") or ""))
            or str(row.get("响应ID") or "") in related_responses
        ]
        adoption_detail = None
        if adopted is not None:
            check, _ = self.verify(int(adopted["id"]))
            adoption_detail = {
                "公告编号": adopted.get("公告编号"),
                "标题": adopted.get("标题"),
                "停办日期": adopted.get("停办日期"),
                "来源样本": adopted.get("样本编号"),
                "来源响应": adopted.get("响应ID"),
                "页面地址": adopted.get("页面地址"),
                "正文指纹": adopted.get("正文指纹"),
                "核对": check,
            }
        inquiry_detail = [
            {
                "追问编号": row.get("追问编号"),
                "隔离编号": row.get("隔离编号"),
                "响应ID": row.get("响应ID"),
                "页面地址": row.get("页面地址"),
                "命中标记": row.get("命中标记"),
                "追问问题": row.get("追问问题"),
                "status": row.get("status"),
            }
            for row in inquiries
        ]
        if adopted is None:
            explanation = f"{target} 没有已发布的有效公告，未发布停办日期"
        else:
            explanation = (
                f"{target} 采用公告 {adopted.get('公告编号')}（来源响应 {adopted.get('响应ID')}）；"
                f"追问针对响应 {'、'.join(str(item['响应ID']) for item in inquiry_detail) or '无'}"
            )
        return {
            "日期": target,
            "采用公告": adoption_detail,
            "相关公告": announcements,
            "隔离记录": [
                {
                    "隔离编号": row.get("隔离编号"),
                    "来源站点": row.get("来源站点"),
                    "错误模板": row.get("错误模板"),
                    "分类": row.get("分类"),
                    "响应列表": row.get("响应列表"),
                    "status": row.get("status"),
                }
                for row in isolation
            ],
            "追问": inquiry_detail,
            "核对": adoption_detail["核对"] if adoption_detail else None,
            "说明": explanation,
        }
