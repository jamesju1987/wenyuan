"""Web 服务：只监听本机 127.0.0.1，浏览器打开即用。"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, ai, config, doctypes, naming, ocr, tidy, winsys
from . import sources as SRC
from . import projects as P
from . import standards as S
from .db import DB, loads, now
from .pipeline import Pipeline, Task, should_ignore
from .watcher import InboxWatcher

STATIC = config.APP_DIR / "static"
config.adopt_previous_data()   # 换了文件夹解压新版本：接着用上一次的数据
config.load()
db = DB(config.DB_FILE)
doctypes.load(db)          # 自定义类型、追加的关键词
pipeline = Pipeline(db)
watcher = InboxWatcher(pipeline)
source_watcher = SRC.SourceWatcher(pipeline, db)
KEY_FIELDS = ("jev_api_key", "deepseek_api_key")
QUIT_HOOK = None   # 托盘模式下由 tray.py 设置：优雅退出


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        P.ensure_all_dirs(db)
    except Exception as e:
        print("初始化目录失败：", e)
    watcher.start()
    source_watcher.start()
    try:
        n = pipeline.recover_staging()
        if n:
            print(f"继续处理上次没处理完的 {n} 个文件")
    except Exception as e:
        print("恢复临时文件失败：", e)
    yield
    watcher.stop()
    source_watcher.stop()


app = FastAPI(title="文渊", version=__version__, lifespan=lifespan)


LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1", "testserver"}


def _trusted_write(request: Request) -> bool:
    """改动类请求只接受：带 X-Guidang 标记的（页面脚本、托盘、右键发送），
    或浏览器标明来自本页面的（同源请求）。别的网站伪造的跨站请求一律拒绝。"""
    if request.headers.get("x-guidang") == "1":
        return True
    site = (request.headers.get("sec-fetch-site") or "").lower()
    if site:
        return site in ("same-origin", "none")
    origin = request.headers.get("origin") or ""
    if origin:
        from urllib.parse import urlparse
        return urlparse(origin).netloc.lower() == (request.headers.get("host") or "").lower()
    return False


@app.middleware("http")
async def local_only(request: Request, call_next):
    """只接受本机访问；改动类请求必须带 X-Guidang 标记（别的网页没法跨站伪造这个请求头）。"""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
    if host not in LOCAL_HOSTS:
        return JSONResponse({"detail": "只允许本机访问"}, status_code=403)
    if request.method in ("POST", "PUT", "DELETE", "PATCH") and not _trusted_write(request):
        return JSONResponse({"detail": "请求被拒绝：只接受文渊自己页面发出的操作"}, status_code=403)
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"      # 升级后浏览器一定拿到新版页面脚本
    return resp


@app.exception_handler(ValueError)
async def value_error(_req, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(ai.AIError)
async def ai_error(_req, exc: ai.AIError):
    return JSONResponse({"detail": str(exc)}, status_code=502)


def within_root(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    root = config.root().resolve()
    if p != root and root not in p.parents:
        inbox = config.inbox().resolve()
        if p != inbox and inbox not in p.parents:
            raise HTTPException(400, "只能访问归档库内的文件")
    return p


def rel_of(p: str) -> str:
    try:
        return str(Path(p).resolve().relative_to(config.root().resolve()))
    except Exception:
        return p


# ---------------------------------------------------------------- 状态与设置
def mask(key: str) -> str:
    key = key or ""
    return "" if not key else (key[:4] + "••••••" + key[-4:] if len(key) > 10 else "••••••")


@app.get("/api/state")
def state():
    today = date.today().isoformat()
    c = lambda sql, a=(): (db.one(sql, a) or {}).get("n", 0)  # noqa: E731
    return {
        "version": __version__,
        "platform": sys.platform,
        "root": str(config.root()),
        "root_exists": config.root().exists(),
        "inbox": str(config.inbox()),
        "watcher": watcher.status(),
        "sources": len(source_watcher.sources) if source_watcher.running else 0,
        "queue": pipeline.queue_size(),
        "ai": {"jev": bool(config.get("jev_enabled") and config.get("jev_api_key")),
               "deepseek": bool(config.get("deepseek_enabled") and config.get("deepseek_api_key")),
               "ocr": bool(config.get("ocr_enabled") and ocr.ready())},
        "ocr": ocr.status(),
        "previous_data": config.PREVIOUS_DATA,
        "counts": {
            "today_archived": c("SELECT COUNT(*) n FROM jobs WHERE status='archived' AND decided_at>=?", (today,)),
            "today_auto": c("SELECT COUNT(*) n FROM jobs WHERE status='archived' AND decided_at>=? AND method!='人工'",
                            (today,)),
            "review": c("SELECT COUNT(*) n FROM jobs WHERE status='pending_review'"),
            "unmatched": c("SELECT COUNT(*) n FROM jobs WHERE status IN ('unmatched','error')"),
            "duplicates": c("SELECT COUNT(*) n FROM jobs WHERE status='duplicate' AND created_at>=?", (today,)),
            "files": c("SELECT COUNT(*) n FROM files WHERE state='archived'"),
            "projects": c("SELECT COUNT(*) n FROM projects WHERE status!='已结项'"),
            "all_jobs": c("SELECT COUNT(*) n FROM jobs WHERE status IN ('archived','pending_review','unmatched')"),
            "all_auto": c("SELECT COUNT(*) n FROM jobs WHERE status='archived' AND method!='人工' AND method!='已撤销'"),
        },
    }


@app.get("/api/settings")
def get_settings():
    s = config.all_settings()
    for k in KEY_FIELDS:
        s[k] = mask(s.get(k, ""))
    s["archive_passwords_count"] = len(s.pop("archive_passwords", None) or [])
    s.pop("sources", None)
    return s


class SettingsIn(BaseModel):
    archive_root: Optional[str] = None
    inbox_dir: Optional[str] = None
    watch_enabled: Optional[bool] = None
    auto_threshold: Optional[float] = None
    review_threshold: Optional[float] = None
    jev_enabled: Optional[bool] = None
    jev_api_key: Optional[str] = None
    jev_model: Optional[str] = None
    jev_endpoint: Optional[str] = None
    deepseek_enabled: Optional[bool] = None
    deepseek_api_key: Optional[str] = None
    deepseek_model: Optional[str] = None
    deepseek_base_url: Optional[str] = None
    text_chars_for_ai: Optional[int] = None
    recent_project_days: Optional[int] = None
    history_enabled: Optional[bool] = None
    learn_enabled: Optional[bool] = None
    learn_min_samples: Optional[int] = None
    ocr_enabled: Optional[bool] = None
    ocr_pdf_pages: Optional[int] = None
    unpack_enabled: Optional[bool] = None
    unpack_max_files: Optional[int] = None
    keep_archives: Optional[bool] = None
    archive_passwords: Optional[List[str]] = None
    source_unmatched: Optional[str] = None
    sendto_move: Optional[bool] = None
    notify_enabled: Optional[bool] = None


@app.post("/api/settings")
def save_settings(body: SettingsIn):
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    for k in KEY_FIELDS:
        if k in changes and "••" in str(changes[k]):
            changes.pop(k)
        elif k in changes:
            changes[k] = str(changes[k]).strip()
    restart = any(k in changes for k in ("archive_root", "inbox_dir", "watch_enabled"))
    if "archive_root" in changes:
        changes["archive_root"] = str(Path(changes["archive_root"]).expanduser())
    if "source_unmatched" in changes and changes["source_unmatched"] not in ("ignore", "keep"):
        changes.pop("source_unmatched")
    config.update(changes)
    if restart:
        P.ensure_all_dirs(db)
        watcher.start()
        source_watcher.start()
    return get_settings()


@app.post("/api/settings/pick-folder")
def pick_folder():
    if sys.platform == "darwin":
        script = 'POSIX path of (choose folder with prompt "选择文件夹")'
        r = subprocess.run(["osascript", "-e", "activate", "-e", script], capture_output=True, text=True)
        path = r.stdout.strip()
        if r.returncode != 0 or not path:
            return {"path": ""}
        return {"path": path.rstrip("/")}
    try:
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory()
        root.destroy()
        return {"path": path or ""}
    except Exception:
        raise HTTPException(400, "当前系统不支持弹窗选择，请直接输入路径")


@app.post("/api/settings/test/{provider}")
def test_provider(provider: str):
    if provider == "jev":
        return ai.test_jev()
    if provider == "deepseek":
        return ai.test_deepseek()
    if provider == "ocr":
        if not ocr.installed():
            raise HTTPException(400, ocr.status()["msg"])
        try:
            r = ocr.self_test()
        except Exception as e:
            raise HTTPException(400, f"识别组件加载失败：{e}")
        if not r["ok"]:
            raise HTTPException(400, f"识别结果不对：{r['text'] or '没有识别到文字'}")
        return {"ok": True, "ms": r["ms"], "model": ocr.status()["msg"], "title": r["text"]}
    raise HTTPException(404)


# ---------------------------------------------------------------- 规范
@app.get("/api/standards")
def standards():
    return {"stages": S.STAGES, "statuses": S.STATUSES, "formula": S.NAME_FORMULA,
            "types": [{"code": t["code"], "name": t["name"], "stage": t["stage"], "keywords": t["kw"],
                       "evidence": bool(t.get("evidence")), "series": bool(t.get("series")),
                       "builtin": bool(t.get("builtin")), "enabled": bool(t.get("enabled", True))}
                      for t in S.TYPE_MAP.values()],
            "type_stages": S.TYPE_STAGES, "stage_prefix": S.STAGE_PREFIX,
            "biz_lines": list(S.BIZ_LINES.keys())}


# ---------------------------------------------------------------- 交付物类型（可新增）
@app.get("/api/types")
def types_list():
    return doctypes.list_types(db)


class TypeIn(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    stage: Optional[str] = None
    keywords: Optional[Any] = None
    extra_keywords: Optional[Any] = None
    series: Optional[bool] = None
    enabled: Optional[bool] = None


@app.post("/api/types")
def types_create(body: TypeIn):
    t = doctypes.create(db, body.model_dump())
    return {"code": t["code"], "types": doctypes.list_types(db)}


@app.put("/api/types/{code}")
def types_update(code: str, body: TypeIn):
    doctypes.update(db, code, body.model_dump())
    return {"code": code, "types": doctypes.list_types(db)}


@app.delete("/api/types/{code}")
def types_delete(code: str):
    doctypes.delete(db, code)
    return {"types": doctypes.list_types(db)}


class NameIn(BaseModel):
    project_id: Optional[int] = None
    doc_type: str = "OTH-DOC"
    title: str = ""
    status: str = "正式"
    doc_date: Optional[str] = None
    version: Optional[str] = None
    ext: str = ""


@app.post("/api/preview-name")
def preview_name(body: NameIn):
    proj = P.get_project(db, body.project_id) if body.project_id else None
    if not proj:
        return {"name": "", "path": "", "valid": False}
    t = S.TYPE_MAP.get(body.doc_type) or S.TYPE_MAP["OTH-DOC"]
    title = naming.clean_title(body.title or t["name"], proj["customer_short"], t["name"],
                               proj.get("aliases"), proj.get("customer_full", ""))
    if t.get("evidence"):
        return {"name": "（证据文件保留原名）", "path": f"{proj['customer_dir']}/{proj['dir_name']}/{S.EVIDENCE_DIR}/",
                "valid": True, "version": "", "title": title}
    version = (body.version or "").strip().upper()
    if not naming.VERSION_RE.match(version):
        doc = None if t.get("series") else pipeline._find_document(proj["id"], body.doc_type, title)
        version = naming.next_version(doc["current_version"] if doc else None, body.status)
    name = naming.build_name(proj["project_no"], body.doc_type, title, version, body.status, body.doc_date, body.ext)
    return {"name": name, "path": f"{proj['customer_dir']}/{proj['dir_name']}/{t['stage']}/", "valid": naming.validate_name(name),
            "version": version, "title": title}


# ---------------------------------------------------------------- 客户与项目
@app.get("/api/projects")
def projects_list():
    return P.list_projects(db)


@app.get("/api/customers")
def customers_list():
    rows = db.q("SELECT * FROM customers ORDER BY short_name")
    for r in rows:
        r["aliases"] = loads(r["aliases"], [])
    return rows


class ProjectIn(BaseModel):
    project_no: str
    name: str = ""
    short_name: str = ""
    customer_id: Optional[int] = None
    customer_full: str = ""
    customer_short: str = ""
    customer_code: str = ""
    customer_aliases: Optional[str] = None
    biz_line: str = ""
    status: str = "进行中"
    start_date: str = ""
    end_date: str = ""
    keywords: str = ""


@app.post("/api/projects")
def project_create(body: ProjectIn):
    p = P.save_project(db, body.model_dump())
    a = tidy.adopt_project_folders(db, {p["id"]})      # 归档库里已有这个项目编号的旧文件夹：接上
    if a["folders"]:
        p["adopted"] = a
    return p


@app.put("/api/projects/{pid}")
def project_update(pid: int, body: ProjectIn):
    return P.save_project(db, body.model_dump(), pid, replace_aliases=True)


class CustomerIn(BaseModel):
    short_name: str
    full_name: str = ""
    aliases: str = ""


@app.put("/api/customers/{cid}")
def customer_update(cid: int, body: CustomerIn):
    c = P.update_customer(db, cid, body.short_name, body.full_name, body.aliases)
    c["aliases"] = loads(c["aliases"], [])
    return c


@app.post("/api/projects/import")
async def project_import(file: UploadFile = File(...)):
    content = await file.read()
    created, updated, errors = P.import_table(db, file.filename or "import.csv", content)
    a = tidy.adopt_project_folders(db)     # 同一项目编号的旧文件夹（换过数据库留下的）并到正式目录
    return {"created": created, "updated": updated, "errors": errors[:20],
            "adopted": a["folders"], "registered": a["registered"]}


# ---------------------------------------------------------------- 整理重复客户
@app.get("/api/tidy")
def tidy_scan(quick: bool = False):
    return tidy.scan(db, quick)


class TidyGroup(BaseModel):
    target: int
    customers: List[int] = []
    folders: List[str] = []


class TidyIn(BaseModel):
    groups: List[TidyGroup] = []
    reindex: bool = True


@app.post("/api/tidy/merge")
def tidy_merge(body: TidyIn):
    if pipeline.queue_size():
        raise HTTPException(409, "正在归档文件，等收件箱处理完再整理")
    r = tidy.merge(db, [g.model_dump() for g in body.groups], body.reindex)
    P.ensure_all_dirs(db)
    return r


@app.get("/api/projects/template.csv")
def project_template():
    return Response(P.template_csv(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''%E9%A1%B9%E7%9B%AE%E5%AF%BC%E5%85%A5%E6%A8%A1%E6%9D%BF.csv"})


@app.post("/api/projects/{pid}/package")
def project_package(pid: int):
    proj = P.get_project(db, pid)
    if not proj:
        raise HTTPException(404, "项目不存在")
    pdir = config.root() / proj["customer_dir"] / proj["dir_name"]
    out_dir = pdir / S.PACKAGE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    zpath = naming.unique_path(out_dir / f"{proj['project_no']}_归档包_{date.today():%Y%m%d}.zip")
    manifest = io.StringIO()
    w = csv.writer(manifest)
    w.writerow(["相对路径", "大小(字节)", "SHA-256", "版本", "状态"])
    info = {f["archive_path"]: f for f in db.q("SELECT * FROM files WHERE project_id=?", (pid,))}
    count = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fp in sorted(pdir.rglob("*")):
            if fp.is_dir() or S.PACKAGE_DIR in fp.relative_to(pdir).parts or fp.name.startswith("."):
                continue
            rel = fp.relative_to(pdir)
            h = hashlib.sha256(fp.read_bytes()).hexdigest()
            rec = info.get(str(fp), {})
            w.writerow([str(rel), fp.stat().st_size, h, rec.get("version", ""), rec.get("status", "")])
            z.write(fp, f"{pdir.name}/{rel}")
            count += 1
        z.writestr(f"{pdir.name}/文件清单.csv", "﻿" + manifest.getvalue())
    return {"path": str(zpath), "name": zpath.name, "files": count}


# ---------------------------------------------------------------- 文件投放
@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...), project_id: Optional[int] = Form(None)):
    config.ensure_system_dirs()
    batch = uuid.uuid4().hex[:8]
    tmp = config.inbox() / ".uploading" / batch
    tmp.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in files:
        name = Path(f.filename or "file").name
        if not name or name.startswith("."):
            continue
        dest = naming.unique_path(tmp / name)
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        pipeline.submit(Task(path=str(dest), source="网页上传", preset_project_id=project_id or None,
                             batch_id=f"upload:{batch}" if len(files) > 1 else None))
        n += 1
    return {"accepted": n}


@app.post("/api/scan")
def scan():
    return {"found": watcher.scan_now()}


class IngestIn(BaseModel):
    paths: List[str]
    source: str = "右键发送"
    move: Optional[bool] = None


@app.post("/api/ingest")
def ingest(body: IngestIn):
    """右键「发送到 → 文渊」：复制（或按设置移动）到收件箱的临时区，逐个识别；多个文件算同一批。"""
    config.ensure_system_dirs()
    move = bool(config.get("sendto_move") if body.move is None else body.move)
    root = config.root().resolve()
    files, dirs, skipped = [], [], []
    for raw in body.paths:
        p = Path(raw).expanduser()
        if not p.exists():
            skipped.append(f"找不到：{raw}")
            continue
        rp = p.resolve()
        if rp == root or root in rp.parents:
            skipped.append(f"已经在归档库里，不用再发送：{p.name}")
            continue
        if p.is_dir():
            count = sum(len(fs) for _, _, fs in os.walk(p))
            if count > 2000:
                skipped.append(f"文件夹里文件太多（{count} 个），请分批发送：{p.name}")
                continue
            dirs.append(p)
        elif not should_ignore(p):
            files.append(p)
    batch = uuid.uuid4().hex[:8]
    base = config.inbox() / ".发送" / batch
    n = 0
    for p in files:
        dst = naming.unique_path(base / p.name)
        dst.parent.mkdir(parents=True, exist_ok=True)
        (shutil.move if move else shutil.copy2)(str(p), str(dst))
        pipeline.submit(Task(path=str(dst), source=body.source, batch_id=f"send:{batch}" if len(files) > 1 else None))
        n += 1
    for d in dirs:
        dst = naming.unique_path(base / naming.safe_dir_name(d.name))
        if move:
            shutil.move(str(d), str(dst))
        else:
            shutil.copytree(str(d), str(dst), ignore=shutil.ignore_patterns(".*", "~$*", "Thumbs.db", "desktop.ini"))
        for f in sorted(dst.rglob("*")):
            if f.is_file() and not should_ignore(f):
                pipeline.submit(Task(path=str(f), source=body.source, batch_id=f"send:{batch}:{d.name}",
                                     batch_label=d.name))
                n += 1
    return {"accepted": n, "skipped": skipped}


@app.post("/api/quit")
def quit_app():
    def later():
        time.sleep(0.4)
        try:
            if QUIT_HOOK:
                QUIT_HOOK()
                return
        except Exception:
            pass
        os._exit(0)
    threading.Thread(target=later, daemon=True).start()
    return {"ok": True}


# ---------------------------------------------------------------- 系统集成（Windows）
@app.get("/api/system")
def system_info():
    return {"platform": sys.platform, "autostart": winsys.autostart_get(), "sendto": winsys.sendto_get(),
            "tray": QUIT_HOOK is not None, "app_dir": str(config.APP_DIR)}


class ToggleIn(BaseModel):
    enabled: bool


@app.put("/api/system/autostart")
def set_autostart(body: ToggleIn):
    if not winsys.IS_WIN:
        raise HTTPException(400, "Mac 上请双击「设置开机自动运行.command」")
    return {"autostart": winsys.autostart_set(body.enabled)}


@app.put("/api/system/sendto")
def set_sendto(body: ToggleIn):
    config.update({"sendto_enabled": body.enabled})
    if not winsys.IS_WIN:
        return {"sendto": None}
    ok = winsys.sendto_set(body.enabled)
    if body.enabled and not ok:
        raise HTTPException(500, "没能创建右键菜单项（PowerShell 被禁用？）")
    return {"sendto": ok}


# ---------------------------------------------------------------- 文件来源（微信、企业微信…）
def _sources_view() -> Dict:
    return {"sources": source_watcher.status(), "unmatched": config.get("source_unmatched")}


@app.get("/api/sources")
def sources_list():
    return _sources_view()


@app.post("/api/sources/detect")
def sources_detect():
    have = {os.path.normcase(str(Path(s["path"]))) for s in SRC.all_sources()}
    found = SRC.detect()
    added = []
    for c in found:
        if os.path.normcase(c["path"]) in have:
            continue
        try:
            added.append(SRC.add_source(c["path"], c["name"], c["kind"], enabled=c["kind"] != "folder"))
        except ValueError:
            continue
    source_watcher.start()
    return {**_sources_view(), "found": len(found), "added": len(added)}


class SourceIn(BaseModel):
    path: str
    name: str = ""


@app.post("/api/sources")
def sources_add(body: SourceIn):
    SRC.add_source(body.path, body.name.strip())
    source_watcher.start()
    return _sources_view()


class SourcePatch(BaseModel):
    enabled: Optional[bool] = None
    name: Optional[str] = None


@app.put("/api/sources/{sid}")
def sources_update(sid: str, body: SourcePatch):
    SRC.update_source(sid, body.model_dump())
    source_watcher.start()
    return _sources_view()


@app.delete("/api/sources/{sid}")
def sources_delete(sid: str):
    SRC.remove_source(sid)
    source_watcher.start()
    return _sources_view()


# ---------------------------------------------------------------- 任务、复核
PENDING = ("pending_review", "unmatched", "error", "duplicate")


def _job_view(j: Dict) -> Dict:
    j["suggestion"] = loads(j["suggestion"], {}) or {}
    j["result"] = loads(j["result"], {}) or {}
    j["ext"] = Path(j["original_name"] or "").suffix.lower()
    if j["status"] in PENDING:
        where = pipeline.locate(j)
        j["missing"] = where is None
        if where is not None:
            j["staged_path"] = str(where)
    j["current_name"] = Path(j["staged_path"] or "").name
    if j["status"] == "ignored" and j.get("original_path") and j["original_path"] != j.get("staged_path"):
        j["origin_exists"] = Path(j["original_path"]).exists()
    return j


@app.get("/api/jobs")
def jobs(status: str = "", limit: int = 100):
    if status:
        sts = tuple(status.split(","))
        rows = db.q(f"SELECT * FROM jobs WHERE status IN ({','.join('?' * len(sts))}) ORDER BY id DESC LIMIT ?",
                    sts + (limit,))
    else:
        rows = db.q("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
    return [_job_view(j) for j in rows]


class ConfirmIn(BaseModel):
    project_id: Optional[int] = None
    doc_type: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    doc_date: Optional[str] = None
    version: Optional[str] = None
    remember: Optional[str] = ""


class UnpackIn(BaseModel):
    password: str = ""
    remember: bool = False


@app.post("/api/jobs/{job_id}/unpack")
def job_unpack(job_id: int, body: UnpackIn):
    return {"count": pipeline.unpack_job(job_id, body.password, body.remember)}


@app.post("/api/jobs/{job_id}/reimport")
def job_reimport(job_id: int):
    """来源里被忽略的文件：从原位置再复制一份，放进待复核/未匹配。"""
    job = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not job or job["status"] != "ignored":
        raise HTTPException(400, "只有被忽略的文件可以拿来归档")
    orig = Path(job["original_path"] or "")
    if not orig.is_file():
        raise HTTPException(400, "原文件已经不在了（可能被微信清理了）")
    stage = naming.unique_path(config.inbox() / ".来源" / "拿来归档" / orig.name)
    stage.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(orig), str(stage))
    db.update("jobs", job_id, {"staged_path": str(stage), "status": "processing"})
    pipeline.submit(Task(path=str(stage), source=job["source"], origin=str(orig), keep_unmatched=True,
                         rerun_job_id=job_id))
    return {"ok": True}


@app.post("/api/jobs/{job_id}/confirm")
def job_confirm(job_id: int, body: ConfirmIn):
    fields = body.model_dump()
    remember = fields.pop("remember") or ""
    fid, learned = pipeline.confirm(job_id, fields, remember)
    for item in learned.get("learned", []):
        item["text"] = _rule_text(item)
    return {"file_id": fid, "learned": learned.get("learned", []), "disabled": learned.get("disabled", []),
            "job": _job_view(db.one("SELECT * FROM jobs WHERE id=?", (job_id,)))}


def _rule_text(r: Dict) -> str:
    tname = S.TYPE_MAP.get(r.get("doc_type") or "", {}).get("name", "")
    if r.get("kind") == "type":
        return f"文件名包含「{r['pattern']}」→ 类型：{tname}"
    p = P.get_project(db, r.get("project_id") or 0)
    return f"文件名包含「{r['pattern']}」→ {p['label'] if p else '已删除的项目'}" + (f" · {tname}" if tname else "")


@app.post("/api/jobs/{job_id}/undo")
def job_undo(job_id: int):
    pipeline.undo(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/rerun")
def job_rerun(job_id: int):
    pipeline.rerun(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/dismiss")
def job_dismiss(job_id: int):
    r = pipeline.dismiss(job_id)
    if r["path"]:
        r["rel"] = rel_of(r["path"])
    return r


@app.get("/api/rules")
def rules():
    rows = db.q("""SELECT r.*, p.project_no, p.short_name FROM rules r LEFT JOIN projects p ON p.id=r.project_id
                   ORDER BY r.enabled DESC, r.id DESC""")
    for r in rows:
        r["kind"] = r.get("kind") or "project"
        r["source"] = r.get("source") or "manual"
        r["type_name"] = S.TYPE_MAP.get(r.get("doc_type") or "", {}).get("name", "")
        r["text"] = _rule_text(r)
    return rows


class RuleIn(BaseModel):
    enabled: bool


@app.put("/api/rules/{rid}")
def rule_update(rid: int, body: RuleIn):
    db.x("UPDATE rules SET enabled=? WHERE id=?", (1 if body.enabled else 0, rid))
    return {"ok": True}


@app.delete("/api/rules/{rid}")
def rule_delete(rid: int):
    db.x("DELETE FROM rules WHERE id=?", (rid,))
    return {"ok": True}


# ---------------------------------------------------------------- 浏览、搜索
@app.get("/api/browse")
def browse(path: str = ""):
    root = config.root()
    target = within_root(str(root / path)) if path else root.resolve()
    if not target.exists() or not target.is_dir():
        raise HTTPException(404, "目录不存在")
    records = {f["archive_path"]: f for f in db.q(
        "SELECT * FROM files WHERE archive_path LIKE ?", (str(target) + "%",))}
    cust = {c["dir_name"]: c for c in db.q("SELECT * FROM customers")}
    projs = {p["dir_name"]: p for p in db.q("SELECT * FROM projects")}
    entries = []
    for e in target.iterdir():
        if e.name.startswith("."):
            continue
        st = e.stat()
        item: Dict[str, Any] = {"name": e.name, "path": str(e.relative_to(root.resolve())) if str(e).startswith(str(root.resolve())) else str(e),
                                "dir": e.is_dir(), "mtime": st.st_mtime, "size": st.st_size,
                                "system": e.name in config.SYSTEM_DIRS}
        if e.is_dir():
            try:
                item["count"] = sum(1 for x in e.iterdir() if not x.name.startswith("."))
            except Exception:
                item["count"] = 0
            if e.name in cust:
                item["display"] = cust[e.name]["short_name"]
                item["kind"] = "customer"
            elif e.name in projs:
                item["display"] = projs[e.name]["short_name"]
                item["kind"] = "project"
        else:
            rec = records.get(str(e.resolve())) or records.get(str(e))
            if rec:
                item.update({"file_id": rec["id"], "version": rec["version"], "status": rec["status"],
                             "doc_type": rec["doc_type"], "sensitivity": rec["sensitivity"]})
        entries.append(item)
    entries.sort(key=lambda x: (not x["dir"], x.get("system", False), x["name"]))
    return {"path": path, "entries": entries}


@app.get("/api/file")
def file_detail(path: str):
    p = within_root(str(config.root() / path))
    if not p.exists():
        raise HTTPException(404, "文件不存在")
    rec = db.one("SELECT * FROM files WHERE archive_path=? ORDER BY id DESC LIMIT 1", (str(p),)) or \
        db.one("SELECT * FROM files WHERE archive_path=? ORDER BY id DESC LIMIT 1", (str(config.root() / path),))
    out: Dict[str, Any] = {"name": p.name, "path": path, "size": p.stat().st_size, "mtime": p.stat().st_mtime,
                           "record": rec, "versions": [], "external_name": naming.external_name(p.name)}
    if rec:
        if rec.get("document_id"):
            out["versions"] = [{**v, "rel": rel_of(v["archive_path"])} for v in db.q(
                "SELECT id, version, status, archive_name, archive_path, state, created_at FROM files "
                "WHERE document_id=? AND state IN ('archived','superseded') ORDER BY id DESC", (rec["document_id"],))]
        if rec.get("project_id"):
            out["project"] = P.get_project(db, rec["project_id"])
        if rec.get("job_id"):
            j = db.one("SELECT id, method, source, original_name, confidence, created_at FROM jobs WHERE id=?",
                       (rec["job_id"],))
            out["job"] = j
        out["type_name"] = S.TYPE_MAP.get(rec.get("doc_type") or "", {}).get("name", "")
    return out


@app.get("/api/search")
def search(q: str, limit: int = 80):
    q = q.strip()
    if not q:
        return []
    terms = [t.lower() for t in q.replace("　", " ").split(" ") if t]
    rows = db.q("""SELECT f.*, p.project_no, p.short_name AS project_short, p.name AS project_name, p.biz_line,
                   c.short_name AS customer_short, c.full_name AS customer_full, c.aliases AS customer_aliases
                   FROM files f LEFT JOIN projects p ON p.id=f.project_id LEFT JOIN customers c ON c.id=p.customer_id
                   WHERE f.state IN ('archived','superseded')""")
    scored = []
    for r in rows:
        tname = S.TYPE_MAP.get(r.get("doc_type") or "", {}).get("name", "")
        short = [r.get("archive_name"), r.get("title"), r.get("original_name"), r.get("project_short"),
                 r.get("customer_short"), r.get("project_no"), tname]
        long = [r.get("summary"), r.get("snippet"), r.get("project_name"), r.get("customer_full"),
                r.get("biz_line"), " ".join(loads(r.get("customer_aliases"), []) or [])]
        total = 0.0
        for t in terms:
            best = max([fuzzy_score(t, s, fuzzy=True) for s in short] + [0.6 * fuzzy_score(t, s, fuzzy=False) for s in long])
            if best <= 0:
                total = 0
                break
            total += best
        if total > 0:
            scored.append((total, r["id"], r))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    out = []
    for _, _, r in scored[:limit]:
        r["rel"] = rel_of(r["archive_path"])
        r["type_name"] = S.TYPE_MAP.get(r.get("doc_type") or "", {}).get("name", "")
        for k in ("customer_aliases", "snippet"):
            r.pop(k, None)
        out.append(r)
    return out


def fuzzy_score(term: str, text: Optional[str], fuzzy: bool = True) -> float:
    """连续出现得分最高；fuzzy=True 时允许中间隔字（如「澄湾等保」能找到「澄湾科技等保测评报告」）。"""
    if not text or not term:
        return 0.0
    s = str(text).lower()
    i = s.find(term)
    if i >= 0:
        return 3.0 + (0.5 if i == 0 else 0) + min(len(term), 10) * 0.1
    if not fuzzy or len(term) < 2:
        return 0.0
    pos, first, gaps = 0, -1, 0
    for ch in term:
        j = s.find(ch, pos)
        if j < 0:
            return 0.0
        if first < 0:
            first = j
        elif j > pos:
            gaps += j - pos
        pos = j + 1
    span = pos - first
    # 太分散的不算；纯字母数字（多半是编号片段）只容许很小的间隔，免得乱配到项目编号里
    limit = len(term) + 3 if term.isascii() else len(term) * 4 + 6
    if span > limit:
        return 0.0
    return 1.0 + len(term) / span


class OpenIn(BaseModel):
    path: str
    mode: str = "open"  # open | reveal | quicklook


@app.post("/api/open")
def open_path(body: OpenIn):
    raw = body.path
    p = within_root(raw if os.path.isabs(raw) else str(config.root() / raw))
    if not p.exists():
        raise HTTPException(404, "文件不存在")
    try:
        if sys.platform == "darwin":
            if body.mode == "reveal":
                subprocess.Popen(["open", "-R", str(p)])
            elif body.mode == "quicklook" and p.is_file():
                subprocess.Popen(["qlmanage", "-p", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["open", str(p)])
        elif sys.platform.startswith("win"):
            if body.mode == "reveal":
                subprocess.Popen(["explorer", "/select,", str(p)])
            else:
                os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(p if body.mode != "reveal" else p.parent)])
    except Exception as e:
        raise HTTPException(500, f"无法打开：{e}")
    return {"ok": True}


@app.get("/api/download")
def download(path: str):
    p = within_root(path if os.path.isabs(path) else str(config.root() / path))
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(str(p), filename=p.name)


# ---------------------------------------------------------------- 页面
def _asset_token() -> str:
    """页面脚本和样式的版本号：文件一变就换地址，浏览器不会再用缓存里的旧脚本。"""
    h = hashlib.sha1(__version__.encode())
    for name in ("app.js", "style.css"):
        st = (STATIC / name).stat()
        h.update(f"{name}:{st.st_mtime_ns}:{st.st_size}".encode())
    return h.hexdigest()[:10]


@app.get("/")
def index():
    v = _asset_token()
    html = (STATIC / "index.html").read_text("utf-8")
    html = html.replace('"/static/app.js"', f'"/static/app.js?v={v}"').replace('"/static/style.css"', f'"/static/style.css?v={v}"')
    return Response(html, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def run():
    import uvicorn

    port = int(os.environ.get("GUIDANG_PORT", "8790"))
    print(f"\n  文渊 {__version__} 已启动：http://127.0.0.1:{port}\n  归档库：{config.root()}\n  关闭此窗口即可退出。\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    run()
