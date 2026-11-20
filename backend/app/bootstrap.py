"""启动引导：把页面样本派生出的隔离结果与去重分流在服务启动时算好。

只做只读分析落库（隔离结果、去重结果），不自动发布公告、不自动向站点发出追问：
发布与追问都是需要人工确认的动作，分别由公告办事台和站点追问页面触发。
"""
from __future__ import annotations

from app.services import dedup, soft_error


def bootstrap() -> dict[str, object]:
    isolated = soft_error.scan()
    deduped = dedup.run_dedup()
    return {"isolated": isolated, "dedup": deduped}
