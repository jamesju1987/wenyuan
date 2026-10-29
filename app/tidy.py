"""整理归档库：把重复的客户文件夹合并到一起，没登记的规范文件重新登记。

重复一般这样产生：
1. 新版本解压到了另一个文件夹，用的是新的空数据库。重新导入 CRM 后客户编码、简称都可能变，
   新文件夹建在旧文件夹旁边。旧文件夹在数据库里查不到（网页上显示带编码的原名），
   里面的文件也搜不到、版本接不上。
2. 同一个客户在 CRM 或手工新建时写法不一样（全称、简称不一致），被当成了两个客户。

合并只移动文件，不删除内容；只有和目标位置「内容完全相同」的重复文件才只留一份。
"""
from __future__ import annotations

import difflib
import hashlib
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

from . import config, naming
from . import projects as P
from . import standards as S
from .db import DB, loads, now

JUNK = {"thumbs.db", "desktop.ini", ".ds_store"}
PAREN = re.compile(r"[（(][^（）()]{0,12}[）)]")
PUNCT = re.compile(r"[\s·•\-—_、,，.。:：'\"“”‘’]+")
NAME_PARSE = re.compile(
    r"^(?P<no>[^_]+)_(?P<type>[A-Z][A-Z0-9]*-[A-Z0-9]+)_(?P<title>[^_]+)_(?P<ver>V\d+\.\d+)_"
    r"(?P<status>草稿|内审|送审|正式|签字)_(?P<date>\d{8})(?:-\d+)?(?P<ext>\.[^.]+)?$")
EVIDENCE_DAY = re.compile(r"^(\d{4})(\d{2})(\d{2})_")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".heic"}


# ---------------------------------------------------------------- 名称比较
def project_no_of(dirname: str) -> str:
    return dirname.split("_", 1)[0]


def folder_base(dirname: str) -> str:
    """客户文件夹名去掉末尾的客户编码：青岚医疗器械有_C0012 → 青岚医疗器械有。"""
    return dirname.rsplit("_", 1)[0] if "_" in dirname else dirname


_norm_cache: Dict[str, str] = {}


def norm_name(s: str) -> str:
    """去掉括号里的地区、开头的省市、公司后缀和标点，只留能区分客户的部分。"""
    s = str(s or "")
    if s in _norm_cache:
        return _norm_cache[s]
    t = PAREN.sub("", s).strip()
    for p in P.REGION_PREFIX:
        if t.startswith(p) and len(t) > len(p) + 1:
            t = t[len(p):]
            break
    for suf in P.CORP_SUFFIX:
        t = t.replace(suf, "")
    t = PUNCT.sub("", t).lower()
    _norm_cache[s] = t
    return t


def _subseq(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def name_score(a: str, b: str) -> float:
    """1 = 实际是同一个名称；0.9 = 一个包含另一个；0.75 = 像是简称（云杉农商行 ≈ 云杉农村商业银行）。"""
    a, b = norm_name(a), norm_name(b)
    if len(a) < 2 or len(b) < 2:
        return 0.0
    if a == b:
        return 1.0
    s, l = sorted((a, b), key=len)
    if s in l:
        return 0.9 if (len(s) >= 3 or l.startswith(s)) else 0.0
    if len(s) >= 3 and s[0] == l[0] and len(l) <= len(s) * 2.5 and _subseq(s, l):
        return 0.75
    return 0.0


WHY = {1.0: "名称一样（只差地区或公司后缀）", 0.9: "一个名称包含另一个", 0.75: "看起来是简称"}


def names_of(c: Dict) -> List[str]:
    out: List[str] = []
    for n in [c.get("short_name"), c.get("full_name")] + list(loads(c.get("aliases"), []) or []):
        n = str(n or "").strip()
        if n and n not in out:
            out.append(n)
    return out


def customer_score(name: str, c: Dict) -> float:
    return max([name_score(name, n) for n in names_of(c)] + [0.0])


def pair_score(a: Dict, b: Dict) -> float:
    return max([name_score(x, y) for x in names_of(a) for y in names_of(b)] + [0.0])


# ---------------------------------------------------------------- 文件小工具
def walk_files(d: Path) -> Iterator[Path]:
    for dp, dns, fns in os.walk(d):
        dns[:] = [x for x in dns if not x.startswith(".")]
        for f in fns:
            if not f.startswith(".") and f.lower() not in JUNK:
                yield Path(dp) / f


def count_files(d: Path) -> int:
    return sum(1 for _ in walk_files(d)) if d.is_dir() else 0


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def same_file(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and sha256_of(a) == sha256_of(b)
    except OSError:
        return False


def _key(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def rel_of(p: Path) -> str:
    try:
        return p.relative_to(config.root()).as_posix()
    except ValueError:
        return str(p)


def canonical_dir(db: DB, p: Dict) -> Path:
    return P.project_dir(p, db=db)


class Mover:
    """把一个文件夹并进另一个：目标不存在就整体挪过去；存在就逐个合并。"""

    def __init__(self) -> None:
        self.maps: List[Tuple[str, str, bool]] = []   # (原路径, 新路径, 是否文件夹)
        self.sources: List[str] = []
        self.moved = self.dups = self.renamed = 0
        self.errors: List[str] = []

    def merge(self, src: Path, dst: Path) -> None:
        if not src.exists() or _key(src) == _key(dst):
            return
        if src.is_dir() and not any(walk_files(src)):
            self.prune(src)                        # 只剩空的阶段目录：直接删掉，不挪过去占地方
            if not src.exists():
                return
        if dst.exists() and dst.is_dir() != src.is_dir():
            dst = naming.unique_path(dst)          # 同名但一个是文件夹一个是文件
            self.renamed += 1
        if not dst.exists():
            n = count_files(src) if src.is_dir() else 1
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                self.maps.append((str(src), str(dst), src.is_dir() or dst.is_dir()))
                self.moved += n
                return
            except OSError:
                if not src.is_dir():
                    self.errors.append(f"{rel_of(src)}：没能移动，可能正被打开")
                    return
                dst.mkdir(parents=True, exist_ok=True)     # 整体挪不动（里面有文件被占用），改成逐个挪
        if src.is_file():
            self._file(src, dst)
            return
        for child in sorted(src.iterdir(), key=lambda x: x.name):
            self.merge(child, dst / child.name) if child.is_dir() else self._file(child, dst / child.name)
        try:
            src.rmdir()
        except OSError:
            pass

    def _file(self, f: Path, t: Path) -> None:
        try:
            if t.exists() and t.is_file():
                if f.name.lower() in JUNK or same_file(f, t):
                    f.unlink()                     # 内容完全一样：留目标那份
                    self.maps.append((str(f), str(t), False))
                    self.dups += 1
                    return
                t = naming.unique_path(t)
                self.renamed += 1
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(t))
            self.maps.append((str(f), str(t), False))
            self.moved += 1
        except OSError as e:
            self.errors.append(f"{rel_of(f)}：{e.strerror or e}")

    @staticmethod
    def prune(d: Path) -> None:
        """删掉空文件夹（只删空的；Thumbs.db 这类系统小文件不算内容）。"""
        if not d.is_dir():
            return
        for dp, _dns, fns in os.walk(d, topdown=False):
            for f in fns:
                if f.lower() in JUNK:
                    try:
                        os.unlink(os.path.join(dp, f))
                    except OSError:
                        pass
            try:
                os.rmdir(dp)
            except OSError:
                pass

    def apply(self, db: DB) -> None:
        """把数据库里的路径改成新位置。"""
        if not self.maps:
            return

        def remap(path: str) -> str:
            for old, new, is_dir in self.maps:
                if path == old:
                    path = new
                elif is_dir and (path.startswith(old + os.sep) or path.startswith(old + "/")):
                    path = new + path[len(old):]
            return path

        prefixes = tuple({m[0] for m in self.maps})
        active = {r["archive_path"]: r["id"] for r in db.q(
            "SELECT id, archive_path FROM files WHERE state IN ('archived','superseded')")}
        for f in db.q("SELECT id, archive_path, state FROM files WHERE archive_path IS NOT NULL AND archive_path != ''"):
            ap = f["archive_path"]
            if not ap.startswith(prefixes):
                continue
            new = remap(ap)
            if new == ap:
                continue
            ch = {"archive_path": new}
            other = active.get(new)
            if other and other != f["id"] and f["state"] in ("archived", "superseded"):
                ch["state"] = "merged"           # 同一个文件已经有记录了
            db.update("files", f["id"], ch)
        for j in db.q("SELECT id, staged_path FROM jobs WHERE staged_path IS NOT NULL AND staged_path != ''"):
            sp = j["staged_path"]
            if sp.startswith(prefixes):
                new = remap(sp)
                if new != sp:
                    db.update("jobs", j["id"], {"staged_path": new})
        self.maps.clear()


# ---------------------------------------------------------------- 检查
def scan(db: DB, quick: bool = False) -> Dict:
    """quick=True 只判断有没有重复（归档库页面的提示条用），不统计文件数。"""
    root = config.root()
    cnt = (lambda d: None) if quick else count_files
    out: Dict = {"groups": [], "loose": [], "unindexed": 0, "customers": []}
    customers = db.q("SELECT * FROM customers ORDER BY id")
    out["customers"] = sorted([{"id": c["id"], "name": c["short_name"], "full": c["full_name"]} for c in customers],
                              key=lambda x: x["name"])
    if not root.is_dir():
        return out
    cust = {c["id"]: c for c in customers}
    by_dir = {c["dir_name"]: c for c in customers}
    projects = db.q("SELECT * FROM projects")
    by_no = {p["project_no"]: p for p in projects}
    pcount = Counter(p["customer_id"] for p in projects)
    fcount = {r["cid"]: r["n"] for r in db.q(
        "SELECT p.customer_id cid, COUNT(*) n FROM files f JOIN projects p ON p.id=f.project_id "
        "WHERE f.state='archived' GROUP BY p.customer_id")}
    items: Dict[int, List[Dict]] = defaultdict(list)

    for d in sorted(root.iterdir(), key=lambda x: x.name):
        if not d.is_dir() or d.name.startswith(".") or d.name in config.SYSTEM_DIRS:
            continue
        subs = sorted([x for x in d.iterdir() if x.is_dir() and not x.name.startswith(".")], key=lambda x: x.name)
        c = by_dir.get(d.name)
        if c:
            own = {p["dir_name"] for p in projects if p["customer_id"] == c["id"]}
            for sub in subs:
                p = by_no.get(project_no_of(sub.name))
                if sub.name in own or not p:
                    continue
                pc = cust[p["customer_id"]]
                items[p["customer_id"]].append({
                    "kind": "folder", "path": rel_of(sub), "name": f"{d.name}/{sub.name}", "files": cnt(sub),
                    "reason": f"项目 {p['project_no']} 的另一个文件夹，正式目录是「{pc['dir_name']}/{p['dir_name']}」",
                    "checked": True})
            continue
        info = {"kind": "folder", "path": rel_of(d), "name": d.name, "files": cnt(d)}
        hits: Counter = Counter()
        nos: List[str] = []
        for sub in subs:
            p = by_no.get(project_no_of(sub.name))
            if p:
                hits[p["customer_id"]] += 1
                nos.append(p["project_no"])
        if hits:
            cid = hits.most_common(1)[0][0]
            info.update(reason=f"里面有项目 {'、'.join(nos[:2])}{' 等' if len(nos) > 2 else ''}，"
                               f"这些项目现在在「{cust[cid]['short_name']}」名下", checked=True)
            items[cid].append(info)
            continue
        base = folder_base(d.name)
        best, bc = 0.0, None
        for c2 in customers:
            s = customer_score(base, c2)
            if s > best:
                best, bc = s, c2
        if bc and best >= 0.75:
            info.update(reason=f"名称相近：「{base}」和「{bc['short_name']}」", checked=best >= 0.9)
            items[bc["id"]].append(info)
        else:
            info.update(reason="没有找到对应的客户", checked=False)
            out["loose"].append(info)

    # 数据库里名称相近的客户：连成一组，项目最多的那个作为保留的客户
    parent = {c["id"]: c["id"] for c in customers}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    scores: Dict[Tuple[int, int], float] = {}
    for i, a in enumerate(customers):
        for b in customers[i + 1:]:
            s = pair_score(a, b)
            if s >= 0.75:
                scores[(a["id"], b["id"])] = scores[(b["id"], a["id"])] = s
                parent[find(a["id"])] = find(b["id"])
    comps: Dict[int, List[Dict]] = defaultdict(list)
    for c in customers:
        comps[find(c["id"])].append(c)
    head: Dict[int, int] = {}
    for members in comps.values():
        if len(members) < 2:
            continue
        t = max(members, key=lambda c: (pcount.get(c["id"], 0), fcount.get(c["id"], 0), -c["id"]))
        for m in members:
            head[m["id"]] = t["id"]
            if m["id"] == t["id"]:
                continue
            s = scores.get((m["id"], t["id"])) or max(v for (x, _), v in scores.items() if x == m["id"])
            items[t["id"]].append({
                "kind": "customer", "id": m["id"], "name": m["short_name"], "full": m["full_name"],
                "dir": m["dir_name"], "projects": pcount.get(m["id"], 0), "files": fcount.get(m["id"], 0),
                "reason": WHY.get(s, "名称相近"), "checked": s >= 1.0})

    groups: Dict[int, List[Dict]] = defaultdict(list)
    for cid, its in items.items():
        groups[head.get(cid, cid)].extend(its)
    for t, its in sorted(groups.items(), key=lambda kv: cust[kv[0]]["short_name"]):
        c = cust[t]
        its.sort(key=lambda x: (x["kind"] != "customer", not x["checked"], x["name"]))
        out["groups"].append({"target": {"id": t, "name": c["short_name"], "full": c["full_name"],
                                         "dir": c["dir_name"], "projects": pcount.get(t, 0),
                                         "files": fcount.get(t, 0)}, "items": its})
    if not quick:
        out["unindexed"] = sum(1 for _ in _unindexed(db))
    return out


# ---------------------------------------------------------------- 合并
def _merge_children(db: DB, mv: Mover, sdir: Path, tdir: Path, touched: Set[int]) -> None:
    """文件夹里的项目文件夹并到各自项目的正式目录，其他东西放进目标客户文件夹。"""
    by_no = {p["project_no"]: p for p in db.q("SELECT * FROM projects")}
    for child in sorted(sdir.iterdir(), key=lambda x: x.name):
        if child.is_dir():
            p = by_no.get(project_no_of(child.name))
            if p:
                mv.merge(child, canonical_dir(db, p))
                touched.add(p["id"])
                continue
        mv.merge(child, tdir / child.name)


def merge_customer(db: DB, mv: Mover, src: Dict, target: Dict, touched: Set[int]) -> None:
    sdir, tdir = P.customer_dir(src), P.customer_dir(target)
    mv.sources.append(str(sdir))
    for p in db.q("SELECT * FROM projects WHERE customer_id=?", (src["id"],)):
        db.update("projects", p["id"], {"customer_id": target["id"]})
        mv.merge(sdir / p["dir_name"], tdir / p["dir_name"])
        touched.add(p["id"])
    if sdir.is_dir() and _key(sdir) != _key(tdir):
        _merge_children(db, mv, sdir, tdir, touched)
        mv.prune(sdir)
    # 旧名称留作别名：以后文件里出现旧叫法也能认出来
    target = db.one("SELECT * FROM customers WHERE id=?", (target["id"],))
    keep = names_of(target)
    aliases = list(loads(target["aliases"], []) or [])
    for n in names_of(src):
        if n not in keep and n not in aliases:
            aliases.append(n)
    db.update("customers", target["id"], {"aliases": aliases})
    db.insert("customer_merges", {"code": src["code"], "short_name": src["short_name"], "full_name": src["full_name"],
                                  "target_id": target["id"], "created_at": now()})
    db.x("UPDATE customer_merges SET target_id=? WHERE target_id=?", (target["id"], src["id"]))
    db.x("DELETE FROM customers WHERE id=?", (src["id"],))


def merge_folder(db: DB, mv: Mover, src: Path, target: Dict, touched: Set[int]) -> None:
    root = config.root()
    mv.sources.append(str(src))
    if _key(src.parent) == _key(root):
        _merge_children(db, mv, src, P.customer_dir(target), touched)
        mv.prune(src)
        return
    p = db.one("SELECT * FROM projects WHERE project_no=?", (project_no_of(src.name),))
    if not p:
        mv.errors.append(f"{rel_of(src)}：找不到对应的项目")
        return
    mv.merge(src, canonical_dir(db, p))
    touched.add(p["id"])


def _check_folder(rel: str) -> Path:
    root = config.root().resolve()
    p = (root / rel).resolve()
    if root not in p.parents:
        raise ValueError(f"不在归档库里：{rel}")
    if not p.is_dir():
        raise ValueError(f"文件夹不存在：{rel}")
    if p.parent == root and p.name in config.SYSTEM_DIRS:
        raise ValueError(f"系统文件夹不能合并：{rel}")
    return config.root() / p.relative_to(root)


def merge(db: DB, groups: List[Dict], reindex_all: bool = True) -> Dict:
    mv = Mover()
    touched: Set[int] = set()
    customers = folders = 0
    registered_dirs = {c["dir_name"] for c in db.q("SELECT dir_name FROM customers")}
    for g in groups:
        target = db.one("SELECT * FROM customers WHERE id=?", (int(g.get("target") or 0),))
        if not target:
            mv.errors.append("保留的客户不存在，请刷新后重试")
            continue
        for cid in g.get("customers") or []:
            src = db.one("SELECT * FROM customers WHERE id=?", (int(cid),))
            if src and src["id"] != target["id"]:
                merge_customer(db, mv, src, target, touched)
                customers += 1
        for rel in g.get("folders") or []:
            try:
                src = _check_folder(rel)
            except ValueError as e:
                mv.errors.append(str(e))
                continue
            if src.parent == config.root() and src.name in registered_dirs:
                mv.errors.append(f"「{rel}」是在用的客户文件夹，请按客户合并")
                continue
            merge_folder(db, mv, src, target, touched)
            folders += 1
    mv.apply(db)
    for pid in touched:                       # 合并后补齐标准阶段目录
        p = db.one("SELECT * FROM projects WHERE id=?", (pid,))
        if p:
            P.ensure_project_dirs(db, p)
    registered = reindex(db) if reindex_all or touched else 0
    return {"customers": customers, "folders": folders, "moved": mv.moved, "duplicates": mv.dups,
            "renamed": mv.renamed, "registered": registered, "errors": mv.errors[:20],
            "error_count": len(mv.errors)}


# ---------------------------------------------------------------- 导入时自动接上旧文件夹
def adopt_project_folders(db: DB, pids: Optional[Set[int]] = None) -> Dict:
    """同一个项目编号在归档库里还有别的文件夹（比如换了数据库后旧客户文件夹里的），并到项目的正式目录。"""
    root = config.root()
    out = {"folders": 0, "moved": 0, "registered": 0, "errors": []}
    if not root.is_dir():
        return out
    customers = db.q("SELECT * FROM customers")
    reg = {c["dir_name"] for c in customers}
    by_no = {p["project_no"]: p for p in db.q("SELECT * FROM projects")}
    mv = Mover()
    touched: Set[int] = set()
    emptied: List[Path] = []
    for d in sorted(root.iterdir(), key=lambda x: x.name):
        if not d.is_dir() or d.name.startswith(".") or d.name in config.SYSTEM_DIRS:
            continue
        for sub in sorted(d.iterdir(), key=lambda x: x.name):
            if not sub.is_dir() or sub.name.startswith("."):
                continue
            p = by_no.get(project_no_of(sub.name))
            if not p or (pids is not None and p["id"] not in pids):
                continue
            dst = canonical_dir(db, p)
            if _key(sub) == _key(dst):
                continue
            mv.sources.append(str(sub))
            mv.merge(sub, dst)
            touched.add(p["id"])
            out["folders"] += 1
            if d.name not in reg:
                emptied.append(d)
    for d in emptied:
        Mover.prune(d)          # 旧客户文件夹挪空了就删掉
    mv.apply(db)
    out["moved"] = mv.moved
    out["errors"] = mv.errors[:20]
    if touched:
        out["registered"] = reindex(db)
    return out


# ---------------------------------------------------------------- 重新登记
def _unindexed(db: DB) -> Iterator[Tuple[Dict, Path, Path, Optional[re.Match]]]:
    """项目目录里按规范命名、但数据库里没有记录的文件（以及证据文件夹里的文件）。"""
    known = {_key(r["archive_path"]) for r in db.q(
        "SELECT archive_path FROM files WHERE state IN ('archived','superseded') AND archive_path IS NOT NULL")}
    cust = {c["id"]: c for c in db.q("SELECT * FROM customers")}
    for p in db.q("SELECT * FROM projects ORDER BY id"):
        c = cust.get(p["customer_id"])
        if not c:
            continue
        pdir = P.customer_dir(c) / p["dir_name"]
        if not pdir.is_dir():
            continue
        for f in walk_files(pdir):
            if _key(f) in known:
                continue
            parts = f.relative_to(pdir).parts
            if parts[0] == S.PACKAGE_DIR:
                continue
            if "/".join(parts).startswith(S.EVIDENCE_DIR + "/"):
                yield p, pdir, f, None
                continue
            m = NAME_PARSE.match(f.name)
            if m and m.group("no") == p["project_no"]:
                yield p, pdir, f, m


def _register(db: DB, p: Dict, f: Path, doc_id: Optional[int], dtype: str, version: str, status: str,
              title: str, doc_date: str, state: str) -> None:
    st = f.stat()
    db.insert("files", {
        "job_id": None, "document_id": doc_id, "project_id": p["id"], "doc_type": dtype, "version": version,
        "status": status, "archive_name": f.name, "archive_path": str(f), "original_name": f.name,
        "source": "整理归档库", "sha256": sha256_of(f), "size": st.st_size, "doc_date": doc_date, "title": title,
        "summary": "", "snippet": "", "sensitivity": "高" if dtype in S.SENSITIVE_TYPES else "一般",
        "state": state, "created_at": now()})


def _find_doc(db: DB, pid: int, dtype: str, title: str) -> Optional[Dict]:
    best, best_r = None, 0.0
    for d in db.q("SELECT * FROM documents WHERE project_id=? AND doc_type=?", (pid, dtype)):
        r = difflib.SequenceMatcher(None, title.lower(), str(d["title"]).lower()).ratio()
        if r > best_r:
            best, best_r = d, r
    return best if best_r >= 0.8 else None


def reindex(db: DB) -> int:
    n = 0
    docs: Dict[Tuple[int, str, str], List] = defaultdict(list)
    for p, pdir, f, m in list(_unindexed(db)):
        try:
            if m is None:
                day = EVIDENCE_DAY.match(f.parent.name)
                d = f"{day.group(1)}-{day.group(2)}-{day.group(3)}" if day else \
                    date.fromtimestamp(f.stat().st_mtime).isoformat()
                _register(db, p, f, None, "EVD-SHOT" if f.suffix.lower() in IMAGE_EXT else "EVD-SCAN", "", "正式",
                          f.stem, d, "archived")
                n += 1
                continue
            hist = f.relative_to(pdir).parts[0] == S.HISTORY_DIR
            docs[(p["id"], m.group("type"), m.group("title"))].append((p, f, m, hist))
        except OSError:
            continue
    for (pid, dtype, title), entries in docs.items():
        entries.sort(key=lambda e: naming.parse_version(e[2].group("ver")))
        series = bool((S.TYPE_MAP.get(dtype) or {}).get("series"))
        batches = [[e] for e in entries] if series else [entries]
        for batch in batches:
            current = [e for e in batch if not e[3]] or batch
            top = current[-1][2]
            doc = None if series else _find_doc(db, pid, dtype, title)
            if doc:
                if naming.parse_version(top.group("ver")) > naming.parse_version(doc["current_version"]):
                    db.update("documents", doc["id"], {"current_version": top.group("ver"),
                                                       "status": top.group("status"), "updated_at": now()})
                doc_id = doc["id"]
            else:
                doc_id = db.insert("documents", {"project_id": pid, "doc_type": dtype, "title": title,
                                                 "current_version": top.group("ver"), "status": top.group("status"),
                                                 "created_at": now(), "updated_at": now()})
            for p, f, m, hist in batch:
                d = m.group("date")
                try:
                    _register(db, p, f, doc_id, dtype, m.group("ver"), m.group("status"), m.group("title"),
                              f"{d[:4]}-{d[4:6]}-{d[6:]}", "superseded" if hist else "archived")
                    n += 1
                except OSError:
                    continue
    return n
