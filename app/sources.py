"""额外的文件来源：微信、企业微信、下载文件夹……

- 只复制、不移动也不删除原文件（微信还要用它打开聊天里的文件）。
- 只收「开启之后」新出现的文件，以前的历史文件不管。
- 每个文件只收一次（记在 source_seen 表里）；内容和已归档文件相同的直接跳过。
- 认不出属于哪个项目的（多半是私人文件）默认忽略，可在设置里改为放进「未匹配」。
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
import uuid
from glob import glob
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config, naming
from .db import DB, now
from .pipeline import Pipeline, Task, should_ignore

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
    HAS_WATCHDOG = True
except Exception:
    HAS_WATCHDOG = False
    FileSystemEventHandler = object  # type: ignore

# 只收这些类型：文档、图片、压缩包（安装包、音视频、聊天缓存一律不收）
SOURCE_EXT = {
    ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".ppt", ".pptx", ".pdf", ".wps", ".et", ".dps", ".rtf", ".odt",
    ".txt", ".md", ".csv", ".vsd", ".vsdx", ".xmind", ".mpp", ".nessus",
    ".png", ".jpg", ".jpeg", ".heic", ".bmp", ".webp", ".tif", ".tiff",
    ".zip", ".7z", ".rar", ".tar", ".gz", ".tgz",
}
MAX_SIZE = 500 * 1024 * 1024
KIND_NAMES = {"wechat": "微信", "wxwork": "企业微信", "folder": "文件夹"}


# ---------------------------------------------------------------- 自动查找
def _documents_dir() -> Path:
    """「文档」文件夹（可能被挪到 D 盘或 OneDrive）。"""
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                v, _ = winreg.QueryValueEx(k, "Personal")
                p = Path(os.path.expandvars(v))
                if p.exists():
                    return p
        except Exception:
            pass
    return Path.home() / "Documents"


def _ini_paths(folder: Path) -> List[Path]:
    """微信把自定义的存储位置写在 config 文件夹的 .ini 里（内容就是一个路径，默认是 MyDocument:）。"""
    out: List[Path] = []
    try:
        for f in sorted(folder.glob("*.ini")):
            try:
                raw = f.read_bytes()[:1024]
            except OSError:
                continue
            for enc in ("utf-8", "gbk", "utf-16"):
                try:
                    v = raw.decode(enc).strip().strip("\x00").strip()
                    break
                except UnicodeDecodeError:
                    v = ""
            if v and v != "MyDocument:" and len(v) < 260 and Path(v).is_dir():
                out.append(Path(v))
    except OSError:
        pass
    return out


def _fixed_drives() -> List[Path]:
    """本机的固定磁盘（C:、D:…），不碰网络盘和光驱，免得卡住。"""
    if not sys.platform.startswith("win"):
        return []
    out: List[Path] = []
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if mask & (1 << i):
                root = f"{chr(65 + i)}:\\"
                if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:      # DRIVE_FIXED
                    out.append(Path(root))
    except Exception:
        pass
    return out


def _chat_roots() -> List[Path]:
    """可能放着「WeChat Files」「xwechat_files」「WXWork」的文件夹。"""
    roots: List[Path] = [_documents_dir()]
    if sys.platform.startswith("win"):
        appdata = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        roots += _ini_paths(appdata / "Tencent" / "xwechat" / "config")                 # 微信 4.x
        roots += _ini_paths(appdata / "Tencent" / "WeChat" / "All Users" / "config")    # 微信 3.x
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Tencent\WeChat") as k:
                v, _ = winreg.QueryValueEx(k, "FileSavePath")
                if v and v != "MyDocument:" and Path(v).is_dir():
                    roots.append(Path(v))
        except Exception:
            pass
        # 存储位置改到了别的盘：看一下每个盘的根目录和第一层文件夹
        for d in _fixed_drives():
            roots.append(d)
            try:
                roots += [x for x in d.iterdir() if x.is_dir() and not x.name.startswith(("$", "."))
                          and x.name.lower() not in ("windows", "program files", "program files (x86)", "programdata")]
            except OSError:
                continue
    out, seen = [], set()
    for r in roots:
        k = os.path.normcase(str(r))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


# 每种聊天软件：存放账号的文件夹名 → 每个账号下「收到的文件」在哪（找不到就退一级，靠路径里的 file 过滤）
CHAT_LAYOUT = (
    ("WeChat Files", "wechat", (("FileStorage", "File"), ("FileStorage",))),        # 微信 3.x
    ("xwechat_files", "wechat", (("msg", "file"), ("msg",))),                      # 微信 4.x
    ("WXWork", "wxwork", (("Cache", "File"), ("Cache",))),                         # 企业微信
)
SKIP_ACCOUNTS = ("all users", "all_users", "applet", "wmpf", "backup", "global", "wxdrive", "plugins")


def _short(name: str) -> str:
    return name if len(name) <= 14 else name[:12] + "…"


def _accounts(container: Path, kind: str, subs) -> List[Tuple[str, str, Path]]:
    out: List[Tuple[str, str, Path]] = []
    try:
        accts = sorted(x for x in container.iterdir() if x.is_dir())
    except OSError:
        return out
    for a in accts:
        if a.name.lower() in SKIP_ACCOUNTS:
            continue
        for sub in subs:
            p = a.joinpath(*sub)
            if p.is_dir():
                out.append((kind, f"{KIND_NAMES[kind]}（{_short(a.name)}）", p))
                break
    return out


def chat_folders(path: Path) -> List[Tuple[str, str, Path]]:
    """给一个文件夹，找出里面（或它所在的）微信、企业微信账号的「收到的文件」文件夹。

    可以是 D:\\、D:\\WeChat Files、…\\xwechat_files\\wxid_x\\msg\\file\\2026-10 这类任意一层。
    """
    found: List[Tuple[str, str, Path]] = []
    parts_l = [x.lower() for x in path.parts]
    for cname, kind, subs in CHAT_LAYOUT:
        if cname.lower() in parts_l:                       # 在某个账号里面：退回到这个账号
            i = parts_l.index(cname.lower())
            if len(path.parts) > i + 1:
                acct = Path(*path.parts[: i + 2])
                found += [t for t in _accounts(acct.parent, kind, subs) if t[2].is_relative_to(acct)]
            else:
                found += _accounts(path, kind, subs)
            continue
        c = path / cname
        if c.is_dir():
            found += _accounts(c, kind, subs)
    return found


def detect() -> List[Dict]:
    """找本机微信、企业微信的「接收文件」文件夹和「下载」文件夹。"""
    found: List[Tuple[str, str, Path]] = []
    home = Path.home()
    if sys.platform.startswith("win"):
        for root in _chat_roots():
            found += chat_folders(root)
    elif sys.platform == "darwin":
        c = home / "Library" / "Containers"
        for pattern, kind in (
                (c / "com.tencent.xinWeChat" / "Data" / "Documents" / "xwechat_files" / "*" / "msg" / "file", "wechat"),
                (c / "com.tencent.xinWeChat" / "Data" / "Library" / "Application Support" / "com.tencent.xinWeChat" /
                 "*" / "*" / "Message" / "MessageTemp", "wechat"),
                (c / "com.tencent.WeWorkMac" / "Data" / "Documents" / "Profiles" / "*" / "Caches" / "Files", "wxwork")):
            for g in sorted(glob(str(pattern))):
                p = Path(g)
                if p.is_dir() and not any(x in str(p) for x in ("All Users", "Applet", "WMPF")):
                    found.append((kind, f"{KIND_NAMES[kind]}（{_short(p.parents[1].name)}）", p))
    dl = home / "Downloads"
    if dl.is_dir():
        found.append(("folder", "下载", dl))
    out, seen = [], set()
    for kind, name, p in found:
        key = os.path.normcase(str(p))
        if key not in seen:
            seen.add(key)
            out.append({"kind": kind, "name": name, "path": str(p)})
    return out


# ---------------------------------------------------------------- 来源列表（存在设置里）
def all_sources() -> List[Dict]:
    return [dict(s) for s in (config.get("sources") or []) if isinstance(s, dict) and s.get("path")]


def _save(sources: List[Dict]) -> None:
    config.update({"sources": sources})


def check_path(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_dir():
        raise ValueError("文件夹不存在")
    p = p.resolve()
    for sys_dir in (config.root(), config.inbox()):
        r = sys_dir.expanduser().resolve()
        if p == r or r in p.parents or p in r.parents:
            raise ValueError("不能添加归档库所在的文件夹（会把归档好的文件又收一遍）")
    return p


def add_source(path: str, name: str = "", kind: str = "folder", enabled: bool = True) -> Dict:
    p = check_path(path)
    sources = all_sources()
    for s in sources:
        if os.path.normcase(str(Path(s["path"]))) == os.path.normcase(str(p)):
            raise ValueError(f"已经添加过：{s['name']}")
    src = {"id": uuid.uuid4().hex[:8], "kind": kind, "name": name or p.name or str(p), "path": str(p),
           "enabled": bool(enabled), "since": time.time()}
    _save(sources + [src])
    return src


def update_source(sid: str, changes: Dict) -> Dict:
    sources = all_sources()
    for s in sources:
        if s.get("id") == sid:
            if "enabled" in changes and bool(changes["enabled"]) and not s.get("enabled"):
                s["since"] = time.time()          # 重新打开：只收打开之后的新文件
            for k in ("enabled", "name"):
                if k in changes and changes[k] is not None:
                    s[k] = changes[k]
            _save(sources)
            return s
    raise ValueError("来源不存在")


def remove_source(sid: str) -> None:
    _save([s for s in all_sources() if s.get("id") != sid])


# ---------------------------------------------------------------- 监听
class _Handler(FileSystemEventHandler):  # type: ignore[misc]
    def __init__(self, w: "SourceWatcher", src: Dict):
        self.w, self.src = w, src

    def on_created(self, event):
        if not event.is_directory:
            self.w.touch(event.src_path, self.src)

    def on_modified(self, event):
        if not event.is_directory:
            self.w.touch(event.src_path, self.src)

    def on_moved(self, event):
        if not event.is_directory:
            self.w.touch(event.dest_path, self.src)


class SourceWatcher:
    STABLE_SECONDS = 3.0
    RESCAN_SECONDS = 60.0

    def __init__(self, pipeline: Pipeline, db: DB):
        self.pipeline, self.db = pipeline, db
        self.pending: Dict[str, Tuple[float, int, Dict]] = {}
        self.lock = threading.RLock()
        self.observer = None
        self.running = False
        self.sources: List[Dict] = []
        self._last_scan = 0.0
        self.imported = 0

    def start(self) -> None:
        self.stop()
        self.sources = [s for s in all_sources() if s.get("enabled") and Path(s["path"]).is_dir()]
        if not self.sources or not config.get("watch_enabled"):
            return
        self.running = True
        if HAS_WATCHDOG:
            try:
                self.observer = Observer()
                for s in self.sources:
                    self.observer.schedule(_Handler(self, s), s["path"], recursive=True)
                self.observer.start()
            except Exception:
                self.observer = None
        threading.Thread(target=self._loop, name="source-watcher", daemon=True).start()

    def stop(self) -> None:
        self.running = False
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=3)
            except Exception:
                pass
            self.observer = None

    def status(self) -> List[Dict]:
        on = {s["id"] for s in self.sources} if self.running else set()
        out = []
        for s in all_sources():
            n = (self.db.one("SELECT COUNT(*) n FROM source_seen WHERE source_id=?", (s["id"],)) or {}).get("n", 0)
            out.append({**s, "exists": Path(s["path"]).is_dir(), "active": s["id"] in on, "imported": n})
        return out

    # ------------------------------------------------------------ 判断要不要收
    def _wanted(self, p: Path, src: Dict) -> bool:
        if should_ignore(p) or p.suffix.lower() not in SOURCE_EXT:
            return False
        if any(part.startswith(".") for part in p.parts[-3:]):
            return False
        if src.get("kind") in ("wechat", "wxwork") and not any(x.lower() in ("file", "files") for x in p.parts):
            return False                      # 微信目录里只收「文件」，不收图片缓存、视频等
        try:
            st = p.stat()
        except OSError:
            return False
        if st.st_size == 0 or st.st_size > MAX_SIZE:
            return False
        return st.st_mtime >= float(src.get("since") or 0) - 2

    def touch(self, path: str, src: Dict) -> None:
        p = Path(path)
        if not self._wanted(p, src):
            return
        with self.lock:
            self.pending[str(p)] = (time.time(), p.stat().st_size, src)

    def scan_now(self) -> int:
        n = 0
        for src in self.sources:
            root = Path(src["path"])
            base = len(root.parts)
            for dirpath, dirnames, filenames in os.walk(root):
                depth = len(Path(dirpath).parts) - base
                dirnames[:] = [d for d in dirnames if not d.startswith(".")] if depth < 4 else []
                for fn in filenames:
                    p = Path(dirpath) / fn
                    if str(p) in self.pending or not self._wanted(p, src):
                        continue
                    if self._seen(p):
                        continue
                    with self.lock:
                        self.pending[str(p)] = (time.time() - self.STABLE_SECONDS, p.stat().st_size, src)
                        n += 1
        self._last_scan = time.time()
        return n

    def _seen(self, p: Path) -> bool:
        row = self.db.one("SELECT size, mtime FROM source_seen WHERE path=?", (str(p),))
        if not row:
            return False
        st = p.stat()
        return row["size"] == st.st_size and abs(float(row["mtime"] or 0) - st.st_mtime) < 2

    def _loop(self) -> None:
        self.scan_now()
        while self.running:
            time.sleep(1.0)
            try:
                if time.time() - self._last_scan > self.RESCAN_SECONDS:
                    self.scan_now()
                self._flush()
            except Exception:
                pass

    def _flush(self) -> None:
        t_now = time.time()
        ready = []
        with self.lock:
            for path, (t, size, src) in list(self.pending.items()):
                p = Path(path)
                try:
                    cur = p.stat().st_size
                except OSError:
                    self.pending.pop(path, None)
                    continue
                if cur != size:
                    self.pending[path] = (t_now, cur, src)
                elif t_now - t >= self.STABLE_SECONDS:
                    ready.append((p, src))
                    self.pending.pop(path, None)
        for p, src in ready:
            try:
                self.import_file(p, src)
            except Exception as e:
                print("来源文件复制失败：", p, e)

    def import_file(self, p: Path, src: Dict) -> Optional[str]:
        if self._seen(p):
            return None
        st = p.stat()
        stage = naming.unique_path(config.inbox() / ".来源" / naming.safe_dir_name(src.get("name") or "来源") / p.name)
        stage.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(p), str(stage))
        self.db.x("INSERT OR REPLACE INTO source_seen (path, size, mtime, source_id, seen_at) VALUES (?,?,?,?,?)",
                  (str(p), st.st_size, st.st_mtime, src.get("id", ""), now()))
        self.pipeline.submit(Task(path=str(stage), source=src.get("name") or "来源", origin=str(p),
                                  keep_unmatched=config.get("source_unmatched") == "keep"))
        self.imported += 1
        return str(stage)
