"""右键「发送到 → 文渊」：把选中的文件/文件夹交给文渊。

文渊没在运行时先在后台启动它；实在启动不了，就直接复制进收件箱，下次启动时处理。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List

from . import config, naming, tray, winsys


def _start_server() -> bool:
    flags = 0x00000008 | 0x08000000 if winsys.IS_WIN else 0      # DETACHED_PROCESS | CREATE_NO_WINDOW
    try:
        subprocess.Popen([str(winsys.pythonw()), str(winsys.script("tray.pyw"))], cwd=str(config.APP_DIR),
                         creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    for _ in range(80):
        time.sleep(0.25)
        if tray._get("/api/state", timeout=0.5):
            return True
    return False


def _fallback_copy(paths: List[Path]) -> int:
    config.ensure_system_dirs()
    n = 0
    for p in paths:
        dst = naming.unique_path(config.inbox() / p.name)
        if p.is_dir():
            shutil.copytree(str(p), str(dst))
        else:
            shutil.copy2(str(p), str(dst))
        n += 1
    return n


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    config.load()
    paths = [Path(a) for a in argv if a and os.path.exists(a)]
    if not paths:
        return
    if tray._get("/api/state") is None and not _start_server():
        n = _fallback_copy(paths)
        winsys.message_box(f"文渊没能启动，已把 {n} 项放进收件箱，下次启动时自动处理。")
        return
    r = tray._post("/api/ingest", {"paths": [str(p) for p in paths], "source": "右键发送"}, timeout=120)
    if r is None:
        winsys.message_box("发送失败：文渊没有响应。可以把文件直接拖进收件箱。", warn=True)
    elif r.get("skipped") and not r.get("accepted"):
        winsys.message_box("\n".join(r["skipped"][:8]))


if __name__ == "__main__":
    main()
