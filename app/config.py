"""配置：保存在程序目录 data/settings.json，所有路径由此推导。"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Any, Dict

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"
DB_FILE = DATA_DIR / "guidang.db"

# 归档库根目录下的系统区（不属于任何客户）
INBOX_NAME = "_收件箱"
REVIEW_NAME = "_待复核"
UNMATCHED_NAME = "_未匹配"
DUPLICATE_NAME = "_重复文件"
TEMPLATE_NAME = "_公共模板"
ARCHIVE_KEEP_NAME = "_原始压缩包"
SYSTEM_DIRS = [INBOX_NAME, REVIEW_NAME, UNMATCHED_NAME, DUPLICATE_NAME, TEMPLATE_NAME, ARCHIVE_KEEP_NAME]

DEFAULTS: Dict[str, Any] = {
    "archive_root": str(Path.home() / "项目归档库"),
    "inbox_dir": "",                 # 留空 = 归档库下的 _收件箱
    "watch_enabled": True,
    "auto_threshold": 0.90,          # ≥ 该值自动归档
    "review_threshold": 0.60,        # < 该值进入 _未匹配
    "jev_enabled": False,
    "jev_api_key": "",
    "jev_endpoint": "https://api.typesafe.ai/v1/systemone",
    "jev_model": "jev-latest",
    "deepseek_enabled": False,
    "deepseek_api_key": "",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-v4-flash",
    "text_chars_for_ai": 1500,       # 发给模型的正文长度
    "recent_project_days": 90,       # 结项多少天内仍作为候选项目
    "history_enabled": True,         # 参考历史归档：相似文件沿用上次的项目和类型
    "learn_enabled": True,           # 人工确认后自动生成规则
    "learn_min_samples": 2,          # 同类文件人工确认几次后生成规则
    "ocr_enabled": True,             # 识别图片和扫描件里的文字（本地离线）
    "ocr_pdf_pages": 2,              # 扫描版 PDF 识别前几页
    "unpack_enabled": True,          # 压缩包自动解压后逐个归档
    "unpack_max_files": 30,          # 超过这么多文件的压缩包整体归档
    "keep_archives": True,           # 解压后原压缩包移到 _原始压缩包
    "archive_passwords": [],         # 记住的解压密码，自动尝试
    "sources": [],                   # 额外的文件来源（微信、企业微信、下载文件夹…），只复制不移动
    "source_unmatched": "ignore",    # 来源里认不出项目的文件：ignore 忽略 / keep 放进未匹配
    "sendto_enabled": True,          # Windows 右键「发送到 → 文渊」
    "sendto_move": False,            # 发送后移走原文件（默认复制，原文件不动）
    "notify_enabled": True,          # 托盘通知：自动归档了多少、多少需要复核
}

PREVIOUS_DATA = ""    # 这次启动沿用了哪里的旧数据（界面上提示一次）


def _marker() -> Path:
    """记住上一次用的数据文件夹在哪（放在用户目录，不随程序文件夹走）。"""
    if os.environ.get("GUIDANG_MARKER"):
        return Path(os.environ["GUIDANG_MARKER"])
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "文渊" / "data_dir.txt"


def _previous_data_dirs() -> list:
    """可能存着旧数据的地方：上次记下的位置（含改名前「归档官」记下的），以及放在旁边的旧程序文件夹。"""
    out = []
    m = _marker()
    for f in (m, m.parent.parent / "归档官" / m.name):
        try:
            if f.exists():
                out.append(Path(f.read_text("utf-8").strip()))
        except Exception:
            pass
    try:
        for sib in APP_DIR.parent.iterdir():
            if sib.is_dir() and sib != APP_DIR and (sib / "app" / "main.py").exists():
                out.append(sib / "data")
    except Exception:
        pass
    found = []
    for d in out:
        try:
            if (d / DB_FILE.name).exists() and d.resolve() != DATA_DIR.resolve() and d not in found:
                found.append(d)
        except Exception:
            continue
    return sorted(found, key=lambda d: (d / DB_FILE.name).stat().st_mtime, reverse=True)


def adopt_previous_data() -> str:
    """新版本解压到了另一个文件夹时，接着用上一次的数据库和设置。

    否则新程序从空数据库开始，重新导入 CRM 后客户编码会变，归档库里就会出现两套客户文件夹。
    只复制、不移动：旧文件夹里的数据原样保留。
    """
    global PREVIOUS_DATA
    marker = _marker()
    try:
        candidates = [] if DB_FILE.exists() else _previous_data_dirs()
        if candidates:
            old = candidates[0]
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            src = sqlite3.connect(str(old / DB_FILE.name))
            dst = sqlite3.connect(str(DB_FILE))
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            if (old / SETTINGS_FILE.name).exists() and not SETTINGS_FILE.exists():
                shutil.copy2(old / SETTINGS_FILE.name, SETTINGS_FILE)
            PREVIOUS_DATA = str(old)
            print(f"接着使用上一次的数据：{old}")
    except Exception as e:
        print("沿用上一次的数据失败：", e)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(DATA_DIR), "utf-8")
    except Exception:
        pass
    return PREVIOUS_DATA


_lock = threading.RLock()
_settings: Dict[str, Any] = {}


def load() -> Dict[str, Any]:
    global _settings
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = dict(DEFAULTS)
        if SETTINGS_FILE.exists():
            try:
                data.update(json.loads(SETTINGS_FILE.read_text("utf-8")))
            except Exception:
                pass
        _settings = data
        return dict(_settings)


def get(key: str) -> Any:
    if not _settings:
        load()
    return _settings.get(key, DEFAULTS.get(key))


def all_settings() -> Dict[str, Any]:
    if not _settings:
        load()
    return dict(_settings)


def update(changes: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        if not _settings:
            load()
        for k, v in changes.items():
            if k in DEFAULTS:
                _settings[k] = v
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_settings, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(SETTINGS_FILE)
        return dict(_settings)


def root() -> Path:
    return Path(str(get("archive_root"))).expanduser()


def inbox() -> Path:
    custom = str(get("inbox_dir") or "").strip()
    return Path(custom).expanduser() if custom else root() / INBOX_NAME


def review_dir() -> Path:
    return root() / REVIEW_NAME


def unmatched_dir() -> Path:
    return root() / UNMATCHED_NAME


def duplicate_dir() -> Path:
    return root() / DUPLICATE_NAME


def ensure_system_dirs() -> None:
    r = root()
    r.mkdir(parents=True, exist_ok=True)
    for name in SYSTEM_DIRS:
        (r / name).mkdir(exist_ok=True)
    inbox().mkdir(parents=True, exist_ok=True)
