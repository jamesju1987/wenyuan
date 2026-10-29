"""客户与项目：增改、目录生成与改名同步、CSV/Excel 导入。"""
from __future__ import annotations

import csv
import io
import os
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config
from . import standards as S
from .db import DB, loads, now
from .naming import safe_dir_name

SPLIT = re.compile(r"[、,;，；\s]+")
CORP_SUFFIX = ["股份有限公司", "有限责任公司", "有限公司", "集团公司", "（中国）", "(中国)", "中国", "集团", "公司"]
REGION_PREFIX = ["上海市", "上海", "北京市", "北京", "江苏省", "浙江省", "广东省", "深圳市", "苏州市", "杭州市"]


def derive_short(full: str) -> str:
    s = (full or "").strip()
    for p in REGION_PREFIX:
        if s.startswith(p) and len(s) > len(p) + 2:
            s = s[len(p):]
            break
    for suf in CORP_SUFFIX:
        s = s.replace(suf, "")
    return safe_dir_name(s[:8]) if s else safe_dir_name(full[:8])


def derive_project_short(name: str, customer_full: str, customer_short: str) -> str:
    s = (name or "").strip()
    for c in (customer_full, customer_short):
        if c:
            s = s.replace(c, "")
    s = re.sub(r"项目$", "", s).strip(" -_—")
    return safe_dir_name(s[:20] or name[:20])


def split_list(v) -> List[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x for x in SPLIT.split(str(v or "")) if x]


# ---------------------------------------------------------------- 查询
def customer_dir(c: Dict) -> Path:
    return config.root() / c["dir_name"]


def project_dir(p: Dict, c: Optional[Dict] = None, db: Optional[DB] = None) -> Path:
    if c is None:
        c = db.one("SELECT * FROM customers WHERE id=?", (p["customer_id"],))
    return customer_dir(c) / p["dir_name"]


def list_projects(db: DB) -> List[Dict]:
    rows = db.q("""SELECT p.*, c.short_name AS customer_short, c.full_name AS customer_full,
                   c.code AS customer_code, c.aliases AS customer_aliases, c.dir_name AS customer_dir
                   FROM projects p JOIN customers c ON c.id=p.customer_id ORDER BY p.id DESC""")
    counts = {r["project_id"]: r["n"] for r in db.q(
        "SELECT project_id, COUNT(*) n FROM files WHERE state='archived' GROUP BY project_id")}
    for r in rows:
        r["aliases"] = loads(r.pop("customer_aliases"), [])
        r["keywords"] = loads(r["keywords"], [])
        r["file_count"] = counts.get(r["id"], 0)
        r["label"] = f"{r['customer_short']} · {r['short_name']}"
    return rows


def candidate_projects(db: DB) -> List[Dict]:
    """进行中，或结项不超过 N 天的项目。"""
    days = int(config.get("recent_project_days") or 90)
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for p in list_projects(db):
        if p["status"] != "已结项" or not p["end_date"] or p["end_date"] >= cutoff:
            out.append(p)
    return out


def get_project(db: DB, pid: int) -> Optional[Dict]:
    for p in list_projects(db):
        if p["id"] == pid:
            return p
    return None


# ---------------------------------------------------------------- 目录
def ensure_project_dirs(db: DB, p: Dict) -> Path:
    c = db.one("SELECT * FROM customers WHERE id=?", (p["customer_id"],))
    d = project_dir(p, c)
    for st in S.STAGES:
        (d / st).mkdir(parents=True, exist_ok=True)
    (d / S.EVIDENCE_DIR).mkdir(parents=True, exist_ok=True)
    return d


def ensure_all_dirs(db: DB) -> None:
    config.ensure_system_dirs()
    for p in db.q("SELECT * FROM projects"):
        ensure_project_dirs(db, p)


def _rename_tree(db: DB, old: Path, new: Path) -> None:
    if old == new:
        return
    if old.exists():
        if new.exists():
            # 目标位置已经有同名文件夹（比如以前留下的）：合并进去，而不是再建一个
            from .tidy import Mover
            mv = Mover()
            mv.merge(old, new)
            mv.apply(db)
            if mv.errors:
                raise ValueError(f"「{old.name}」里有 {len(mv.errors)} 个文件没能移动，可能正被打开，请关闭后重试")
            return
        new.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(old), str(new))
        except OSError as e:
            raise ValueError(f"无法重命名目录「{old.name}」：其中可能有文件正在被打开，请关闭后重试（{e.strerror or e}）")
    old_s, new_s = str(old), str(new)
    for f in db.q("SELECT id, archive_path FROM files"):
        ap = f["archive_path"] or ""
        if ap == old_s or ap.startswith(old_s + os.sep) or ap.startswith(old_s + "/"):
            db.update("files", f["id"], {"archive_path": new_s + ap[len(old_s):]})
    for j in db.q("SELECT id, staged_path FROM jobs WHERE status='archived'"):
        sp = j["staged_path"] or ""
        if sp.startswith(old_s + os.sep) or sp.startswith(old_s + "/"):
            db.update("jobs", j["id"], {"staged_path": new_s + sp[len(old_s):]})


# ---------------------------------------------------------------- 增改
def next_customer_code(db: DB) -> str:
    n = 0
    for r in db.q("SELECT code FROM customers"):
        m = re.match(r"^C(\d+)$", r["code"])
        if m:
            n = max(n, int(m.group(1)))
    return f"C{n + 1:04d}"


def upsert_customer(db: DB, short_name: str = "", full_name: str = "", code: str = "",
                    aliases=None) -> Dict:
    full_name = (full_name or "").strip()
    short_name = safe_dir_name(short_name) if short_name else derive_short(full_name)
    code = (code or "").strip()
    c = None
    if code:
        c = db.one("SELECT * FROM customers WHERE code=?", (code,))
    if not c and full_name:
        c = db.one("SELECT * FROM customers WHERE full_name=?", (full_name,))
    if not c and short_name:
        c = db.one("SELECT * FROM customers WHERE short_name=?", (short_name,))
    if not c:
        c = find_known_customer(db, code, full_name, short_name)
    alias_list = split_list(aliases)
    if c:
        changes = {}
        old_aliases = loads(c["aliases"], [])
        merged = old_aliases + [a for a in alias_list if a not in old_aliases]
        if merged != old_aliases:
            changes["aliases"] = merged
        if full_name and not c["full_name"]:
            changes["full_name"] = full_name
        db.update("customers", c["id"], changes)
        return db.one("SELECT * FROM customers WHERE id=?", (c["id"],))
    code = code or next_customer_code(db)
    dir_name = f"{short_name}_{code}"
    cid = db.insert("customers", {"code": code, "short_name": short_name, "full_name": full_name,
                                  "aliases": alias_list, "dir_name": dir_name, "created_at": now()})
    return db.one("SELECT * FROM customers WHERE id=?", (cid,))


def find_known_customer(db: DB, code: str, full_name: str, short_name: str) -> Optional[Dict]:
    """合并过的客户、或者别名里写着这个名称的客户：直接用它，不再新建一个重复的。"""
    for col, v in (("code", code), ("full_name", full_name), ("short_name", short_name)):
        if v:
            m = db.one(f"SELECT target_id FROM customer_merges WHERE {col}=? ORDER BY id DESC LIMIT 1", (v,))
            c = m and db.one("SELECT * FROM customers WHERE id=?", (m["target_id"],))
            if c:
                return c
    names = [n for n in (full_name, short_name) if n]
    for c in db.q("SELECT * FROM customers ORDER BY id") if names else []:
        if any(n in (loads(c["aliases"], []) or []) for n in names):
            return c
    return None


def update_customer(db: DB, cid: int, short_name: str, full_name: str, aliases) -> Dict:
    c = db.one("SELECT * FROM customers WHERE id=?", (cid,))
    if not c:
        raise ValueError("客户不存在")
    short_name = safe_dir_name(short_name or c["short_name"])
    new_dir = f"{short_name}_{c['code']}"
    _rename_tree(db, config.root() / c["dir_name"], config.root() / new_dir)
    db.update("customers", cid, {"short_name": short_name, "full_name": full_name or c["full_name"],
                                 "aliases": split_list(aliases), "dir_name": new_dir})
    return db.one("SELECT * FROM customers WHERE id=?", (cid,))


def save_project(db: DB, data: Dict, pid: Optional[int] = None, replace_aliases: bool = False) -> Dict:
    project_no = (data.get("project_no") or "").strip()
    if not project_no:
        raise ValueError("项目编号不能为空")
    if re.search(r'[\\/:*?"<>|_\s]', project_no):
        raise ValueError("项目编号不能包含下划线、空格或 \\ / : * ? \" < > |")
    name = (data.get("name") or "").strip() or project_no
    if pid is None:
        exist = db.one("SELECT * FROM projects WHERE project_no=?", (project_no,))
        if exist:
            pid = exist["id"]
    else:
        other = db.one("SELECT id FROM projects WHERE project_no=? AND id!=?", (project_no, pid))
        if other:
            raise ValueError(f"项目编号 {project_no} 已被另一个项目使用")
    if data.get("customer_id"):
        c = db.one("SELECT * FROM customers WHERE id=?", (int(data["customer_id"]),))
        if c and data.get("customer_aliases") is not None:
            if replace_aliases:
                # 编辑项目时：按填写的内容整体替换，允许删除别名
                db.update("customers", c["id"], {"aliases": split_list(data.get("customer_aliases"))})
                c = db.one("SELECT * FROM customers WHERE id=?", (c["id"],))
            elif split_list(data.get("customer_aliases")):
                c = upsert_customer(db, c["short_name"], c["full_name"], c["code"], data.get("customer_aliases"))
    else:
        c = upsert_customer(db, data.get("customer_short", ""), data.get("customer_full", ""),
                            data.get("customer_code", ""), data.get("customer_aliases"))
    if not c:
        raise ValueError("请填写客户")
    short = safe_dir_name(data.get("short_name") or derive_project_short(name, c["full_name"], c["short_name"]))
    row = {
        "project_no": project_no, "name": name, "short_name": short, "customer_id": c["id"],
        "biz_line": (data.get("biz_line") or "").strip(), "status": data.get("status") or "进行中",
        "start_date": _norm_date(data.get("start_date")), "end_date": _norm_date(data.get("end_date")),
        "keywords": split_list(data.get("keywords")), "dir_name": f"{project_no}_{short}",
    }
    if pid:
        old = db.one("SELECT * FROM projects WHERE id=?", (pid,))
        old_c = db.one("SELECT * FROM customers WHERE id=?", (old["customer_id"],))
        _rename_tree(db, customer_dir(old_c) / old["dir_name"], customer_dir(c) / row["dir_name"])
        db.update("projects", pid, row)
    else:
        row["created_at"] = now()
        pid = db.insert("projects", row)
    p = db.one("SELECT * FROM projects WHERE id=?", (pid,))
    ensure_project_dirs(db, p)
    return get_project(db, pid)


def _norm_date(v) -> str:
    if not v:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    m = re.match(r"^(\d{4})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s[:10]


# ---------------------------------------------------------------- 导入
HEADER_MAP = {
    "project_no": ["项目编号", "项目编码", "项目号", "编号"],
    "name": ["项目名称", "项目全称"],
    "short_name": ["项目简称"],
    "customer_full": ["客户名称", "客户全称", "客户"],
    "customer_short": ["客户简称"],
    "customer_code": ["客户编码", "客户编号"],
    "customer_aliases": ["客户别名", "别名"],
    "biz_line": ["业务线", "项目类型", "业务类型", "产品线"],
    "status": ["项目状态", "状态"],
    "start_date": ["开始日期", "开始时间", "立项日期"],
    "end_date": ["结束日期", "结束时间", "结项日期", "完成日期"],
    "keywords": ["关键词", "项目关键词"],
}
TEMPLATE_HEADER = ["项目编号", "项目名称", "项目简称", "客户名称", "客户简称", "客户编码", "客户别名",
                   "业务线", "项目状态", "开始日期", "结束日期", "关键词"]


def template_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(TEMPLATE_HEADER)
    w.writerow(["PRJ-2026-0123", "上海澄湾科技有限公司2026年等级保护测评项目", "等保测评2026",
                "上海澄湾科技有限公司", "澄湾科技", "", "澄湾、CW", "等保", "进行中",
                "2026-07-01", "2026-12-31", "核心业务系统、OA"])
    return "﻿" + buf.getvalue()


def _map_headers(headers: List[str]) -> Dict[int, str]:
    mapping: Dict[int, str] = {}
    for i, h in enumerate(headers):
        h = str(h or "").strip()
        for field, names in HEADER_MAP.items():
            if field in mapping.values():
                continue
            if h in names:
                mapping[i] = field
                break
    # 宽松匹配：包含关系
    for i, h in enumerate(headers):
        if i in mapping:
            continue
        h = str(h or "").strip()
        for field, names in HEADER_MAP.items():
            if field not in mapping.values() and any(n in h for n in names if len(n) >= 3):
                mapping[i] = field
                break
    return mapping


def read_table(filename: str, content: bytes) -> List[List]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return rows
    for enc in ("utf-8-sig", "gb18030"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = content.decode("utf-8", errors="ignore")
    return list(csv.reader(io.StringIO(text)))


def import_table(db: DB, filename: str, content: bytes) -> Tuple[int, int, List[str]]:
    rows = [r for r in read_table(filename, content) if any(str(c or "").strip() for c in r)]
    if not rows:
        raise ValueError("文件为空")
    # 表头可能不在第一行：找包含「项目编号」的行
    head_idx = 0
    for i, r in enumerate(rows[:10]):
        if any(str(c or "").strip() in HEADER_MAP["project_no"] for c in r):
            head_idx = i
            break
    mapping = _map_headers([str(c or "") for c in rows[head_idx]])
    if "project_no" not in mapping.values():
        raise ValueError("没有找到「项目编号」列，请参考导入模板")
    created = updated = 0
    errors: List[str] = []
    for n, r in enumerate(rows[head_idx + 1:], start=head_idx + 2):
        data = {}
        for i, field in mapping.items():
            if i < len(r) and r[i] is not None:
                data[field] = r[i] if isinstance(r[i], (date, datetime)) else str(r[i]).strip()
        if not data.get("project_no"):
            continue
        if not data.get("customer_full") and not data.get("customer_short"):
            errors.append(f"第 {n} 行缺少客户名称")
            continue
        exists = db.one("SELECT id FROM projects WHERE project_no=?", (data["project_no"],))
        try:
            save_project(db, data, exists["id"] if exists else None)
            if exists:
                updated += 1
            else:
                created += 1
        except Exception as e:
            errors.append(f"第 {n} 行：{e}")
    return created, updated, errors
