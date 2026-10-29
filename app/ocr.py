"""本地图片文字识别：RapidOCR（ONNXRuntime，模型随安装包自带，完全离线，不上传任何内容）。

识别组件没装上时 ready() 返回 False，图片和扫描件照旧只按文件名判断，其他流程不受影响。
"""
from __future__ import annotations

import importlib.util
import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MAX_SIDE = 2000          # 手机照片通常 4000px，缩到 2000 识别率几乎不变、速度快一倍
MIN_SIDE = 80            # 小图标、头像之类不识别
MAX_BYTES = 40 * 1024 * 1024

_init_lock = threading.Lock()
_run_lock = threading.Lock()
_engine = None
_error: Optional[str] = None
_heif_done = False


_installed = False


def installed() -> bool:
    global _installed
    if not _installed:
        _installed = all(importlib.util.find_spec(m) is not None for m in ("rapidocr", "onnxruntime", "numpy", "PIL"))
    return _installed


def pdf_render_installed() -> bool:
    return importlib.util.find_spec("pypdfium2") is not None


def status() -> Dict:
    if not installed():
        return {"ready": False, "msg": "识别组件未安装：重新运行启动脚本会自动安装（约 100 MB，只需一次）"}
    if _error:
        return {"ready": False, "msg": f"识别组件加载失败：{_error}"}
    try:
        from importlib.metadata import version
        v = version("rapidocr")
    except Exception:
        v = ""
    extra = "" if pdf_render_installed() else "（缺少 pypdfium2，扫描版 PDF 暂不能识别）"
    return {"ready": True, "loaded": _engine is not None, "msg": f"RapidOCR {v} · 本地离线{extra}".strip()}


def ready() -> bool:
    return installed() and not _error


def _get():
    global _engine, _error
    if _engine is not None:
        return _engine
    with _init_lock:
        if _engine is None:
            try:
                logging.getLogger("RapidOCR").setLevel(logging.ERROR)
                from rapidocr import RapidOCR
                try:
                    _engine = RapidOCR(params={"Global.log_level": "error"})
                except TypeError:          # 旧版接口不接受 params
                    _engine = RapidOCR()
                logging.getLogger("RapidOCR").setLevel(logging.ERROR)
            except Exception as e:
                _error = str(e)[:160]
                raise
    return _engine


def _lines(result) -> List[str]:
    txts = getattr(result, "txts", None)
    if txts is None and isinstance(result, tuple) and result:   # 旧版返回 ([box, text, score], elapse)
        txts = [r[1] for r in (result[0] or [])]
    return [str(t).strip() for t in (txts or []) if t and str(t).strip()]


def _prepare(img):
    from PIL import Image, ImageOps

    try:
        img = ImageOps.exif_transpose(img)     # 手机竖拍的照片按实际方向识别
    except Exception:
        pass
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")   # 透明背景的截图垫白底，否则会变成黑底
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    s = MAX_SIDE / max(w, h)
    if s < 1:
        img = img.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    return img


def recognize(img) -> str:
    """识别一张 PIL 图片，按从上到下的顺序返回文字行。"""
    import numpy as np

    img = _prepare(img)
    engine = _get()
    with _run_lock:
        res = engine(np.asarray(img))
    return "\n".join(_lines(res))


def _enable_heif() -> None:
    global _heif_done
    if _heif_done:
        return
    _heif_done = True
    try:
        from pillow_heif import register_heif_opener   # iPhone 的 HEIC 照片（可选组件）
        register_heif_opener()
    except Exception:
        pass


def image_text(path: Path) -> Tuple[str, Tuple[int, int], float]:
    """返回 (文字, (宽, 高), 用时秒)。图片太小或太大时返回空文字。"""
    from PIL import Image, ImageOps

    _enable_heif()
    t0 = time.time()
    if path.stat().st_size > MAX_BYTES:
        return "", (0, 0), 0.0
    with Image.open(path) as im:
        try:
            im.seek(0)
        except Exception:
            pass
        im.load()
        try:
            size = ImageOps.exif_transpose(im).size
        except Exception:
            size = im.size
        if min(size) < MIN_SIDE:
            return "", size, 0.0
        text = recognize(im)
    return text, size, time.time() - t0


def pdf_text(path: Path, pages: int = 2, dpi: int = 150) -> Tuple[str, int, float]:
    """把扫描版 PDF 的前几页渲染成图片再识别。返回 (文字, 识别页数, 用时秒)。"""
    import pypdfium2 as pdfium

    t0 = time.time()
    doc = pdfium.PdfDocument(str(path))
    parts: List[str] = []
    n = 0
    try:
        for i in range(min(max(1, pages), len(doc))):
            page = doc[i]
            try:
                img = page.render(scale=dpi / 72).to_pil()
                parts.append(recognize(img))
                n += 1
            finally:
                page.close()
    finally:
        doc.close()
    return "\n".join(p for p in parts if p), n, time.time() - t0


def self_test() -> Dict:
    """设置页「测试识别」：画一张带字的图识别一下，顺便预热模型。"""
    from PIL import Image, ImageDraw, ImageFont

    t0 = time.time()
    img = Image.new("RGB", (900, 200), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=56)
    except TypeError:
        font = ImageFont.load_default()
    d.text((40, 60), "OCR TEST 2026-10", fill="black", font=font)
    text = recognize(img)
    return {"ok": "2026" in text or "OCR" in text.upper(), "text": text, "ms": int((time.time() - t0) * 1000)}
