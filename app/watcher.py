"""收件箱监听：文件系统事件 + 定时扫描兜底；等文件大小稳定后再交给流水线。"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import config
from .pipeline import Pipeline, Task, should_ignore

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
    HAS_WATCHDOG = True
except Exception:  # 没装 watchdog 时只用定时扫描
    HAS_WATCHDOG = False
    FileSystemEventHandler = object  # type: ignore


class _Handler(FileSystemEventHandler):  # type: ignore[misc]
    def __init__(self, w: "InboxWatcher"):
        self.w = w

    def on_created(self, event):
        if not event.is_directory:
            self.w.touch(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.w.touch(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.w.touch(event.dest_path)


class InboxWatcher:
    STABLE_SECONDS = 2.0
    RESCAN_SECONDS = 15.0

    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self.pending: Dict[str, Tuple[float, int]] = {}
        self.lock = threading.RLock()
        self.observer = None
        self.running = False
        self.path: Optional[Path] = None
        self._last_scan = 0.0
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------ 控制
    def start(self) -> None:
        self.stop()
        if not config.get("watch_enabled"):
            return
        config.ensure_system_dirs()
        self.path = config.inbox()
        self.running = True
        if HAS_WATCHDOG:
            try:
                self.observer = Observer()
                self.observer.schedule(_Handler(self), str(self.path), recursive=True)
                self.observer.start()
            except Exception:
                self.observer = None
        self._thread = threading.Thread(target=self._loop, name="inbox-watcher", daemon=True)
        self._thread.start()
        self.scan_now()

    def stop(self) -> None:
        self.running = False
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=3)
            except Exception:
                pass
            self.observer = None

    def status(self) -> Dict:
        return {"running": self.running, "path": str(self.path or config.inbox()),
                "mode": "实时监听" if self.observer else ("定时扫描" if self.running else "已暂停"),
                "pending": len(self.pending)}

    # ------------------------------------------------------------ 事件
    def touch(self, path: str) -> None:
        p = Path(path)
        if self._skip(p):
            return
        with self.lock:
            size = p.stat().st_size if p.exists() else -1
            self.pending[str(p)] = (time.time(), size)

    def _skip(self, p: Path) -> bool:
        if should_ignore(p):
            return True
        try:
            rel = p.relative_to(config.inbox())
        except ValueError:
            return True
        return any(part.startswith(".") for part in rel.parts)

    def scan_now(self) -> int:
        inbox = config.inbox()
        n = 0
        if not inbox.exists():
            return 0
        for dirpath, dirnames, filenames in os.walk(inbox):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                p = Path(dirpath) / fn
                if self._skip(p):
                    continue
                with self.lock:
                    if str(p) not in self.pending:
                        self.pending[str(p)] = (time.time() - self.STABLE_SECONDS, p.stat().st_size)
                        n += 1
        self._last_scan = time.time()
        return n

    def _loop(self) -> None:
        while self.running:
            time.sleep(1.0)
            try:
                if time.time() - self._last_scan > self.RESCAN_SECONDS:
                    self.scan_now()
                self._flush()
            except Exception:
                pass

    def _flush(self) -> None:
        now = time.time()
        ready = []
        with self.lock:
            for path, (t, size) in list(self.pending.items()):
                p = Path(path)
                if not p.exists():
                    self.pending.pop(path, None)
                    continue
                cur = p.stat().st_size
                if cur != size:
                    self.pending[path] = (now, cur)
                    continue
                if now - t >= self.STABLE_SECONDS:
                    ready.append(p)
                    self.pending.pop(path, None)
        inbox = config.inbox()
        for p in ready:
            rel = p.relative_to(inbox)
            batch_id = batch_label = None
            if len(rel.parts) > 1:
                batch_label = rel.parts[0]
                batch_id = f"inbox:{batch_label}"
            self.pipeline.submit(Task(path=str(p), source="收件箱", batch_id=batch_id,
                                      batch_label=batch_label or ""))
