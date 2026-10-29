"""Windows 专用：开机自动运行（当前用户的注册表 Run 项）、右键「发送到 → 文渊」、开始菜单快捷方式、提示框。

在 Mac / Linux 上这些函数什么也不做（返回 None）。全部只写当前用户的设置，不需要管理员权限。
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from . import config

IS_WIN = sys.platform.startswith("win")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "文渊"
OLD_NAMES = ("归档官",)   # 改名前用过的名字：启动时把旧的启动项和快捷方式换掉
NO_WINDOW = 0x08000000


def pythonw() -> Path:
    """运行环境里不带命令行窗口的 Python。"""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def script(name: str) -> Path:
    return config.APP_DIR / "scripts" / name


def icon_file() -> Path:
    return config.APP_DIR / "static" / "icon.ico"


def tray_command() -> str:
    return f'"{pythonw()}" "{script("tray.pyw")}"'


# ---------------------------------------------------------------- 开机自动运行
def autostart_get() -> Optional[bool]:
    if not IS_WIN:
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            v, _ = winreg.QueryValueEx(k, RUN_NAME)
            return bool(v)
    except OSError:
        return False


def autostart_set(on: bool) -> Optional[bool]:
    if not IS_WIN:
        return None
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, tray_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass
    return autostart_get()


def autostart_refresh() -> None:
    """程序文件夹挪过位置后，开机启动项跟着更新。"""
    if IS_WIN and autostart_get():
        autostart_set(True)


# ---------------------------------------------------------------- 快捷方式
def _powershell(ps: str) -> bool:
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-EncodedCommand", enc], capture_output=True, stdin=subprocess.DEVNULL, timeout=30,
                           creationflags=NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def _q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _make_shortcut(lnk: Path, target: Path, args: str, desc: str) -> bool:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    ps = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_q(lnk)}); "
          f"$s.TargetPath = {_q(target)}; $s.Arguments = {_q(args)}; "
          f"$s.WorkingDirectory = {_q(config.APP_DIR)}; $s.IconLocation = {_q(str(icon_file()) + ',0')}; "
          f"$s.Description = {_q(desc)}; $s.Save()")
    return _powershell(ps) and lnk.exists()


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))


def sendto_link() -> Path:
    return _appdata() / "Microsoft" / "Windows" / "SendTo" / f"{RUN_NAME}.lnk"


def startmenu_link() -> Path:
    return _appdata() / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{RUN_NAME}.lnk"


def sendto_get() -> Optional[bool]:
    return sendto_link().exists() if IS_WIN else None


def sendto_set(on: bool) -> Optional[bool]:
    if not IS_WIN:
        return None
    if on:
        _make_shortcut(sendto_link(), pythonw(), f'"{script("sendto.pyw")}"', "发送到文渊：自动识别、重命名、归档")
    else:
        try:
            sendto_link().unlink()
        except OSError:
            pass
    return sendto_get()


def ensure_shortcuts() -> None:
    """启动时：按设置补上「发送到」和开始菜单里的快捷方式（程序挪过位置也会更新）。"""
    if not IS_WIN:
        return
    migrate_old_names()
    if config.get("sendto_enabled"):
        sendto_set(True)
    _make_shortcut(startmenu_link(), pythonw(), f'"{script("tray.pyw")}" --open', "文渊：项目文件智能归档")
    autostart_refresh()


def migrate_old_names() -> None:
    """改名前（归档官）留下的开机启动项、「发送到」和开始菜单快捷方式：删掉旧的，开机启动按新名字重新登记。"""
    import winreg
    had_autostart = False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
            for old in OLD_NAMES:
                try:
                    winreg.QueryValueEx(k, old)
                    winreg.DeleteValue(k, old)
                    had_autostart = True
                except OSError:
                    pass
    except OSError:
        pass
    if had_autostart:
        try:
            autostart_set(True)
        except OSError:
            pass
    base = _appdata() / "Microsoft" / "Windows"
    for old in OLD_NAMES:
        for lnk in (base / "SendTo" / f"{old}.lnk", base / "Start Menu" / "Programs" / f"{old}.lnk"):
            try:
                lnk.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------- 提示框
def message_box(text: str, title: str = "文渊", warn: bool = False) -> None:
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x30 if warn else 0x40)
            return
        except Exception:
            pass
    print(f"[{title}] {text}")
