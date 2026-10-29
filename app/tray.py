"""Windows 托盘：文渊在后台运行（没有黑色命令行窗口），右下角图标 + 菜单 + 处理完成通知。

启动方式：pythonw scripts/tray.pyw [--open]
- 已经有同版本在运行：只打开界面。
- 旧版本在运行：请它退出再启动新版本（升级时不用手动找进程）。
- 没装托盘组件（pystray）：照样在后台运行，用网页设置里的「退出文渊」关闭。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Dict, Optional

from . import __version__, config, winsys

PORT = int(os.environ.get("GUIDANG_PORT", "8790"))
BASE = f"http://127.0.0.1:{PORT}"
HDR = {"X-Guidang": "1", "Content-Type": "application/json"}


def _get(path: str, timeout: float = 1.5) -> Optional[Dict]:
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + path, headers=HDR), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _post(path: str, data: Optional[Dict] = None, timeout: float = 5) -> Optional[Dict]:
    try:
        req = urllib.request.Request(BASE + path, data=json.dumps(data or {}).encode(), headers=HDR, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except Exception:
        return None


def _log_to_file() -> None:
    """pythonw 没有控制台，输出写到 data/server.log。"""
    if sys.stdout is None or Path(sys.executable).name.lower().startswith("pythonw"):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        f = open(config.DATA_DIR / "server.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = f
        print(f"\n==== 文渊 {__version__} 启动 {time.strftime('%Y-%m-%d %H:%M:%S')} ====")


def _icon_image(paused: bool = False):
    from PIL import Image, ImageOps

    p = config.APP_DIR / "static" / "tray.png"
    img = Image.open(p).convert("RGBA") if p.exists() else Image.new("RGBA", (64, 64), (0, 122, 255, 255))
    if paused:
        alpha = img.getchannel("A")
        img = ImageOps.grayscale(img).convert("RGBA")
        img.putalpha(alpha.point(lambda a: int(a * 0.75)))
    return img


class Notifier:
    """把一阵子内的处理结果攒成一条通知：「自动归档 3 个文件，2 个需要复核」。"""

    QUIET = 6.0

    def __init__(self):
        self.base: Optional[Dict] = None
        self.acc_auto = self.acc_pending = 0
        self.last_change = 0.0

    def feed(self, st: Dict) -> Optional[str]:
        c = st.get("counts") or {}
        cur = {"auto": int(c.get("today_auto") or 0), "pending": int(c.get("review") or 0) + int(c.get("unmatched") or 0)}
        if self.base is None:
            self.base = cur
            return None
        d_auto = cur["auto"] - self.base["auto"]
        d_pend = cur["pending"] - self.base["pending"]
        if d_auto < 0:                      # 过了零点，今天的计数归零
            d_auto = 0
        if d_auto > 0 or d_pend > 0:
            self.acc_auto += max(0, d_auto)
            self.acc_pending += max(0, d_pend)
            self.last_change = time.time()
        self.base = cur
        busy = int(st.get("queue") or 0) > 0
        if (self.acc_auto or self.acc_pending) and not busy and time.time() - self.last_change >= self.QUIET:
            parts = []
            if self.acc_auto:
                parts.append(f"自动归档了 {self.acc_auto} 个文件")
            if self.acc_pending:
                parts.append(f"{self.acc_pending} 个需要复核")
            self.acc_auto = self.acc_pending = 0
            return "，".join(parts)
        return None


def _open_ui() -> None:
    webbrowser.open(BASE)


def _replace_old(st: Dict) -> bool:
    """端口上已经有文渊：同版本就只打开界面；旧版本就请它退出。返回 True 表示可以继续启动。"""
    if st.get("version") == __version__:
        return False
    _post("/api/quit")
    for _ in range(60):
        time.sleep(0.25)
        if _get("/api/state", timeout=0.5) is None:
            time.sleep(0.5)
            return True
    winsys.message_box(f"旧版本的文渊（{st.get('version')}）还在运行。\n\n请先关闭原来的文渊窗口（黑色命令行窗口），再重新启动。",
                       warn=True)
    return False


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    want_open = "--open" in argv
    config.load()
    _log_to_file()

    st = _get("/api/state")
    if st is not None:
        if not _replace_old(st):
            if want_open:
                _open_ui()
            return

    import uvicorn
    from . import main as appmain

    server = uvicorn.Server(uvicorn.Config(appmain.app, host="127.0.0.1", port=PORT, log_level="warning"))
    t = threading.Thread(target=server.run, name="server", daemon=True)
    t.start()
    for _ in range(160):
        if server.started or not t.is_alive():
            break
        time.sleep(0.25)
    if not server.started:
        winsys.message_box(f"文渊没能启动：端口 {PORT} 可能被别的程序占用了。\n详细信息见 data/server.log", warn=True)
        return
    print(f"已启动：{BASE}  归档库：{config.root()}")
    if want_open:
        _open_ui()
    threading.Thread(target=winsys.ensure_shortcuts, name="shortcuts", daemon=True).start()

    try:
        import pystray
    except Exception:
        appmain.QUIT_HOOK = lambda: setattr(server, "should_exit", True)
        t.join()
        return

    stop = threading.Event()

    def quit_all(*_):
        stop.set()
        server.should_exit = True
        try:
            icon.stop()
        except Exception:
            pass

    appmain.QUIT_HOOK = quit_all

    def toggle_pause(*_):
        _post("/api/settings", {"watch_enabled": not config.get("watch_enabled")})
        refresh()

    def toggle_autostart(*_):
        try:
            winsys.autostart_set(not winsys.autostart_get())
        except Exception as e:
            winsys.message_box(f"设置开机自动运行失败：{e}", warn=True)

    def open_inbox(*_):
        try:
            os.startfile(str(config.inbox()))      # type: ignore[attr-defined]
        except Exception:
            webbrowser.open(config.inbox().as_uri())

    menu = pystray.Menu(
        pystray.MenuItem("打开文渊", lambda *_: _open_ui(), default=True),
        pystray.MenuItem("打开收件箱", open_inbox),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("暂停自动整理", toggle_pause, checked=lambda _: not config.get("watch_enabled")),
        pystray.MenuItem("开机自动运行", toggle_autostart, checked=lambda _: bool(winsys.autostart_get()),
                         visible=winsys.IS_WIN),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出文渊", quit_all),
    )
    icon = pystray.Icon("guidang", _icon_image(), f"文渊 {__version__}", menu)
    notifier = Notifier()
    state = {"paused": None}

    def refresh(st: Optional[Dict] = None):
        st = st or _get("/api/state") or {}
        paused = not config.get("watch_enabled")
        c = st.get("counts") or {}
        todo = int(c.get("review") or 0) + int(c.get("unmatched") or 0)
        icon.title = f"文渊 · {'已暂停自动整理' if paused else ('待复核 ' + str(todo) if todo else '运行中')}"
        if paused != state["paused"]:
            icon.icon = _icon_image(paused)
            state["paused"] = paused
        icon.update_menu()

    def poll():
        while not stop.wait(4.0):
            st = _get("/api/state")
            if not st:
                continue
            try:
                refresh(st)
                msg = notifier.feed(st)
                if msg and config.get("notify_enabled"):
                    icon.notify(msg, "文渊")
            except Exception as e:
                print("托盘刷新失败：", e)

    def setup(ic):
        ic.visible = True
        refresh()
        threading.Thread(target=poll, name="tray-poll", daemon=True).start()

    try:
        icon.run(setup=setup)
    except Exception as e:                    # 托盘出问题也不影响后台服务，照常运行
        print("托盘图标启动失败，继续在后台运行：", repr(e))
        stop.wait()
    stop.set()
    server.should_exit = True
    t.join(timeout=8)


if __name__ == "__main__":
    main()
