"""持续学习：参考历史归档（相似文件沿用项目和类型）+ 人工确认后自动生成规则。

只使用本机数据库里的历史记录，不调用任何模型。
"""
from __future__ import annotations

import math
import re
import threading
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import config
from . import standards as S
from .db import DB, loads, now

PROJECT_NO_RE = re.compile(r"[A-Za-z]{2,8}-\d{4}-[A-Za-z0-9]{3,20}")
DATE_RE = re.compile(r"(20\d{2})\s*[年\-/\.]?\s*\d{1,2}\s*[月\-/\.]?\s*\d{1,2}\s*日?")
VERSION_RE = re.compile(r"(?i)(?<![a-z])v\s*\d+(\.\d+)*(?![a-z])")
COPY_RE = re.compile(r"[\(（【\[]\s*\d{1,2}\s*[\)）】\]]")
EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,6}$")
SPLIT_RE = re.compile(r"[\s_\-—–·,，;；:：、/\\|+()（）【】\[\]{}《》<>\"'“”‘’.!！?？#&@=~`^*%$]+|\d+")
TOKEN_RE = re.compile(r"[a-z][a-z0-9]+|[一-鿿]+")

# 不适合作为规则的泛词
STOPWORDS: Set[str] = {
    "项目", "服务", "文件", "文档", "资料", "附件", "版本", "新建", "公司", "有限", "集团", "有限公司", "年度", "月份",
    "关于", "以及", "报告", "方案", "记录", "清单", "说明", "材料", "汇总", "表格", "通知", "汇报", "总结", "工作",
    "安全", "系统", "平台", "测试", "检查", "评估", "管理", "信息", "技术", "网络", "数据", "第一", "第二", "最终",
    "上海", "北京", "中国", "word", "microsoft", "doc", "docx", "pdf", "xlsx", "pptx", "copy", "final", "img",
    "image", "scan", "new", "draft", "the", "and", "for", "微信图片", "截图", "屏幕截图", "图片", "副本", "签字", "盖章",
}


def _norm_name(name: str) -> str:
    s = EXT_RE.sub("", name or "")
    s = PROJECT_NO_RE.sub(" ", s)
    s = DATE_RE.sub(" ", s)
    s = VERSION_RE.sub(" ", s)
    s = COPY_RE.sub(" ", s)
    for w in sorted(S.NOISE_WORDS, key=len, reverse=True):
        s = s.replace(w, " ")
    return s


def match_text(name: str) -> str:
    """用于规则匹配的文件名形态：去掉扩展名、编号、日期、版本号，转小写。"""
    return _norm_name(name).lower()


def _vocab_to_remove(customers: Iterable[Dict]) -> List[str]:
    words: Set[str] = set()
    for c in customers:
        for n in [c.get("short_name"), c.get("full_name"), *(loads(c.get("aliases"), []) or [])]:
            if n and len(n) >= 2:
                words.add(n)
    for t in S.TYPE_CODES:
        words.update(k for k in t["kw"] if len(k) >= 2)
    for kws in S.STATUS_KEYWORDS.values():
        words.update(k for k in kws if len(k) >= 2)
    words.update(S.GARBAGE_TITLES)
    return sorted(words, key=len, reverse=True)


def candidate_terms(name: str, remove_words: List[str]) -> List[str]:
    """从文件名里取出可以当规则的词：去掉客户名称、类型关键词、日期编号等通用部分后剩下的片段。"""
    s = _norm_name(name)
    low = s.lower()
    for w in remove_words:
        wl = w.lower()
        i = low.find(wl)
        while i >= 0:
            s = s[:i] + " " * len(w) + s[i + len(w):]
            low = s.lower()
            i = low.find(wl, i + len(w))
    out: List[str] = []
    for seg in SPLIT_RE.split(s):
        seg = (seg or "").strip()
        if not seg:
            continue
        has_cjk = bool(re.search(r"[一-鿿]", seg))
        if len(seg) < (2 if has_cjk else 3) or len(seg) > 16:
            continue
        if seg.lower() in STOPWORDS or seg in STOPWORDS:
            continue
        if re.fullmatch(r"[A-Za-z]{1,2}", seg):
            continue
        if seg not in out:
            out.append(seg)
    return out


# ---------------------------------------------------------------- 相似度
def tokens(text: str) -> Set[str]:
    s = _norm_name(text).lower()
    out: Set[str] = set()
    for m in TOKEN_RE.finditer(s):
        seg = m.group()
        if seg[0].isascii():
            if len(seg) >= 2 and seg not in STOPWORDS:
                out.add(seg)
        elif len(seg) == 1:
            out.add(seg)
        else:
            out.update(seg[i:i + 2] for i in range(len(seg) - 1))
    return out


class History:
    """已归档文件的检索索引；文件有变化时自动重建。"""

    TEXT_CHARS = 160
    MIN_SIM = 0.45

    def __init__(self, db: DB):
        self.db = db
        self.lock = threading.RLock()
        self.sig: Tuple = ()
        self.docs: List[Dict] = []
        self.idf: Dict[str, float] = {}

    def _signature(self) -> Tuple:
        r = self.db.one("SELECT COUNT(*) n, MAX(id) m, SUM(CASE WHEN state IN ('archived','superseded') THEN 1 ELSE 0 END) a "
                        "FROM files") or {}
        return (r.get("n"), r.get("m"), r.get("a"))

    def refresh(self) -> None:
        with self.lock:
            sig = self._signature()
            if sig == self.sig:
                return
            rows = self.db.q("""SELECT f.id, f.project_id, f.doc_type, f.original_name, f.title, f.snippet,
                                j.method FROM files f LEFT JOIN jobs j ON j.id=f.job_id
                                WHERE f.state IN ('archived','superseded') AND f.project_id IS NOT NULL""")
            docs, df = [], defaultdict(int)
            for r in rows:
                name_t = tokens(r["original_name"] or "") | tokens(r["title"] or "")
                text_t = tokens((r["snippet"] or "")[: self.TEXT_CHARS])
                for t in name_t | text_t:
                    df[t] += 1
                docs.append({"id": r["id"], "project_id": r["project_id"], "doc_type": r["doc_type"],
                             "name": r["original_name"] or "", "manual": (r["method"] or "") == "人工",
                             "name_t": name_t, "text_t": text_t})
            n = max(1, len(docs))
            self.idf = {t: math.log(1 + n / c) for t, c in df.items()}
            self.docs = docs
            self.sig = sig

    def _cos(self, a: Set[str], b: Set[str]) -> float:
        if not a or not b:
            return 0.0
        common = a & b
        if not common:
            return 0.0
        dflt = math.log(1 + max(1, len(self.docs)))
        w = lambda t: self.idf.get(t, dflt) ** 2  # noqa: E731
        dot = sum(w(t) for t in common)
        return dot / math.sqrt(sum(w(t) for t in a) * sum(w(t) for t in b))

    def suggest(self, file_name: str, folder: str, text: str, allowed: Optional[Set[int]] = None) -> Optional[Dict]:
        self.refresh()
        if not self.docs:
            return None
        q_name = tokens(file_name) | tokens(folder or "")
        q_text = tokens((text or "")[: self.TEXT_CHARS])
        if not q_name and not q_text:
            return None
        scored = []
        for d in self.docs:
            if allowed is not None and d["project_id"] not in allowed:
                continue
            ns = self._cos(q_name, d["name_t"])
            ts = self._cos(q_text, d["text_t"]) if q_text and d["text_t"] else 0.0
            sim = max(ns, (ns + ts) / 2) if ts else ns
            if sim >= self.MIN_SIM:
                scored.append((sim, d))
        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:7]

        def vote(key: str) -> Tuple[Optional[object], float, float, int, Dict]:
            acc: Dict = defaultdict(float)
            best: Dict = {}
            count: Dict = defaultdict(int)
            for sim, d in top:
                k = d[key]
                if not k:
                    continue
                acc[k] += sim * (1.3 if d["manual"] else 1.0)
                count[k] += 1
                if k not in best or sim > best[k][0]:
                    best[k] = (sim, d)
            if not acc:
                return None, 0.0, 0.0, 0, {}
            k = max(acc, key=acc.get)
            share = acc[k] / sum(acc.values())
            return k, share, best[k][0], count[k], best[k][1]

        pid, pshare, psim, pcount, pdoc = vote("project_id")
        tcode, tshare, tsim, tcount, tdoc = vote("doc_type")
        res: Dict = {}
        if pid:
            conf = 0.5 + 0.45 * min(1.0, psim) * pshare + (0.03 if pcount >= 2 else 0.0)
            res.update(project_id=pid, project_conf=round(min(0.96, conf), 3), project_like=pdoc["name"],
                       project_sim=round(psim, 3))
        if tcode:
            conf = 0.5 + 0.45 * min(1.0, tsim) * tshare + (0.03 if tcount >= 2 else 0.0)
            res.update(doc_type=tcode, type_conf=round(min(0.96, conf), 3), type_like=tdoc["name"])
        return res or None


# ---------------------------------------------------------------- 自动生成规则
def learn_after_confirm(db: DB, file_id: int) -> Dict[str, List[Dict]]:
    """人工确认归档后调用：同类文件（文件名里同一个特征词）人工确认达到次数且结论一致时，生成规则；
    与本次确认矛盾的自动规则会被停用。"""
    out: Dict[str, List[Dict]] = {"learned": [], "disabled": []}
    f = db.one("SELECT * FROM files WHERE id=?", (file_id,))
    if not f or not f.get("project_id"):
        return out
    name = f.get("original_name") or ""
    mt = match_text(name)

    # 1) 纠正：命中但结论不同的自动规则 → 停用
    for r in db.q("SELECT * FROM rules WHERE enabled=1 AND source='auto'"):
        pat = (r["pattern"] or "").lower()
        if not pat or pat not in mt:
            continue
        wrong = (r["kind"] == "type" and r["doc_type"] != f["doc_type"]) or \
                (r["kind"] != "type" and r["project_id"] != f["project_id"])
        if wrong:
            db.update("rules", r["id"], {"enabled": 0})
            out["disabled"].append({"pattern": r["pattern"], "kind": r["kind"]})

    if not config.get("learn_enabled"):
        return out
    need = max(2, int(config.get("learn_min_samples") or 2))
    remove = _vocab_to_remove(db.q("SELECT short_name, full_name, aliases FROM customers"))
    segs = candidate_terms(name, remove)
    if not segs:
        return out
    existing = [(r["pattern"] or "").lower() for r in db.q("SELECT pattern FROM rules")]
    rows = db.q("""SELECT f.id, f.original_name, f.project_id, f.doc_type, j.method FROM files f
                   LEFT JOIN jobs j ON j.id=f.job_id WHERE f.state IN ('archived','superseded')""")
    for r in rows:
        r["mt"] = match_text(r["original_name"] or "")

    # 中文文件名没有分隔符：在本文件的片段里找各个子串，看历史上哪些文件也含有它
    cands: Set[str] = set()
    for seg in segs:
        cands.update(_substrings(seg))
    seg_cache: Dict[int, Set[str]] = {}

    def natural(t: str, hits: List[Dict]) -> bool:
        """t 是否在某个文件里是一个完整片段（而不是半个词）。"""
        tl = t.lower()
        for r in hits:
            if r["id"] not in seg_cache:
                seg_cache[r["id"]] = {s.lower() for s in candidate_terms(r["original_name"] or "", remove)}
            if tl in seg_cache[r["id"]]:
                return True
        return False

    proj_q, type_q = [], []
    for t in cands:
        tl = t.lower()
        if any(tl == e or tl in e or e in tl for e in existing if e):
            continue
        hits = [r for r in rows if tl in r["mt"]]
        if len(hits) < need or not any((r["method"] or "") == "人工" for r in hits):
            continue
        if all(r["project_id"] == f["project_id"] for r in hits):
            proj_q.append((len(hits), natural(t, hits), len(t), t, hits))
        elif f["doc_type"] != "OTH-DOC" and all(r["doc_type"] == f["doc_type"] for r in hits) \
                and len({r["project_id"] for r in hits}) >= 2:
            type_q.append((len(hits), natural(t, hits), len(t), t, hits))

    for queue, kind in ((proj_q, "project"), (type_q, "type")):
        if not queue:
            continue
        queue.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        _, _, _, t, hits = queue[0]
        if kind == "project":
            types = {r["doc_type"] for r in hits}
            dt = next(iter(types)) if len(types) == 1 else ""
            db.insert("rules", {"pattern": t, "project_id": f["project_id"], "doc_type": dt,
                                "kind": "project", "source": "auto", "created_at": now()})
            out["learned"].append({"pattern": t, "kind": "project", "project_id": f["project_id"], "doc_type": dt})
        else:
            db.insert("rules", {"pattern": t, "project_id": 0, "doc_type": f["doc_type"],
                                "kind": "type", "source": "auto", "created_at": now()})
            out["learned"].append({"pattern": t, "kind": "type", "doc_type": f["doc_type"]})
        existing.append(t.lower())
    return out


def _substrings(seg: str) -> Set[str]:
    out: Set[str] = set()
    n = len(seg)
    for i in range(n):
        for j in range(i + 2, min(n, i + 12) + 1):
            t = seg[i:j]
            # 英文单词不能截半：ERP门户 可以，RP门户 不行
            if t[0].isascii() and t[0].isalnum() and i > 0 and seg[i - 1].isascii() and seg[i - 1].isalnum():
                continue
            if t[-1].isascii() and t[-1].isalnum() and j < n and seg[j].isascii() and seg[j].isalnum():
                continue
            has_cjk = bool(re.search(r"[一-鿿]", t))
            if len(t) < (2 if has_cjk else 3) or t.lower() in STOPWORDS or t in STOPWORDS:
                continue
            if not re.search(r"[A-Za-z一-鿿]", t) or re.fullmatch(r"[一-鿿]", t):
                continue
            out.add(t)
    return out
