"""命名规范：标题清洗、版本计算、归档名组装与校验。"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

from . import standards as S

ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')
VERSION_RE = re.compile(r"^V(\d+)\.(\d+)$")
NAME_RE = re.compile(r"^[^_]+_[A-Z][A-Z0-9]*-[A-Z0-9]+_[^_]+_V\d+\.\d+_(草稿|内审|送审|正式|签字)_\d{8}(\.[^.]+)?$")


STATUS_TOKEN = re.compile(r"[\s_\-—(（【\[]+(签字版?|盖章版?|签章版?|已签字?|送审稿|送审版|内审稿|内审版|评审稿|定稿|终版"
                          r"|修订版?|修订稿|修改稿|更新版?|新版)[\)）】\]]?(?=$|[\s_\-—.(（【\[])")


def clean_title(raw: str, customer_short: str = "", type_name: str = "",
                aliases: Optional[list] = None, full_name: str = "") -> str:
    """去掉噪声词、版本号、日期、非法字符；客户名称统一为简称；限制 30 字。"""
    t = (raw or "").strip()
    t = re.sub(r"\.(docx?|xlsx?|pptx?|pdf|txt|md|zip|rar)$", "", t, flags=re.I)
    t = re.sub(r"[A-Za-z]{2,8}-\d{4}-[A-Za-z0-9]{3,20}", " ", t)     # 项目编号已在名称首位（PRJ-2026-0123、XM-2026-2EDMV0JRPZF）
    t = re.sub(r"[\(（【\[]\s*\d{1,2}\s*[\)）】\]]", "", t)          # (1) （2）
    t = re.sub(r"(?i)(?<![a-z])v\s*\d+(\.\d+)*(?![a-z])", " ", t)   # V2 / v1.1 / 报告V2（不误伤 IPv6）
    t = re.sub(r"(?i)rev\s*\d+", " ", t)
    t = re.sub(r"(20\d{2})\s*[年\-/\.]?\s*\d{1,2}\s*[月\-/\.]?\s*\d{1,2}\s*日?", " ", t)  # 日期
    t = STATUS_TOKEN.sub(" ", t)                                       # 状态由状态字段表达
    t = re.sub(r"(^|[\s_\-—(（【\[])改(?:版|稿)?\d*(?=$|[\s_\-—.)）】\]])", " ", t)   # 「-改」「_改2」这类单独的改
    for w in sorted(S.NOISE_WORDS, key=len, reverse=True):
        t = t.replace(w, " ")
    t = ILLEGAL.sub(" ", t)
    t = t.replace("_", " ")
    t = re.sub(r"[\s\-—·.]+", "-", t).strip("-（）()【】[] ")
    t = re.sub(r"-{2,}", "-", t)
    # 中文之间不需要连字符
    t = re.sub(r"(?<=[一-鿿])-(?=[一-鿿])", "", t)
    if not t or len(t) < 2:
        t = type_name or "文件"
    if customer_short and customer_short not in t:
        # 全称或别名统一替换为简称，避免「澄湾科技澄湾…」
        others = [n for n in [full_name, *(aliases or [])] if n and n != customer_short and len(n) >= 2]
        for n in sorted(others, key=len, reverse=True):
            if re.search(re.escape(n), t, flags=re.I):
                t = re.sub(re.escape(n), customer_short, t, count=1, flags=re.I)
                break
        else:
            t = customer_short + t
    t = re.sub(r"[/／]", "-", t)
    return t[: S.MAX_TITLE]


def is_garbage_title(t: str) -> bool:
    t = (t or "").strip()
    if len(t) < 3:
        return True
    if re.fullmatch(r"[\d\s_\-\.()（）]+", t):
        return True
    return any(g in t for g in S.GARBAGE_TITLES)


def parse_version(v: str) -> Tuple[int, int]:
    m = VERSION_RE.match(v or "")
    return (int(m.group(1)), int(m.group(2))) if m else (1, 0)


def fmt_version(major: int, minor: int) -> str:
    return f"V{major}.{minor}"


def next_version(current: Optional[str], new_status: str) -> str:
    """草稿/内审/送审 → V0.x；正式/签字首次 → V1.0；已正式后每次修改 → 次版本 +1。"""
    draft = new_status in S.DRAFT_STATUSES
    if not current:
        return "V0.1" if draft else "V1.0"
    major, minor = parse_version(current)
    if major == 0:
        return fmt_version(0, minor + 1) if draft else "V1.0"
    return fmt_version(major, minor + 1)


def date_compact(d: Optional[str]) -> str:
    if d and re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        return d.replace("-", "")
    return date.today().strftime("%Y%m%d")


def build_name(project_no: str, doc_type: str, title: str, version: str, status: str,
               doc_date: Optional[str], ext: str) -> str:
    ext = (ext or "").lower()
    head = f"{project_no}_{doc_type}_"
    tail = f"_{version}_{status}_{date_compact(doc_date)}{ext}"
    room = S.MAX_NAME - len(head) - len(tail)
    t = title[: max(4, min(room, S.MAX_TITLE))]
    return f"{head}{t}{tail}"


def validate_name(name: str) -> bool:
    return bool(NAME_RE.match(name)) and len(name) <= S.MAX_NAME + 10 and not ILLEGAL.search(name)


def external_name(archive_name: str) -> str:
    """对外交付名：去掉项目编号和类型码。"""
    parts = archive_name.split("_")
    if len(parts) >= 6:
        return "_".join([parts[2], parts[3], parts[5]])
    return archive_name


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    i = 2
    while True:
        cand = p.with_name(f"{stem}-{i}{suffix}")
        if not cand.exists():
            return cand
        i += 1


def safe_dir_name(s: str) -> str:
    s = ILLEGAL.sub("-", (s or "").strip())
    s = re.sub(r"\s+", "", s)
    return s[:40] or "未命名"
