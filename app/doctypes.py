"""交付物类型的增改删：新增自定义类型、给内置类型追加识别关键词、停用或删除不再用的自定义类型。

内置的 31 个类型不能删、名称和目录不能改，只能追加关键词；自定义类型都可以改，
已经有文件在用的自定义类型不能删除（可以停用：不再参与识别和选择，老文件照常显示名称）。
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from . import standards as S
from .db import DB, now

NAME_BAD = re.compile(r"[_/\\:*?\"<>|]")


def load(db: DB) -> None:
    S.apply_types(db.q("SELECT * FROM doc_types"))


def split_keywords(v) -> List[str]:
    items = v if isinstance(v, list) else re.split(r"[、,，;；\n\r\t ]+", str(v or ""))
    out: List[str] = []
    for k in items:
        k = str(k).strip()
        if k and k not in out and len(k) <= 20:
            out.append(k)
    if len(out) > 40:
        raise ValueError("关键词最多 40 个")
    return out


def usage(db: DB, code: str) -> Dict[str, int]:
    c = lambda sql: (db.one(sql, (code,)) or {}).get("n", 0)  # noqa: E731
    return {"files": c("SELECT COUNT(*) n FROM files WHERE doc_type=? AND state IN ('archived','superseded')"),
            "rules": c("SELECT COUNT(*) n FROM rules WHERE doc_type=?")}


def list_types(db: DB) -> List[Dict]:
    counts = {r["doc_type"]: r["n"] for r in db.q(
        "SELECT doc_type, COUNT(*) n FROM files WHERE state='archived' GROUP BY doc_type")}
    out = []
    for t in S.TYPE_MAP.values():
        base = [k for k in t["kw"] if k not in t.get("extra_kw", [])] if t.get("builtin") else t["kw"]
        out.append({"code": t["code"], "name": t["name"], "stage": t["stage"], "keywords": base,
                    "extra_keywords": t.get("extra_kw", []), "series": bool(t.get("series")),
                    "evidence": bool(t.get("evidence")), "builtin": bool(t.get("builtin")),
                    "enabled": bool(t.get("enabled", True)), "files": counts.get(t["code"], 0)})
    return out


def _check_name(name: str, code: Optional[str] = None) -> str:
    name = (name or "").strip()
    if not 2 <= len(name) <= 20:
        raise ValueError("类型名称要 2–20 个字")
    if NAME_BAD.search(name):
        raise ValueError("类型名称里不能有 _ / \\ : * ? \" < > | 这些字符")
    for t in S.TYPE_MAP.values():
        if t["name"] == name and t["code"] != code:
            raise ValueError(f"已经有叫「{name}」的类型（{t['code']}）")
    return name


def _check_stage(stage: str) -> str:
    if stage not in S.TYPE_STAGES:
        raise ValueError("请选择归档目录")
    return stage


def create(db: DB, data: Dict) -> Dict:
    code = str(data.get("code") or "").strip().upper()
    if not S.TYPE_CODE_RE.match(code):
        raise ValueError("类型码格式：大写字母开头，2–8 位字母数字 + 短横线 + 2–10 位字母数字，例如 ACC-FWSX")
    if code in S.TYPE_MAP or db.one("SELECT code FROM doc_types WHERE code=?", (code,)):
        raise ValueError(f"类型码 {code} 已经存在")
    name = _check_name(data.get("name", ""))
    stage = _check_stage(data.get("stage", ""))
    kw = split_keywords(data.get("keywords", ""))
    if name not in kw:
        kw.insert(0, name)                    # 类型名称本身就是最直接的关键词
    db.x("INSERT INTO doc_types (code, name, stage, kw, series, enabled, builtin, created_at) VALUES (?,?,?,?,?,1,0,?)",
         (code, name, stage, json.dumps(kw, ensure_ascii=False), 1 if data.get("series") and stage != S.EVIDENCE_DIR else 0,
          now()))
    load(db)
    return S.TYPE_MAP[code]


def update(db: DB, code: str, data: Dict) -> Dict:
    t = S.TYPE_MAP.get(code)
    if not t:
        raise ValueError("类型不存在")
    if t.get("builtin"):
        extra = [k for k in split_keywords(data.get("extra_keywords", "")) if k not in t["kw"] or k in t.get("extra_kw", [])]
        db.x("INSERT INTO doc_types (code, kw, builtin, created_at) VALUES (?,?,1,?) "
             "ON CONFLICT(code) DO UPDATE SET kw=excluded.kw", (code, json.dumps(extra, ensure_ascii=False), now()))
    else:
        row = db.one("SELECT * FROM doc_types WHERE code=?", (code,)) or {}
        name = _check_name(data["name"], code) if data.get("name") is not None else row.get("name")
        stage = _check_stage(data["stage"]) if data.get("stage") is not None else row.get("stage")
        kw = split_keywords(data["keywords"]) if data.get("keywords") is not None else json.loads(row.get("kw") or "[]")
        series = data["series"] if data.get("series") is not None else bool(row.get("series"))
        enabled = data["enabled"] if data.get("enabled") is not None else bool(row.get("enabled", 1))
        db.x("UPDATE doc_types SET name=?, stage=?, kw=?, series=?, enabled=? WHERE code=?",
             (name, stage, json.dumps(kw, ensure_ascii=False), 1 if series and stage != S.EVIDENCE_DIR else 0,
              1 if enabled else 0, code))
    load(db)
    return S.TYPE_MAP[code]


def delete(db: DB, code: str) -> None:
    t = S.TYPE_MAP.get(code)
    if not t:
        raise ValueError("类型不存在")
    if t.get("builtin"):
        raise ValueError("内置类型不能删除")
    u = usage(db, code)
    if u["files"] or u["rules"]:
        what = "、".join(x for x in [f"{u['files']} 个已归档文件" if u["files"] else "",
                                     f"{u['rules']} 条规则" if u["rules"] else ""] if x)
        raise ValueError(f"已有{what}在用这个类型，不能删除；可以改成「停用」")
    db.x("DELETE FROM doc_types WHERE code=?", (code,))
    load(db)
