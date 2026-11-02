"""分拣流水线：去重 → 抽取 → 关键词快判 → Jev 判断 + DeepSeek 分析 → 置信度分流 → 重命名归档。"""
from __future__ import annotations

import difflib
import hashlib
import os
import queue
import re
import shutil
import stat
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import ai, archives, config, extract, learning, naming
from . import projects as P
from . import standards as S
from .db import DB, loads, now


@dataclass
class Task:
    path: str
    source: str = "收件箱"
    preset_project_id: Optional[int] = None
    batch_id: Optional[str] = None
    batch_label: str = ""
    rerun_job_id: Optional[int] = None
    origin: str = ""                 # 来自微信等来源的复制件：原文件路径（原文件不动）
    keep_unmatched: bool = True      # False：认不出项目就忽略（只删复制件），不进「未匹配」
    depth: int = 0                   # 压缩包嵌套层数
    force_unpack: bool = False


@dataclass
class Signal:
    project_id: Optional[int] = None
    conf: float = 0.0
    reason: str = ""
    customer_id: Optional[int] = None
    locked: bool = False
    candidates: List[int] = field(default_factory=list)
    rule_type: str = ""
    rule_source: str = ""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


ANALYZE_TIMEOUT = 300      # 单个文件识别最多等 5 分钟，超时就交给人处理，不堵住后面的文件


def make_writable(path: Path) -> None:
    """去掉只读属性。Windows 版微信（3.9 起）收到的文件都是只读的，复制过来也带着只读，
    不去掉的话临时副本删不掉、归档后的文件也改不了。"""
    try:
        mode = os.stat(path).st_mode
        if not mode & stat.S_IWUSR:
            os.chmod(path, mode | stat.S_IWUSR | stat.S_IREAD)
    except OSError:
        pass


def remove_file(path: Path, tries: int = 6) -> bool:
    """删除临时副本：只读的先去掉只读；被杀毒软件等短暂占用时稍等重试。删不掉也不抛异常。"""
    for i in range(tries):
        try:
            path.unlink(missing_ok=True)
            return True
        except PermissionError:
            make_writable(path)
        except OSError:
            pass
        time.sleep(0.3 * (i + 1))
    print("临时文件删不掉，先留着：", path)
    return False


def should_ignore(path: Path) -> bool:
    name = path.name
    if name.startswith(".") or name.startswith("~$") or name in ("Thumbs.db", "desktop.ini", "Icon\r"):
        return True
    return path.suffix.lower() in S.IGNORE_SUFFIX


def norm(s: str) -> str:
    return re.sub(r"[\s_\-—()（）【】\[\]·.]", "", s or "").lower()


GENERIC_BIZ = {"其他", "其它", "服务", "项目", "综合", "专项", "框架", "协议"}


def biz_keywords(biz: str) -> List[str]:
    """把 CRM 里的业务线（如「渗透测试」「安测软测、渗透测试」「漏洞扫描」）展开成识别关键词。"""
    biz = biz or ""
    out = [t for t in re.split(r"[、,，/;；\s\-]+", biz) if len(t) >= 2 and t not in GENERIC_BIZ]
    for key, kws in S.BIZ_LINES.items():
        if biz_matches(biz, key):
            out += [key] + kws
    return list(dict.fromkeys(out))


def biz_matches(biz: str, key: str) -> bool:
    if not biz or not key:
        return False
    if key in biz:
        return True
    return any(len(k) >= 2 and k in biz for k in S.BIZ_LINES.get(key, []))


class Pipeline:
    def __init__(self, db: DB):
        self.db = db
        self.q: "queue.Queue[Task]" = queue.Queue()
        self.inflight: set = set()
        self.batch_projects: Dict[str, Tuple[int, float]] = {}
        self.lock = threading.RLock()
        self.busy = False
        self.current_job: Optional[int] = None
        self.recovered: Dict[int, int] = {}
        self.processed = 0
        self.history = learning.History(db)
        self.thread = threading.Thread(target=self._loop, name="pipeline", daemon=True)
        self.thread.start()

    # ------------------------------------------------------------ 队列
    def submit(self, task: Task) -> bool:
        key = os.path.abspath(task.path)
        with self.lock:
            if key in self.inflight and task.rerun_job_id is None:
                return False
            self.inflight.add(key)
        self.q.put(task)
        return True

    def queue_size(self) -> int:
        return self.q.qsize() + (1 if self.busy else 0)

    def _loop(self) -> None:
        while True:
            task = self.q.get()
            self.busy = True
            self.current_job = task.rerun_job_id
            try:
                self.process(task)
            except Exception as e:
                traceback.print_exc()
                self._fail_current(e)
            finally:
                self.busy = False
                self.current_job = None
                with self.lock:
                    self.inflight.discard(os.path.abspath(task.path))
                self.processed += 1
            if self.q.empty():
                try:      # 队列空了还有「识别中」的，说明哪里漏了：重新排队或如实标出来
                    self.recover_jobs()
                except Exception:
                    traceback.print_exc()

    def _fail_current(self, e: Exception) -> None:
        """处理中途出了没预料到的错：这一条标成「出错」，不能一直停在「识别中」。"""
        jid = self.current_job
        if not jid:
            return
        try:
            j = self.db.one("SELECT status FROM jobs WHERE id=?", (jid,))
            if j and j["status"] == "processing":
                self.db.update("jobs", jid, {"status": "error", "error": f"处理出错：{e}"[:500], "decided_at": now()})
        except Exception:
            traceback.print_exc()

    def recover_jobs(self) -> int:
        """停在「识别中」却没有在处理的记录（上次退出时正在处理的、处理中途出意外的）重新排队；
        临时文件不在了就如实标出来。启动时和队列空闲时各查一次。"""
        n = 0
        for j in self.db.q("SELECT * FROM jobs WHERE status='processing' ORDER BY id"):
            staged = Path(j["staged_path"]) if j.get("staged_path") else None
            orig = j.get("original_path") or ""
            origin = orig if orig and orig != j.get("staged_path") else ""
            tries = self.recovered.get(j["id"], 0)
            if staged and staged.is_file() and tries >= 2:
                self.db.update("jobs", j["id"], {"status": "error", "decided_at": now(),
                                                 "error": "重试两次仍没有处理完，请手动指定项目或「重新识别」"})
            elif staged and staged.is_file():
                self.recovered[j["id"]] = tries + 1
                keep = (not origin) or "拿来归档" in staged.parts or config.get("source_unmatched") == "keep"
                n += self.submit(Task(path=str(staged), source=j.get("source") or "恢复", origin=origin,
                                      batch_id=j.get("batch_id") or None, rerun_job_id=j["id"], keep_unmatched=keep))
            elif origin and Path(origin).is_file():
                self.db.update("jobs", j["id"], {"status": "ignored", "staged_path": "", "decided_at": now(),
                                                 "result": {"ignored_reason": "处理中断"}})
            else:
                self.db.update("jobs", j["id"], {"status": "error", "decided_at": now(),
                                                 "error": "处理中断，临时文件已经不在了；需要的话把原文件重新放进收件箱"})
        return n

    def fix_readonly_archive(self) -> int:
        """以前从微信归档进来的文件可能还是只读的（打开后不能保存），顺手去掉只读。"""
        n = 0
        for r in self.db.q("SELECT archive_path FROM files WHERE state IN ('archived','superseded')"):
            fp = r.get("archive_path")
            try:
                if fp and os.path.isfile(fp) and not os.stat(fp).st_mode & stat.S_IWUSR:
                    make_writable(Path(fp))
                    n += 1
            except OSError:
                continue
        return n

    def _analyze_limited(self, src: Path, task: Task, job_id: int) -> Dict:
        ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analyze")
        fut = ex.submit(self.analyze, src, task, job_id)
        try:
            return fut.result(timeout=ANALYZE_TIMEOUT)
        except FutureTimeout:
            span = f"{ANALYZE_TIMEOUT // 60} 分钟" if ANALYZE_TIMEOUT >= 60 else f"{ANALYZE_TIMEOUT} 秒"
            raise TimeoutError(f"识别超过 {span}还没完成，已跳过，请手动指定项目") from None
        finally:
            ex.shutdown(wait=False)

    # ------------------------------------------------------------ 主流程
    def process(self, task: Task) -> Optional[int]:
        src = Path(task.path)
        if not src.exists() or not src.is_file():
            return None
        make_writable(src)
        size = src.stat().st_size
        sha = sha256_of(src)
        if task.rerun_job_id:
            job_id = task.rerun_job_id
            self.db.update("jobs", job_id, {"status": "processing", "error": ""})
        else:
            job_id = self.db.insert("jobs", {
                "original_name": src.name, "original_path": task.origin or str(src), "staged_path": str(src),
                "source": task.source, "batch_id": task.batch_id or "", "sha256": sha, "size": size,
                "status": "processing", "created_at": now()})
            self.current_job = job_id
            dup = self.db.one("SELECT * FROM files WHERE sha256=? AND state IN ('archived','superseded') "
                              "ORDER BY id DESC LIMIT 1", (sha,))
            pend = None if dup else self.db.one(
                "SELECT * FROM jobs WHERE sha256=? AND status IN ('pending_review','unmatched','unpacked') AND id!=? "
                "ORDER BY id DESC LIMIT 1", (sha, job_id))
            if (dup or pend) and task.origin:
                # 微信等来源的复制件：已经归档过（或正在处理）就丢掉副本，原文件还在原处
                self.db.update("jobs", job_id, {"status": "skipped", "staged_path": "", "decided_at": now(),
                                                "result": {"dropped": True, "existing_name": (dup or pend).get(
                                                    "archive_name") or (pend or {}).get("original_name", "")}})
                remove_file(src)
                self._cleanup_inbox_dir(src.parent)
                return job_id
            if dup or pend:
                dst = naming.unique_path(config.duplicate_dir() / src.name)
                self._move(job_id, src, dst, "duplicate")
                result = ({"duplicate_of": dup["id"], "existing_path": dup["archive_path"],
                           "existing_name": dup["archive_name"]} if dup else
                          {"duplicate_of_job": pend["id"], "existing_path": pend["staged_path"],
                           "existing_name": pend["original_name"] + (
                               "（已解压过）" if pend["status"] == "unpacked" else "（待复核中）")})
                self.db.update("jobs", job_id, {"status": "duplicate", "staged_path": str(dst),
                                                "decided_at": now(), "result": result})
                self._cleanup_inbox_dir(src.parent)
                return job_id
        arch: Dict = {}
        if archives.kind_of(src) and config.get("unpack_enabled") and task.depth < 3:
            arch = self._try_unpack(task, src, job_id)
            if arch.get("done"):
                return job_id
        try:
            sug = self._analyze_limited(src, task, job_id)
        except Exception as e:
            traceback.print_exc()
            sug = {"error": str(e) or e.__class__.__name__, "confidence": 0}
        auto = float(config.get("auto_threshold"))
        review = float(config.get("review_threshold"))
        if arch:
            sug["archive"] = arch
            sug.setdefault("evidence", []).insert(0, arch["reason"])
            if arch["status"] in ("password", "error"):     # 让人看一眼：输入密码或决定整包归档
                sug["confidence"] = min(float(sug.get("confidence") or 0), round(auto - 0.01, 2))
        conf = float(sug.get("confidence") or 0)
        self.db.update("jobs", job_id, {"suggestion": sug, "confidence": conf, "method": sug.get("method", "")})
        pconf = float(sug.get("project_conf") or 0)
        if task.origin and not task.keep_unmatched and not arch and not sug.get("error") \
                and not (sug.get("project_id") and pconf >= review):
            # 来源（微信等）里认不出项目的文件：多半是私人文件，忽略；原文件还在原处，记录里可以「拿来归档」
            self.db.update("jobs", job_id, {"status": "ignored", "staged_path": "", "decided_at": now(),
                                            "result": {"ignored_reason": "认不出属于哪个项目"}})
            remove_file(src)
            self._cleanup_inbox_dir(src.parent)
            return job_id
        try:
            if sug.get("project_id") and sug.get("doc_type") and conf >= auto:
                self.archive(job_id, src, sug, sug.get("method", "关键词"))
            else:
                # 项目有把握、只是类型或其他字段拿不准 → 待复核；项目都没找到 → 未匹配
                target_dir = config.review_dir() if (sug.get("project_id") and pconf >= review) else config.unmatched_dir()
                status = "pending_review" if target_dir == config.review_dir() else "unmatched"
                dst = src if src.parent == target_dir else naming.unique_path(target_dir / src.name)
                if dst != src:
                    self._move(job_id, src, dst, "stage")
                upd = {"status": status, "staged_path": str(dst)}
                if sug.get("error"):
                    upd.update({"status": "error", "error": str(sug["error"])[:500]})
                self.db.update("jobs", job_id, upd)
        except Exception as e:
            traceback.print_exc()
            self.db.update("jobs", job_id, {"status": "error", "error": str(e)[:500]})
        self._cleanup_inbox_dir(src.parent)
        return job_id

    # ------------------------------------------------------------ 压缩包
    def _try_unpack(self, task: Task, src: Path, job_id: int, password: str = "") -> Dict:
        """能解就解：解出的文件作为同一批次逐个识别，原包移到 _原始压缩包。
        返回 {"done": True} 表示已处理完；否则返回压缩包情况，交给后面按普通文件处理。"""
        dest = naming.unique_path(config.inbox() / ".解压" / naming.safe_dir_name(archives.stem_of(src)))
        pws = ([password] if password else []) + [p for p in (config.get("archive_passwords") or []) if p != password]
        r = archives.unpack(src, dest, pws, int(config.get("unpack_max_files") or 30), force=task.force_unpack)
        if r.status != "ok":
            reason = {"password": "压缩包有密码：输入密码后自动解压，或直接整包归档",
                      "error": f"压缩包没能解开：{r.reason}"}.get(r.status, r.reason)
            return {"status": r.status, "kind": r.kind, "count": r.count, "reason": reason,
                    "can_unpack": r.status == "password" or (r.status == "whole" and r.count > 0)}
        if not r.files:
            return {"status": "whole", "kind": r.kind, "count": 0, "reason": "压缩包是空的"}
        label = archives.stem_of(src)
        source = task.source if task.source.endswith("压缩包") else f"{task.source}·压缩包"
        for f in r.files:
            self.submit(Task(path=str(f), source=source, preset_project_id=task.preset_project_id,
                             batch_id=f"zip:{job_id}", batch_label=label, origin=task.origin,
                             keep_unmatched=task.keep_unmatched, depth=task.depth + 1))
        kept = ""
        if config.get("keep_archives"):
            dst = naming.unique_path(config.root() / config.ARCHIVE_KEEP_NAME / date.today().strftime("%Y-%m") / src.name)
            self._move(job_id, src, dst, "unpack")
            kept = str(dst)
        else:
            src.unlink(missing_ok=True)
        self.db.update("jobs", job_id, {
            "status": "unpacked", "staged_path": kept, "decided_at": now(), "method": "解压",
            "result": {"count": len(r.files), "kept": kept, "password_used": bool(r.password),
                       "names": [str(f.relative_to(dest)) for f in r.files[:40]]}})
        self._cleanup_inbox_dir(src.parent)
        return {"done": True}

    def unpack_job(self, job_id: int, password: str = "", remember: bool = False) -> int:
        """待复核卡片上「解压后逐个归档」/ 输入密码解压。"""
        job = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] not in ("pending_review", "unmatched", "error"):
            raise ValueError("只有待处理的压缩包可以解压")
        src = self.locate(job)
        if src is None:
            raise ValueError("找不到这个压缩包")
        res = self._try_unpack(Task(path=str(src), source=job["source"], force_unpack=True), src, job_id, password)
        if not res.get("done"):
            if res["status"] == "password":
                raise ValueError("密码不对" if password else "压缩包有密码，请输入密码")
            raise ValueError(res["reason"])
        if remember and password:
            pws = list(config.get("archive_passwords") or [])
            if password not in pws:
                config.update({"archive_passwords": (pws + [password])[-20:]})
        return (loads(self.db.one("SELECT result FROM jobs WHERE id=?", (job_id,))["result"], {}) or {}).get("count", 0)

    def recover_staging(self) -> int:
        """上次退出时还没处理完的临时文件（解压出来的、从微信复制来的、网页上传的）重新排队。"""
        n = 0
        for name in (".解压", ".来源", ".发送", ".uploading"):
            d = config.inbox() / name
            if not d.exists():
                continue
            for p in sorted(d.rglob("*")):
                if p.is_file() and not should_ignore(p):
                    batch = p.relative_to(d).parts[0] if len(p.relative_to(d).parts) > 1 else ""
                    n += self.submit(Task(path=str(p), source="恢复", batch_id=f"recover:{name}:{batch}" if batch else None,
                                          batch_label=batch if name in (".解压",) else ""))
        return n

    # ------------------------------------------------------------ 识别
    def analyze(self, src: Path, task: Task, job_id: int) -> Dict:
        info = extract.extract(src, ocr_enabled=bool(config.get("ocr_enabled")),
                               pdf_pages=int(config.get("ocr_pdf_pages") or 2))
        text = info["text"]
        projects = P.candidate_projects(self.db)
        pmap = {p["id"]: p for p in projects}
        if task.preset_project_id and task.preset_project_id not in pmap:
            p = P.get_project(self.db, task.preset_project_id)
            if p:
                projects.append(p)
                pmap[p["id"]] = p
        folder = self._folder_hint(src, task)
        hay_name = f"{src.name} {folder}"
        # 写明了项目编号的，结项很久的项目也要认（结项后才补回来的验收单、签字版很常见）
        hay_no = f"{hay_name} {text[:3000]}"
        for p in P.list_projects(self.db):
            if p["id"] not in pmap and p["project_no"] and p["project_no"] in hay_no:
                projects.append(p)
                pmap[p["id"]] = p
        evidence: List[str] = []
        errors: List[str] = []
        is_pic = src.suffix.lower() in S.IMAGE_EXT
        if info.get("ocr"):
            where = f"扫描件前 {info.get('ocr_pages', 1)} 页" if not is_pic else "图中"
            evidence.append(f"识别了{where}文字（{extract.meaningful_len(text)} 字，{info.get('ocr_ms', 0) / 1000:.1f} 秒）"
                            if text.strip() else f"{where}没有识别到文字")
        elif info.get("ocr_error"):
            errors.append(f"图片文字识别失败：{info['ocr_error']}")
        elif info.get("ocr_skip") and (is_pic or src.suffix.lower() == ".pdf"):
            evidence.append(f"只按文件名判断（{info['ocr_skip']}）")

        type_code, type_conf, type_rank, type_by = self._keyword_type(src, text, evidence, info)
        sig = self._keyword_project(hay_name, text, projects, task, evidence, type_code)
        status_kw = self._keyword_status(src.name, text)
        # 拍照/扫描的授权书、验收单、合同等，默认就是签字盖章版
        if info.get("ocr") and text and not self._status_explicit(src.name) \
                and not S.TYPE_MAP.get(type_code, {}).get("evidence") \
                and (type_code in S.SIGNED_TYPES or re.search(r"盖\s*章|签\s*字|签\s*章", text)):
            status_kw = "签字"
        # 学习到的类型规则
        t0 = (type_code, type_conf)
        type_code, type_conf = self._apply_rule_types(hay_name, sig, type_code, type_conf, evidence)
        type_by = self._by_change(type_by, t0, (type_code, type_conf), "规则")
        # 参考历史归档：相似文件沿用上次的项目和类型
        if config.get("history_enabled"):
            try:
                hist = self.history.suggest(src.name, folder, text, set(pmap))
            except Exception:
                traceback.print_exc()
                hist = None
            if hist:
                t0 = (type_code, type_conf)
                type_code, type_conf = self._merge_history(hist, sig, type_code, type_conf, pmap, evidence)
                type_by = self._by_change(type_by, t0, (type_code, type_conf), "历史归档")

        auto = float(config.get("auto_threshold"))
        use_jev = bool(config.get("jev_enabled") and config.get("jev_api_key")) and (
            sig.conf < auto or type_conf < auto)
        is_evidence = S.TYPE_MAP.get(type_code, {}).get("evidence") and type_conf >= 0.85
        use_ds = bool(config.get("deepseek_enabled") and config.get("deepseek_api_key")) and not is_evidence \
            and (text or not naming.is_garbage_title(src.stem))
        # DeepSeek 也判断：关键词（含规则、历史）拿不准的那一项才问；给它全部候选项目，让它独立判断
        ds_judge = use_ds and config.get("deepseek_judge") is not False
        ask_p = bool(ds_judge and not sig.locked and sig.conf < auto and projects)
        ask_t = bool(ds_judge and type_conf < auto)
        limit = int(config.get("text_chars_for_ai") or 1500)
        snippet = text[:limit]

        jev_candidates = projects
        if sig.customer_id and not sig.locked:
            same = [p for p in projects if p["customer_id"] == sig.customer_id]
            if same:
                jev_candidates = same
        cust_short = pmap[sig.project_id]["customer_short"] if sig.project_id in pmap else ""

        jev_res: Dict = {}
        ds_res: Dict = {}
        with ThreadPoolExecutor(max_workers=2) as ex:
            fj = ex.submit(ai.jev_classify, src.name, folder, snippet, jev_candidates, not sig.locked) if use_jev else None
            if ask_p or ask_t:
                fd = ex.submit(ai.deepseek_analyze, src.name, snippet, "", "", 40,
                               projects if ask_p else None, ask_t, folder)
            else:
                fd = ex.submit(ai.deepseek_analyze, src.name, snippet, cust_short,
                               S.TYPE_MAP.get(type_code, {}).get("name", "")) if use_ds else None
            if fj:
                try:
                    answers, body, resp, ms = fj.result()
                    jev_res = answers
                    self._log_ai(job_id, "jev", body, resp, ms, True)
                except Exception as e:
                    errors.append(f"Jev：{e}")
                    self._log_ai(job_id, "jev", {}, {"error": str(e)}, 0, False)
            if fd:
                try:
                    result, body, resp, ms = fd.result()
                    ds_res = result
                    self._log_ai(job_id, "deepseek", body, {"result": result}, ms, True)
                except Exception as e:
                    errors.append(f"DeepSeek：{e}")
                    self._log_ai(job_id, "deepseek", {}, {"error": str(e)}, 0, False)

        method = "关键词"
        cand_probs: Dict[int, float] = {}
        # ---- 合并项目判断
        if jev_res.get("project"):
            choice, p, ranked = ai.choice_top(jev_res["project"])
            by_no = {x["project_no"]: x["id"] for x in projects}
            for k, v in ranked[:5]:
                if k in by_no:
                    cand_probs[by_no[k]] = v
            jid = by_no.get(choice) if choice and choice != "none" else None
            if jid:
                method = "Jev"
                if sig.project_id == jid:
                    sig.conf = min(0.99, max(sig.conf, p, 0.93))
                    sig.reason += " + Jev 印证"
                    evidence.append(f"Jev 与关键词结论一致（{p:.0%}）")
                elif sig.project_id:
                    evidence.append(f"Jev 判断为 {pmap[jid]['label']}（{p:.0%}），与关键词结论不一致")
                    if p > sig.conf:
                        sig.project_id = jid
                    sig.conf = min(0.75, max(sig.conf, p))
                    sig.reason = "Jev 与关键词不一致"
                else:
                    sig.project_id = jid
                    sig.conf = round(p * 0.97, 3)
                    sig.reason = "Jev"
                    evidence.append(f"Jev 判断项目：{pmap[jid]['label']}（{p:.0%}）")
            elif choice == "none":
                evidence.append(f"Jev 认为不属于任何候选项目（{p:.0%}）")
        # ---- 合并类型判断
        if jev_res.get("doc_type"):
            t, p, ranked = ai.choice_top(jev_res["doc_type"])
            if t in S.TYPE_MAP:
                method = "Jev"
                if t == type_code:
                    type_conf = min(0.99, max(type_conf, p, 0.93))
                    type_by = (type_by + " + Jev 印证") if type_by else "Jev"
                elif type_conf < 0.3:
                    type_code, type_conf = t, round(p * 0.97, 3)
                    type_by = "Jev"
                    evidence.append(f"Jev 判断类型：{S.TYPE_MAP[t]['name']}（{p:.0%}）")
                else:
                    evidence.append(f"Jev 判断类型为 {S.TYPE_MAP[t]['name']}，与关键词不一致")
                    if p > type_conf:
                        type_code = t
                    type_conf = min(0.75, max(type_conf, p))
                    type_by = "Jev 与关键词不一致"
                type_rank = [(k, v) for k, v in ranked[:4]]
        # ---- DeepSeek 的判断
        ds_used = False
        if ask_p and ds_res.get("project"):
            ds_used = self._merge_ds_project(ds_res, sig, projects, pmap, hay_name, text, evidence, cand_probs)
        if ask_t and ds_res.get("doc_type"):
            type_code, type_conf, type_by, type_rank, used = self._merge_ds_type(
                ds_res, type_code, type_conf, type_by, type_rank, evidence)
            ds_used = ds_used or used
        if ds_used:
            # 项目是 DeepSeek 单独认出来的记作「DeepSeek」，其余是在关键词或 Jev 的基础上帮了忙
            method = "DeepSeek" if method == "关键词" and sig.reason.startswith("DeepSeek") else f"{method}+DeepSeek"
        status = status_kw
        if jev_res.get("status"):
            st, p, _ = ai.choice_top(jev_res["status"])
            if st in S.STATUSES and p >= 0.6 and not self._status_explicit(src.name):
                status = st
        sensitivity = "高" if type_code in S.SENSITIVE_TYPES else "一般"
        if jev_res.get("sensitive", {}).get("type") == "noul" and float(jev_res["sensitive"].get("noul", 0)) >= 0.5:
            sensitivity = "高"

        # ---- 标题与日期
        proj = pmap.get(sig.project_id) if sig.project_id else None
        cust_short = proj["customer_short"] if proj else ""
        tname = S.TYPE_MAP.get(type_code, {}).get("name", "")
        title_src = "文件名"
        if S.TYPE_MAP.get(type_code, {}).get("evidence"):
            raw_title, title_src = src.stem, "原文件名（证据保留原名）"
        elif ds_res.get("title"):
            raw_title, title_src = ds_res["title"], "DeepSeek"
        elif not naming.is_garbage_title(src.stem):
            raw_title = src.stem
            # 文件名里只剩个笼统的叫法（「最终版(2)-评估报告-改」→「评估报告」），正文标题更具体时用正文标题
            cover = info.get("cover_title") or ""
            if cover and not naming.is_garbage_title(cover):
                core_f, core_c = naming.clean_title(src.stem), naming.clean_title(cover)
                if len(core_c) > len(core_f) >= 2 and core_f in core_c:
                    raw_title, title_src = cover, ("图中文字" if info.get("ocr") else "封面")
        elif info.get("cover_title"):
            raw_title, title_src = info["cover_title"], ("图中文字" if info.get("ocr") else "封面")
        elif info.get("meta_title") and not naming.is_garbage_title(info["meta_title"]):
            raw_title, title_src = info["meta_title"], "文档属性"
        else:
            raw_title, title_src = tname, "模板"
        title = naming.clean_title(raw_title, cust_short, tname,
                                   proj.get("aliases") if proj else None, proj.get("customer_full", "") if proj else "")
        doc_date = ds_res.get("doc_date") or extract.pick_doc_date(src.name, text) or date.today().isoformat()

        candidates = []
        ids = list(dict.fromkeys(([sig.project_id] if sig.project_id else []) + list(cand_probs) + sig.candidates))
        for pid in ids[:6]:
            if pid in pmap:
                candidates.append({"id": pid, "label": pmap[pid]["label"], "project_no": pmap[pid]["project_no"],
                                   "p": round(cand_probs.get(pid, 0), 3)})
        conf = round(min(sig.conf, type_conf), 3) if sig.project_id else 0.0
        return {
            "project_id": sig.project_id, "project_conf": round(sig.conf, 3),
            "project_by": sig.reason if sig.project_id else "",
            "doc_type": type_code, "type_conf": round(type_conf, 3), "type_by": type_by,
            "type_candidates": [{"code": k, "name": S.TYPE_MAP[k]["name"], "p": round(v, 3)}
                                for k, v in type_rank if k in S.TYPE_MAP][:4],
            "candidates": candidates, "title": title, "title_source": title_src,
            "status": status, "doc_date": doc_date, "summary": ds_res.get("summary", ""),
            "sensitivity": sensitivity, "confidence": conf, "method": method,
            "evidence": evidence[:10], "errors": errors, "snippet": text[:400],
            "batch_label": task.batch_label, "ocr": bool(info.get("ocr") and text.strip()),
        }

    # ------------------------------------------------------------ DeepSeek 判断的合并
    GENERIC_WORDS = ("股份有限公司", "有限责任公司", "有限公司", "集团", "股份", "公司", "科技", "信息", "技术", "网络",
                     "中国", "上海", "北京", "深圳", "广州", "杭州", "南京", "苏州", "天津", "重庆", "co.", "ltd", "inc")

    def _ds_evidence_ok(self, ev: str, proj: Dict, hay_name: str, text: str) -> bool:
        """DeepSeek 给的原文依据：确实出现在文件名/正文里，而且说的就是这个客户（如「青岚集团」对应「青岚医疗」）。"""
        ev = re.sub(r"\s+", "", ev or "").lower()
        if len(ev) < 2 or ev not in re.sub(r"\s+", "", f"{hay_name}{text}").lower():
            return False
        for nm in {proj.get("customer_short") or "", proj.get("customer_full") or "", *(proj.get("aliases") or [])}:
            core = nm.lower()
            for g in self.GENERIC_WORDS:
                core = core.replace(g, "")
            core = re.sub(r"[\s()（）·\-_.]", "", core)
            if len(core) < 2:
                continue
            key = core[:4] if core.isascii() else core[:2]
            if len(key) >= 2 and key in ev:
                return True
        return False

    def _merge_ds_project(self, ds: Dict, sig: Signal, projects: List[Dict], pmap: Dict[int, Dict], hay_name: str,
                          text: str, evidence: List[str], cand_probs: Dict[int, float]) -> bool:
        """把 DeepSeek 的项目判断并进来，返回它是否起了作用。
        一致 → 92%；认出客户但分不清项目时由它挑 → 90%；单独认出且原文依据对得上 → 90%，否则最多 80%；
        和现有结论不一致 → 压到 75% 请人确认。之前已经有分歧（Jev 与关键词不一致）的，不会因为它而自动归档。"""
        no, dp, ev = ds.get("project"), float(ds.get("project_p") or 0), ds.get("project_evidence") or ""
        by_no = {x["project_no"]: x["id"] for x in projects}
        did = by_no.get(no) if no and no != "none" else None
        if not did:
            if no == "none" and dp >= 0.7 and sig.project_id:
                evidence.append("DeepSeek 认为不属于任何候选项目")
            return False
        cand_probs.setdefault(did, dp)
        label = pmap[did]["label"]
        disputed = "不一致" in (sig.reason or "")
        if sig.project_id == did:
            if dp < 0.8:
                return False
            sig.conf = min(0.97, max(sig.conf, 0.85 if disputed else 0.92))
            sig.reason = re.sub(r"，(项目待确认|分不清是哪个项目)$", "", sig.reason or "") + " + DeepSeek 印证"
            evidence.append(f"DeepSeek 与结论一致（{dp:.0%}）")
            return True
        same_cust = sig.project_id and pmap[sig.project_id]["customer_id"] == pmap[did]["customer_id"]
        if same_cust and sig.conf <= 0.8 and not disputed:
            # 认出了客户，但分不清是这个客户的哪个项目：让 DeepSeek 按正文内容挑
            sig.project_id = did
            sig.conf = 0.9 if dp >= 0.85 else max(sig.conf, round(min(dp, 0.8), 3))
            base = re.sub(r"，.*$", "", sig.reason or "客户名").replace("（与历史不一致）", "")
            sig.reason = base + " + DeepSeek 区分项目"
            evidence.append(f"同一客户有多个项目，DeepSeek 按内容判断为 {label}（{dp:.0%}）")
            return True
        if sig.project_id:
            evidence.append(f"DeepSeek 判断为 {label}（{dp:.0%}），与现有结论不一致，请确认")
            sig.conf = min(sig.conf, 0.75)
            sig.reason += "（DeepSeek 不一致）"
            if did not in sig.candidates:
                sig.candidates.insert(0, did)
            return True
        ok = self._ds_evidence_ok(ev, pmap[did], hay_name, text)
        sig.project_id, sig.customer_id = did, pmap[did]["customer_id"]
        sig.conf = 0.9 if (dp >= 0.85 and ok) else round(min(dp, 0.8), 3)
        sig.reason = f"DeepSeek（依据「{ev}」）" if ok else "DeepSeek"
        evidence.append(f"DeepSeek 判断项目：{label}（{dp:.0%}）" +
                        (f"，依据「{ev}」" if ok else "，文件里找不到明确的客户依据，请确认"))
        return True

    def _merge_ds_type(self, ds: Dict, type_code: str, type_conf: float, type_by: str,
                       type_rank: List[Tuple[str, float]], evidence: List[str]):
        t, tp = ds.get("doc_type"), float(ds.get("type_p") or 0)
        if t not in S.TYPE_MAP:
            return type_code, type_conf, type_by, type_rank, False
        if t not in [k for k, _ in type_rank]:
            type_rank = (type_rank + [(t, round(tp, 3))])[:4]
        name = S.TYPE_MAP[t]["name"]
        if t == type_code:
            if tp < 0.8:
                return type_code, type_conf, type_by, type_rank, False
            target = 0.85 if "不一致" in type_by else 0.92
            return (type_code, min(0.97, max(type_conf, target)), (type_by + " + DeepSeek 印证") if type_by else "DeepSeek",
                    type_rank, True)
        if type_conf < 0.5:
            evidence.append(f"DeepSeek 判断类型：{name}（{tp:.0%}）")
            rank = [(t, round(tp, 3))] + [(k, v) for k, v in type_rank if k != t][:3]
            return t, (0.9 if tp >= 0.9 else round(min(tp, 0.8), 3)), "DeepSeek", rank, True
        rank = [(t, round(tp, 3))] + [(k, v) for k, v in type_rank if k != t][:3]
        if type_by.startswith("正文关键词") and "不一致" not in type_by and type_conf <= 0.8:
            # 只是正文里零星出现了某类关键词，DeepSeek 读了内容另有判断：以 DeepSeek 为准
            old = S.TYPE_MAP.get(type_code, {}).get("name", type_code)
            evidence.append(f"正文关键词像{old}，DeepSeek 读内容判断为{name}（{tp:.0%}）")
            if tp >= 0.9:
                return t, 0.9, "DeepSeek（读正文，覆盖正文关键词）", rank, True
            return t, round(min(tp, 0.75), 3), "DeepSeek（与正文关键词不一致）", rank, True
        evidence.append(f"DeepSeek 判断类型为 {name}（{tp:.0%}），与现有结论不一致，请确认")
        return type_code, min(type_conf, 0.75), type_by + "（DeepSeek 不一致）", type_rank, True

    @staticmethod
    def _by_change(by: str, before: Tuple[str, float], after: Tuple[str, float], what: str) -> str:
        """类型判断被规则 / 历史改动过：依据里记上一笔。"""
        if after == before:
            return by
        if after[0] != before[0] or not by:
            return what
        return f"{by} + {what[:2]}印证" if after[1] > before[1] else by

    def _folder_hint(self, src: Path, task: Task) -> str:
        try:
            rel = src.parent.relative_to(config.inbox())
            parts = [x for x in rel.parts if not x.startswith(".")]
            return "/".join(parts)
        except ValueError:
            return task.batch_label or ""

    def _keyword_project(self, hay_name: str, text: str, projects: List[Dict], task: Task,
                         evidence: List[str], type_guess: str = "") -> Signal:
        sig = Signal()
        pmap = {p["id"]: p for p in projects}
        if task.preset_project_id and task.preset_project_id in pmap:
            p = pmap[task.preset_project_id]
            evidence.append(f"上传时指定项目：{p['label']}")
            return Signal(p["id"], 1.0, "上传时指定", p["customer_id"], True)
        name_l = hay_name.lower()
        head = text[:3000]
        head_l = head.lower()
        # 1. 精确项目编号
        for p in projects:
            no = p["project_no"]
            if no.lower() in name_l or no in head:
                evidence.append(f"出现项目编号 {no}")
                return Signal(p["id"], 1.0, "项目编号", p["customer_id"], True)
        # 2. 规则（手动记住的 + 自动学习的），长的优先
        for r in self.db.q("SELECT * FROM rules WHERE enabled=1 AND COALESCE(kind,'project')='project' "
                           "ORDER BY LENGTH(pattern) DESC"):
            if r["pattern"] and r["pattern"].lower() in name_l and r["project_id"] in pmap:
                self.db.x("UPDATE rules SET hits=hits+1 WHERE id=?", (r["id"],))
                p = pmap[r["project_id"]]
                auto = r.get("source") == "auto"
                evidence.append(f"命中{'自动学习的' if auto else ''}规则「文件名包含 {r['pattern']}」")
                s = Signal(p["id"], 0.97, "自动学习的规则" if auto else "记住的规则", p["customer_id"], True)
                s.rule_type = r.get("doc_type") or ""
                s.rule_source = r.get("source") or "manual"
                return s
        # 3. 客户名称 / 别名
        scores: Dict[int, float] = {}
        in_name: Dict[int, bool] = {}
        customers: Dict[int, Dict] = {}
        for p in projects:
            customers.setdefault(p["customer_id"], p)
        for cid, p in customers.items():
            names = {p["customer_short"], p.get("customer_full") or "", *p.get("aliases", [])}
            s = 0.0
            for nm in names:
                if not nm or len(nm) < 2:
                    continue
                if nm.lower() in name_l:
                    s += 3 * len(nm)
                    in_name[cid] = True
                elif self._in_text(nm, head, head_l):
                    s += len(nm)
            if s:
                scores[cid] = s
        batch = self.batch_projects.get(task.batch_id or "")
        if not scores:
            if batch and batch[0] in pmap:
                p = pmap[batch[0]]
                evidence.append(f"同批次文件已归入 {p['label']}")
                return Signal(p["id"], 0.9, "同批次文件", p["customer_id"])
            return sig
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        cid, top = ranked[0]
        if len(ranked) > 1 and ranked[1][1] >= top * 0.8:
            evidence.append("文件中出现多个客户名称")
            sig.candidates = [p["id"] for p in projects if p["customer_id"] in (cid, ranked[1][0])]
            return sig
        sig.customer_id = cid
        cust = customers[cid]
        evidence.append(f"识别到客户：{cust['customer_short']}" + ("（文件名）" if in_name.get(cid) else "（正文）"))
        own = [p for p in projects if p["customer_id"] == cid]
        sig.candidates = [p["id"] for p in own]
        if batch and batch[0] in {p["id"] for p in own}:
            p = pmap[batch[0]]
            evidence.append(f"同批次文件已归入 {p['label']}")
            return Signal(p["id"], 0.92, "客户名 + 同批次文件", cid, False, sig.candidates)
        base = 0.95 if in_name.get(cid) else 0.84
        sig.reason = "客户名（文件名）" if in_name.get(cid) else "客户名（正文）"
        if len(own) == 1:
            sig.project_id, sig.conf = own[0]["id"], base
            evidence.append("该客户只有一个在建项目")
            return sig
        # 4. 同一客户多个项目：用项目简称、关键词、业务线区分
        pscore: Dict[int, float] = {}
        hint_biz = S.TYPE_BIZ_HINT.get(type_guess, "")
        for p in own:
            s = 0.0
            terms = [p["short_name"], *p.get("keywords", [])]
            terms += [t for t in re.split(r"[\d年\-]+", p["short_name"]) if len(t) >= 2]
            for t in set(terms):
                if t and len(t) >= 2:
                    if t.lower() in name_l:
                        s += 3 * len(t)
                    elif t in head:
                        s += len(t)
            for kw in biz_keywords(p.get("biz_line") or ""):
                if kw.lower() in name_l:
                    s += 2 * len(kw)
                elif kw in head:
                    s += 0.5 * len(kw)
            if hint_biz and biz_matches(p.get("biz_line") or "", hint_biz):
                s += 4
            if s:
                pscore[p["id"]] = s
        if pscore:
            pr = sorted(pscore.items(), key=lambda kv: kv[1], reverse=True)
            clear = pr[0][1] >= 4 and (len(pr) == 1 or pr[1][1] < pr[0][1] * 0.6)
            if clear:
                sig.project_id = pr[0][0]
                sig.conf = base - 0.02
                sig.reason += " + 项目简称"
                evidence.append(f"按项目简称/业务线区分为 {pmap[pr[0][0]]['label']}")
                return sig
            sig.project_id = pr[0][0]
            sig.conf = 0.7
            sig.reason += "，项目待确认"
            evidence.append(f"该客户有 {len(own)} 个在建项目，需确认")
            return sig
        sig.project_id = own[0]["id"]
        sig.conf = 0.65
        sig.reason += "，分不清是哪个项目"
        evidence.append(f"该客户有 {len(own)} 个在建项目，无法区分")
        return sig

    def _keyword_type(self, src: Path, text: str, evidence: List[str],
                      info: Optional[Dict] = None) -> Tuple[str, float, List[Tuple[str, float]], str]:
        ext = src.suffix.lower()
        info = info or {}
        if ext in S.IMAGE_EXT:
            doc = self._image_as_document(src, text, info, evidence)
            if doc:
                return (*doc, "文件名关键词" if evidence and evidence[-1].startswith("图片文件名") else "图片里的标题")
            evidence.append("图片文件，按截图证据处理")
            return "EVD-SHOT", 0.92, [("EVD-SHOT", 0.92)], "图片格式"
        if ext in S.SCAN_EXT:
            return "EVD-SCAN", 0.95, [("EVD-SCAN", 0.95)], "扫描结果格式"
        code, conf, rank, where = self._type_by_keywords(src.name, text[:1500])
        # 扫描件：标题行写明了是什么文件（如「项目验收确认单」），以标题为准，可信度和文件名命中相当
        if info.get("ocr") and where != "文件名":
            tcode, tline = self._title_type(text)
            if tcode:
                evidence.append(f"扫描件标题「{tline[:24]}」：{S.TYPE_MAP[tcode]['name']}")
                rank = [(tcode, 0.9)] + [(k, v) for k, v in rank if k != tcode][:3]
                return tcode, 0.9, rank, "扫描件标题"
        if code == "OTH-DOC":
            return "OTH-DOC", 0.0, [], ""
        evidence.append(f"类型关键词（{where}）：{S.TYPE_MAP[code]['name']}")
        return code, conf, rank, f"{where}关键词"

    def _title_type(self, text: str) -> Tuple[str, str]:
        """取前三行里第一行像标题的（不超过 40 字）判断文件类型；返回 (类型码, 标题行)。"""
        for line in [x.strip() for x in text.split("\n") if x.strip()][:3]:
            if len(line) > 40:
                continue
            code, _, _, _ = self._type_by_keywords("", line)
            if code != "OTH-DOC" and not S.TYPE_MAP[code].get("evidence"):
                return code, line
        return "", ""

    @staticmethod
    def _in_text(nm: str, text: str, text_l: str) -> bool:
        """客户名/别名是否出现在正文里。英文别名不区分大小写，按整词匹配（starbucks 能匹配 hcp.starbucks.com.cn）。"""
        if nm.isascii():
            return re.search(rf"(?<![a-z0-9]){re.escape(nm.lower())}(?![a-z0-9])", text_l) is not None
        return nm in text

    def _image_as_document(self, src: Path, text: str, info: Dict,
                           evidence: List[str]) -> Optional[Tuple[str, float, List[Tuple[str, float]]]]:
        """图片是「文件的照片/扫描件」（授权书、验收单拍照）还是「截图证据」？前者按文件类型归档。"""
        stem = src.stem.lower()
        if any(h in stem for h in S.SHOT_NAME_HINTS):
            return None
        code, conf, rank, _ = self._type_by_keywords(src.name, "")
        if code != "OTH-DOC" and not S.TYPE_MAP[code].get("evidence") and conf >= 0.85:
            evidence.append(f"图片文件名表明是{S.TYPE_MAP[code]['name']}，按文件照片/扫描件处理")
            return code, conf, rank
        if not text:
            return None
        code, tline = self._title_type(text)
        if not code:
            return None
        rank = [(code, 0.9)]
        doc = 3.0 + (1 if re.search(S.DOC_TEXT_PATTERN, text) else 0)
        shot = sum(1 for p in S.SHOT_TEXT_PATTERNS if re.search(p, text)) + (0.5 if src.suffix.lower() == ".png" else 0)
        w, h = (info.get("image_size") or [0, 0])[:2]
        if w and h:
            doc += 1 if h > w * 1.15 else 0          # 文件照片多是竖的
            shot += 1 if w > h * 1.15 else 0         # 屏幕截图多是横的
        if doc <= shot:
            return None
        evidence.append(f"图中标题「{tline[:24]}」，按{S.TYPE_MAP[code]['name']}的照片/扫描件处理")
        return code, 0.9, rank

    def _type_by_keywords(self, name: str, head: str) -> Tuple[str, float, List[Tuple[str, float]], str]:
        """按类型关键词打分：返回 (类型码, 把握, 排名, 命中位置)。"""
        name_l = name.lower()
        name_hits: List[Tuple[str, str]] = []
        text_hits: List[Tuple[str, str]] = []
        for t in S.TYPE_CODES:
            for kw in t["kw"]:
                if kw.lower() in name_l:
                    name_hits.append((t["code"], kw))
                elif kw in head:
                    text_hits.append((t["code"], kw))

        def suppress(hits: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
            # 「渗透测试」被另一类型的「渗透测试授权」包含时，只算更具体的那个
            return [(c, kw) for c, kw in hits
                    if not any(oc != c and kw != o and kw.lower() in o.lower() for oc, o in hits)]

        ns: Dict[str, float] = {}
        ts: Dict[str, float] = {}
        for c, kw in suppress(name_hits):
            ns[c] = ns.get(c, 0) + len(kw)
        for c, kw in suppress(text_hits):
            ts[c] = ts.get(c, 0) + len(kw)
        total = {c: 3 * ns.get(c, 0) + ts.get(c, 0) for c in set(ns) | set(ts)}
        if not total:
            return "OTH-DOC", 0.0, [], ""
        ranked = sorted(total.items(), key=lambda kv: kv[1], reverse=True)
        top_code, s1 = ranked[0]
        s2 = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = (s1 - s2) / s1
        if ns.get(top_code):
            rivals = [c for c in ns if c != top_code]
            if not rivals:
                conf = 0.95 if s1 >= 2 * s2 else 0.85        # 文件名只命中这一类
            else:
                conf = 0.6 + 0.35 * margin                    # 文件名里有多种类型词
        else:
            conf = min(0.8, 0.45 + 0.35 * margin)             # 只有正文命中：不单独自动归档
        whole = sum(v for _, v in ranked)
        rank = [(k, round(v / whole, 3)) for k, v in ranked[:4]]
        where = "文件名" if ns.get(top_code) else "正文"
        return top_code, round(min(conf, 0.97), 3), rank, where

    def _apply_rule_types(self, hay_name: str, sig: Signal, type_code: str, type_conf: float,
                          evidence: List[str]) -> Tuple[str, float]:
        if sig.rule_type in S.TYPE_MAP:
            strong = sig.rule_source == "auto"
            if sig.rule_type == type_code:
                return type_code, max(type_conf, 0.95)
            if type_conf < (0.9 if strong else 0.5):
                evidence.append(f"规则记住的类型：{S.TYPE_MAP[sig.rule_type]['name']}")
                return sig.rule_type, (0.93 if strong else 0.85)
            return type_code, type_conf
        name_l = hay_name.lower()
        for r in self.db.q("SELECT * FROM rules WHERE enabled=1 AND kind='type' ORDER BY LENGTH(pattern) DESC"):
            pat = (r["pattern"] or "").lower()
            if not pat or pat not in name_l or r["doc_type"] not in S.TYPE_MAP:
                continue
            if r["doc_type"] == type_code:
                self.db.x("UPDATE rules SET hits=hits+1 WHERE id=?", (r["id"],))
                return type_code, max(type_conf, 0.95)
            if type_conf < 0.9:
                self.db.x("UPDATE rules SET hits=hits+1 WHERE id=?", (r["id"],))
                evidence.append(f"命中自动学习的类型规则「{r['pattern']}」→ {S.TYPE_MAP[r['doc_type']]['name']}")
                return r["doc_type"], 0.93
            break
        return type_code, type_conf

    def _merge_history(self, hist: Dict, sig: Signal, type_code: str, type_conf: float,
                       pmap: Dict[int, Dict], evidence: List[str]) -> Tuple[str, float]:
        hp, hc = hist.get("project_id"), float(hist.get("project_conf") or 0)
        like = hist.get("project_like", "")
        if hp in pmap and not sig.locked:
            hcust = pmap[hp]["customer_id"]
            label = pmap[hp]["label"]
            if sig.project_id is None:
                if sig.customer_id in (None, hcust):
                    sig.project_id, sig.conf, sig.customer_id = hp, hc, hcust
                    sig.reason = "历史归档" if not sig.reason else sig.reason + " + 历史归档"
                    evidence.append(f"与已归档的「{like}」相似，沿用项目 {label}")
                else:
                    evidence.append(f"历史相似文件「{like}」属于 {label}，与识别到的客户不一致")
            elif sig.project_id == hp:
                sig.conf = min(0.97, max(sig.conf, hc) + 0.04)
                sig.reason += " + 历史印证"
                evidence.append(f"历史文件印证：与「{like}」同属该项目")
            else:
                same_cust = pmap[sig.project_id]["customer_id"] == hcust
                if same_cust and sig.conf <= 0.8:
                    sig.project_id, sig.conf = hp, max(hc, sig.conf)
                    sig.reason = "客户名 + 历史归档"
                    evidence.append(f"同一客户有多个项目，参考历史文件「{like}」选择 {label}")
                else:
                    evidence.append(f"历史相似文件「{like}」属于 {label}，与关键词结论不一致")
                    if hc > sig.conf + 0.1:
                        sig.project_id = hp
                    sig.conf = min(sig.conf, 0.78)
                    sig.reason += "（与历史不一致）"
            if hp not in sig.candidates:
                sig.candidates.append(hp)
        ht, htc = hist.get("doc_type"), float(hist.get("type_conf") or 0)
        if ht in S.TYPE_MAP:
            if ht == type_code:
                type_conf = min(0.97, max(type_conf, htc) + 0.04)
            elif type_conf < 0.5:
                type_code, type_conf = ht, htc
                evidence.append(f"参考历史文件「{hist.get('type_like', '')}」，类型为 {S.TYPE_MAP[ht]['name']}")
            elif htc > type_conf + 0.1:
                type_code, type_conf = ht, min(htc, 0.8)
                evidence.append(f"参考历史文件，类型更像 {S.TYPE_MAP[ht]['name']}")
        return type_code, type_conf

    def _status_explicit(self, name: str) -> bool:
        n = name.lower()
        return any(k.lower() in n for kws in S.STATUS_KEYWORDS.values() for k in kws)

    def _keyword_status(self, name: str, text: str) -> str:
        n = name.lower()
        for st in ("签字", "草稿", "送审", "内审", "正式"):
            if any(k.lower() in n for k in S.STATUS_KEYWORDS[st]):
                return st
        head = text[:300]
        for st in ("草稿", "送审"):
            if any(k in head for k in S.STATUS_KEYWORDS[st]):
                return st
        return "正式"

    # ------------------------------------------------------------ 归档
    def archive(self, job_id: int, src: Path, f: Dict, method: str) -> int:
        proj = P.get_project(self.db, int(f["project_id"]))
        if not proj:
            raise ValueError("项目不存在")
        tdef = S.TYPE_MAP.get(f["doc_type"]) or S.TYPE_MAP["OTH-DOC"]
        pdir = P.ensure_project_dirs(self.db, self.db.one("SELECT * FROM projects WHERE id=?", (proj["id"],)))
        status = f.get("status") if f.get("status") in S.STATUSES else "正式"
        doc_date = f.get("doc_date") or date.today().isoformat()
        title = naming.clean_title(f.get("title") or tdef["name"], proj["customer_short"], tdef["name"],
                                   proj.get("aliases"), proj.get("customer_full", ""))
        doc_id = None
        version = None
        created_doc = False
        prev_version = None
        if tdef.get("evidence"):
            label = naming.safe_dir_name(f.get("batch_label") or ("截图" if f["doc_type"] == "EVD-SHOT" else "扫描结果"))
            dest = naming.unique_path(pdir / S.EVIDENCE_DIR / f"{naming.date_compact(doc_date)}_{label}" / src.name)
            name = dest.name
        else:
            doc = None if tdef.get("series") else self._find_document(proj["id"], f["doc_type"], title)
            override = str(f.get("version") or "").strip().upper()
            if override and naming.VERSION_RE.match(override):
                version = override
            else:
                version = naming.next_version(doc["current_version"] if doc else None, status)
            name = naming.build_name(proj["project_no"], f["doc_type"], title, version, status, doc_date, src.suffix)
            dest = naming.unique_path(pdir / tdef["stage"] / name)
            if doc:
                doc_id = doc["id"]
                prev_version = doc["current_version"]
                for old in self.db.q("SELECT * FROM files WHERE document_id=? AND state='archived'", (doc_id,)):
                    op_src = Path(old["archive_path"])
                    if op_src.exists():
                        hist = naming.unique_path(pdir / S.HISTORY_DIR / op_src.name)
                        self._move(job_id, op_src, hist, "supersede", {"file_id": old["id"]})
                        self.db.update("files", old["id"], {"state": "superseded", "archive_path": str(hist)})
                    else:
                        self.db.update("files", old["id"], {"state": "superseded"})
                self.db.update("documents", doc_id, {"current_version": version, "status": status,
                                                     "title": title, "updated_at": now()})
            else:
                doc_id = self.db.insert("documents", {"project_id": proj["id"], "doc_type": f["doc_type"],
                                                      "title": title, "current_version": version, "status": status,
                                                      "created_at": now(), "updated_at": now()})
                created_doc = True
        self._move(job_id, src, dest, "archive", {"document_id": doc_id, "created_doc": created_doc,
                                                  "prev_version": prev_version})
        job = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,)) or {}
        file_id = self.db.insert("files", {
            "job_id": job_id, "document_id": doc_id, "project_id": proj["id"], "doc_type": f["doc_type"],
            "version": version or "", "status": status, "archive_name": dest.name, "archive_path": str(dest),
            "original_name": job.get("original_name") or src.name, "source": job.get("source") or "",
            "sha256": job.get("sha256") or sha256_of(dest), "size": dest.stat().st_size, "doc_date": doc_date,
            "title": title, "summary": f.get("summary") or "", "snippet": (f.get("snippet") or "")[:400],
            "sensitivity": f.get("sensitivity") or "一般", "state": "archived", "created_at": now()})
        self.db.update("jobs", job_id, {
            "status": "archived", "file_id": file_id, "method": method, "decided_at": now(),
            "staged_path": str(dest),
            "result": {"name": dest.name, "path": str(dest), "project": proj["label"],
                       "stage": tdef["stage"], "version": version or "", "replaced": prev_version or ""}})
        if job.get("batch_id"):
            self.batch_projects[job["batch_id"]] = (proj["id"], time.time())
        return file_id

    def _find_document(self, project_id: int, doc_type: str, title: str) -> Optional[Dict]:
        best, best_r = None, 0.0
        nt = norm(title)
        for d in self.db.q("SELECT * FROM documents WHERE project_id=? AND doc_type=?", (project_id, doc_type)):
            r = difflib.SequenceMatcher(None, nt, norm(d["title"])).ratio()
            if r > best_r:
                best, best_r = d, r
        return best if best_r >= 0.8 else None

    # ------------------------------------------------------------ 复核、撤销、重识别
    def locate(self, job: Dict) -> Optional[Path]:
        """找到待处理文件的当前位置；文件被改名时按内容（大小 + SHA-256）在原文件夹等处找回。"""
        p = Path(job.get("staged_path") or "")
        if p.is_file():
            return p
        dirs: List[Path] = []
        for d in (p.parent, config.review_dir(), config.unmatched_dir(), config.duplicate_dir()):
            if d not in dirs and d.is_dir():
                dirs.append(d)
        for d in dirs:
            for f in d.iterdir():
                try:
                    if not f.is_file() or should_ignore(f) or f.stat().st_size != job.get("size"):
                        continue
                    if sha256_of(f) == job.get("sha256"):
                        owner = self.db.one("SELECT id FROM jobs WHERE staged_path=? AND id!=? AND status IN "
                                            "('pending_review','unmatched','error','duplicate')", (str(f), job["id"]))
                        if owner:
                            continue
                        self.db.update("jobs", job["id"], {"staged_path": str(f)})
                        return f
                except OSError:
                    continue
        return None

    def dismiss(self, job_id: int) -> Dict:
        """移出列表：不再显示在待复核/未匹配/重复文件里，文件本身保留不动。"""
        job = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] not in ("pending_review", "unmatched", "error", "duplicate"):
            raise ValueError("只有待处理的文件可以移出列表")
        where = self.locate(job)
        self.db.update("jobs", job_id, {"status": "ignored", "method": "已移出", "decided_at": now()})
        return {"path": str(where) if where else "", "missing": where is None}

    def confirm(self, job_id: int, fields: Dict, remember: str = "") -> int:
        job = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] not in ("pending_review", "unmatched", "error", "duplicate"):
            raise ValueError("该文件不在待处理状态")
        src = self.locate(job)
        if src is None:
            raise ValueError("找不到这个文件：它可能被改名后又修改过内容、移到别处或删除了。"
                             "请把文件重新放进收件箱，再把这一条「移出列表」。")
        sug = loads(job["suggestion"], {}) or {}
        merged = {**sug, **{k: v for k, v in fields.items() if v not in (None, "")}}
        if not merged.get("project_id") or not merged.get("doc_type"):
            raise ValueError("请选择项目和类型")
        merged["project_id"] = int(merged["project_id"])
        file_id = self.archive(job_id, src, merged, "人工")
        pattern = (remember or "").strip()
        if pattern:
            self.db.insert("rules", {"pattern": pattern, "project_id": merged["project_id"],
                                     "doc_type": merged.get("doc_type", ""), "kind": "project",
                                     "source": "manual", "created_at": now()})
        learned: Dict = {"learned": [], "disabled": []}
        try:
            learned = learning.learn_after_confirm(self.db, file_id)
        except Exception:
            traceback.print_exc()
        return file_id, learned

    def undo(self, job_id: int) -> None:
        job = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] != "archived":
            raise ValueError("只有已归档的文件可以撤销")
        ops = self.db.q("SELECT * FROM operations WHERE job_id=? AND undone=0 ORDER BY id DESC", (job_id,))
        staged = None
        for op in ops:
            data = loads(op["data"], {}) or {}
            if op["kind"] == "archive":
                cur = Path(op["dst"])
                if not cur.exists():
                    raise ValueError(f"文件已被移动或删除：{cur.name}")
                staged = naming.unique_path(config.review_dir() / job["original_name"])
                staged.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cur), str(staged))
                if data.get("document_id"):
                    if data.get("created_doc"):
                        self.db.x("DELETE FROM documents WHERE id=?", (data["document_id"],))
                    elif data.get("prev_version"):
                        self.db.update("documents", data["document_id"], {"current_version": data["prev_version"]})
            elif op["kind"] == "supersede":
                cur, back = Path(op["dst"]), Path(op["src"])
                if cur.exists() and not back.exists():
                    shutil.move(str(cur), str(back))
                    self.db.update("files", data.get("file_id"), {"state": "archived", "archive_path": str(back)})
            self.db.x("UPDATE operations SET undone=1 WHERE id=?", (op["id"],))
        if job.get("file_id"):
            self.db.update("files", job["file_id"], {"state": "undone"})
        self.db.update("jobs", job_id, {"status": "pending_review", "file_id": None, "decided_at": None,
                                        "staged_path": str(staged) if staged else job["staged_path"],
                                        "method": "已撤销"})

    def rerun(self, job_id: int) -> None:
        job = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] not in ("pending_review", "unmatched", "error", "duplicate"):
            raise ValueError("只有待处理的文件可以重新识别")
        src = self.locate(job)
        if src is None:
            raise ValueError("找不到这个文件，无法重新识别。请把文件重新放进收件箱，再把这一条「移出列表」。")
        if job["status"] == "duplicate":
            # 「仍然归档」：从 _重复文件 移回待复核再识别
            dst = naming.unique_path(config.review_dir() / src.name)
            self._move(job_id, src, dst, "stage")
            src = dst
            self.db.update("jobs", job_id, {"staged_path": str(dst), "status": "processing"})
        # 文件被改名过：用新名字重新识别
        self.db.update("jobs", job_id, {"original_name": src.name} if src.name != job["original_name"] else {})
        self.submit(Task(path=str(src), source=job["source"], batch_id=job["batch_id"] or None,
                         rerun_job_id=job_id))

    # ------------------------------------------------------------ 工具
    def _move(self, job_id: int, src: Path, dst: Path, kind: str, data: Optional[Dict] = None) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        make_writable(src)              # 只读文件跨盘移动时删不掉原件
        shutil.move(str(src), str(dst))
        self.db.insert("operations", {"job_id": job_id, "kind": kind, "src": str(src), "dst": str(dst),
                                      "data": data or {}, "created_at": now()})

    def _log_ai(self, job_id: int, provider: str, req: Dict, resp: Dict, ms: int, ok: bool) -> None:
        self.db.insert("ai_calls", {"job_id": job_id, "provider": provider, "request": req, "response": resp,
                                    "ms": ms, "ok": 1 if ok else 0, "created_at": now()})

    def _cleanup_inbox_dir(self, d: Path) -> None:
        """收件箱里处理空了的子文件夹顺手移除（只删空目录和 .DS_Store）。"""
        inbox = config.inbox().resolve()
        try:
            d = d.resolve()
            while d != inbox and inbox in d.parents:
                entries = [e for e in d.iterdir()]
                if all(e.name == ".DS_Store" for e in entries):
                    for e in entries:
                        e.unlink()
                    d.rmdir()
                    d = d.parent
                else:
                    break
        except Exception:
            pass
