"""内容摘要工具：正文指纹与证据指纹共用同一套归一化规则。

正文指纹用于公告核对：已确认的公告正文可以随时用原文重新计算摘要比对，
去重、隔离等后续流程都不会改写公告正文，因此摘要保持稳定。
"""
from __future__ import annotations

import hashlib
import re


def normalize_text(text: str) -> str:
    """归一化空白：去掉行首行尾空白、压缩连续空白、丢弃空行。"""
    lines = [re.sub(r"[ \t　]+", " ", line).strip() for line in str(text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def body_fingerprint(text: str) -> str:
    """正文指纹：对归一化后的正文取 sha256，用于独立核对公告原文。"""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def short_fingerprint(text: str) -> str:
    """短指纹：保留前 16 位，方便页面展示，不替代完整指纹核对。"""
    return body_fingerprint(text)[:16]


def content_key(site: str, title: str, body: str) -> str:
    """有效内容去重键：同站点同标题同正文视为重复公告。"""
    raw = "|".join([str(site or "").strip(), normalize_text(title), body_fingerprint(body)])
    return body_fingerprint(raw)
