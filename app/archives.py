"""压缩包：zip（含 Windows 中文文件名、加密包）、7z、tar 系列、rar（借助本机已装的 7-Zip / WinRAR / tar）。

两种处理方式（设置里选）：
- 整包归档（默认）：peek() 只解出里面几份有代表性的文档读一读，判断项目和类型，整个压缩包按规范改名归档。
- 解压后逐个归档：unpack() 全部解开，每个文件单独识别。规则：
- 文件不多（默认 ≤ 30 个）的资料包：解压后逐个识别归档。
- 扫描结果包、日志包、文件很多的包：不拆，整体当一个文件归档（卡片上可以手动「解压后逐个归档」）。
- 加密包：先试记住的密码，不行就在待复核卡片上输入密码。
- 防压缩炸弹：最多 500 个文件、解压后最多 2 GB；路径只能落在目标文件夹里。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

MAX_FILES = 500
MAX_TOTAL = 2 * 1024 ** 3

_SUFFIXES = ((".tar.gz", "tar"), (".tar.bz2", "tar"), (".tar.xz", "tar"), (".tgz", "tar"), (".tbz2", "tar"),
             (".txz", "tar"), (".tar", "tar"), (".zip", "zip"), (".7z", "7z"), (".rar", "rar"))
_JUNK_PART = re.compile(r"^(__MACOSX|\.DS_Store|Thumbs\.db|desktop\.ini|\._.*|~\$.*|\.git|\.svn)$", re.I)
# 名字像扫描结果/日志/证据包的，整体归档
EVIDENCE_NAME = re.compile(r"扫描结果|漏扫|原始数据|原始结果|日志|证据|截图|nessus|awvs|xray|appscan|rsas|nmap|burp|"
                           r"pcap|\blogs?\b|\bscan", re.I)
MACHINE_EXT = {".html", ".htm", ".xml", ".json", ".csv", ".nessus", ".log", ".txt", ".pcap", ".pcapng", ".js", ".css",
               ".har", ".db", ".sqlite"}


class ArchiveError(Exception):
    pass


class NeedPassword(ArchiveError):
    pass


@dataclass
class Result:
    status: str                      # ok（已解压）| whole（整体归档）| password（需要密码）| error
    files: List[Path] = field(default_factory=list)
    count: int = 0
    reason: str = ""
    password: Optional[str] = None
    kind: str = ""


def kind_of(path: Path) -> str:
    n = path.name.lower()
    for suf, k in _SUFFIXES:
        if n.endswith(suf):
            return k
    return ""


def stem_of(path: Path) -> str:
    n = path.name
    for suf, _ in _SUFFIXES:
        if n.lower().endswith(suf):
            return n[: -len(suf)] or "压缩包"
    return path.stem


def _safe_rel(name: str) -> Optional[str]:
    """压缩包里的路径 → 安全的相对路径；跳过 ../ 越界、系统垃圾文件。"""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    if any(_JUNK_PART.match(p) for p in parts):
        return None
    clean = []
    for p in parts:
        p = re.sub(r'[<>:"|?*\x00-\x1f]', "_", p).rstrip(" .")
        clean.append(p or "_")
    return "/".join(clean)


def _zip_name(zi: zipfile.ZipInfo) -> str:
    """Windows 压缩软件默认用 GBK 存中文文件名，又不打 UTF-8 标记，Python 会按 cp437 解成乱码，这里还原。"""
    n = zi.filename
    if zi.flag_bits & 0x800:
        return n
    try:
        raw = n.encode("cp437")
    except UnicodeEncodeError:
        return n
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return n


def _pw_variants(pw: Optional[str]) -> List[Optional[bytes]]:
    if pw is None:
        return [None]
    out = []
    for enc in ("utf-8", "gbk"):
        try:
            b = pw.encode(enc)
        except UnicodeEncodeError:
            continue
        if b not in out:
            out.append(b)
    return out


def _creationflags() -> int:
    return 0x08000000 if sys.platform.startswith("win") else 0   # CREATE_NO_WINDOW


# ---------------------------------------------------------------- zip
def _zip_open(path: Path):
    try:
        import pyzipper  # 支持 AES 加密的 zip（WinRAR、7-Zip 的「AES-256」）
        return pyzipper.AESZipFile(str(path))
    except ImportError:
        return zipfile.ZipFile(str(path))


def _zip_members(zf) -> List[Tuple[zipfile.ZipInfo, str]]:
    out = []
    for zi in zf.infolist():
        if zi.is_dir():
            continue
        rel = _safe_rel(_zip_name(zi))
        if rel:
            out.append((zi, rel))
    return out


def _zip_check_password(zf, members, passwords: Sequence[Optional[str]]) -> Tuple[Optional[str], Optional[bytes]]:
    enc = [zi for zi, _ in members if zi.flag_bits & 0x1]
    if not enc:
        return None, None
    probe = min(enc, key=lambda z: z.file_size)
    for pw in passwords:
        for b in _pw_variants(pw):
            if b is None:
                continue
            try:
                with zf.open(probe, pwd=b) as f:
                    while f.read(1 << 20):
                        pass
                return pw, b
            except NotImplementedError:
                raise ArchiveError("这个 zip 用了 AES 加密，需要可选组件 pyzipper（重新运行启动脚本会自动安装）或本机安装 7-Zip")
            except Exception:
                continue
    raise NeedPassword("压缩包有密码")


def _zip_extract(path: Path, dest: Path, passwords, max_files: int, force: bool) -> Result:
    with _zip_open(path) as zf:
        members = _zip_members(zf)
        r = _precheck(path, [(rel, zi.file_size) for zi, rel in members], max_files, force)
        if r:
            return r
        pw, pwb = _zip_check_password(zf, members, passwords)
        files, total = [], 0
        for zi, rel in members:
            out = _target(dest, rel)
            with zf.open(zi, pwd=pwb) as fsrc, open(out, "wb") as fdst:
                total += _copy_limited(fsrc, fdst, total)
            files.append(out)
        return Result("ok", files, len(files), password=pw, kind="zip")


# ---------------------------------------------------------------- tar
def _tar_extract(path: Path, dest: Path, max_files: int, force: bool) -> Result:
    with tarfile.open(str(path), "r:*") as tf:
        members = [(m, _safe_rel(m.name)) for m in tf.getmembers() if m.isfile()]
        members = [(m, rel) for m, rel in members if rel]
        r = _precheck(path, [(rel, m.size) for m, rel in members], max_files, force)
        if r:
            return r
        files, total = [], 0
        for m, rel in members:
            src = tf.extractfile(m)
            if src is None:
                continue
            out = _target(dest, rel)
            with src, open(out, "wb") as fdst:
                total += _copy_limited(src, fdst, total)
            files.append(out)
        return Result("ok", files, len(files), kind="tar")


# ---------------------------------------------------------------- 7z
def _7z_extract(path: Path, dest: Path, passwords, max_files: int, force: bool) -> Result:
    try:
        import py7zr
    except ImportError:
        if _external_tool():
            return _external_extract(path, dest, passwords, max_files, force, "7z")
        raise ArchiveError("解压 7z 需要可选组件 py7zr（重新运行启动脚本会自动安装）或本机安装 7-Zip")
    for pw in passwords:
        try:
            z = py7zr.SevenZipFile(str(path), mode="r", password=pw)
        except Exception:
            if pw is None:          # 文件名也加密了：没密码打不开
                continue
            continue                # 密码不对
        with z:
            encrypted = z.needs_password()
            if encrypted and pw is None:
                continue
            infos = [(i, _safe_rel(i.filename)) for i in z.list() if not i.is_directory]
            infos = [(i, rel) for i, rel in infos if rel]
            r = _precheck(path, [(rel, int(i.uncompressed or 0)) for i, rel in infos], max_files, force)
            if r:
                return r
        tmp = Path(tempfile.mkdtemp(dir=str(dest.parent), prefix=".7z-"))
        try:
            with py7zr.SevenZipFile(str(path), mode="r", password=pw) as z:
                z.extractall(path=str(tmp))
            files = _collect(tmp, dest, max_files)
            return Result("ok", files, len(files), password=pw, kind="7z")
        except Exception as e:
            if encrypted:
                continue            # 密码不对时 py7zr 抛各种解码/校验错误
            raise ArchiveError(f"7z 解压失败：{e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    raise NeedPassword("压缩包有密码")


# ---------------------------------------------------------------- rar（外部工具）
def _external_tool() -> Optional[Tuple[str, str]]:
    """本机已有的解压工具：7-Zip > WinRAR > 系统 tar（Windows 11 / macOS 自带，能解大部分 rar，但不支持密码）。"""
    cands: List[Tuple[str, str]] = []
    if sys.platform.startswith("win"):
        for base in filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                                  os.environ.get("ProgramW6432"))):
            cands += [(str(Path(base) / "7-Zip" / "7z.exe"), "7z"), (str(Path(base) / "WinRAR" / "UnRAR.exe"), "unrar")]
        cands.append((str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"), "tar"))
    else:
        for exe, k in (("7zz", "7z"), ("7z", "7z"), ("unrar", "unrar"), ("bsdtar", "tar")):
            w = shutil.which(exe)
            if w:
                cands.append((w, k))
    for exe, k in cands:
        if Path(exe).exists():
            return exe, k
    return None


def _external_extract(path: Path, dest: Path, passwords, max_files: int, force: bool, kind: str) -> Result:
    tool = _external_tool()
    if not tool:
        raise ArchiveError("本机没有能解压 rar 的工具：安装 7-Zip（免费）后即可自动解压")
    exe, k = tool
    for pw in passwords:
        with tempfile.TemporaryDirectory(dir=str(dest.parent)) as tmp:
            if k == "7z":
                cmd = [exe, "x", "-y", f"-o{tmp}", f"-p{pw or ''}", str(path)]
            elif k == "unrar":
                cmd = [exe, "x", "-y", f"-p{pw}" if pw else "-p-", str(path), tmp + os.sep]
            else:
                if pw:
                    raise ArchiveError("系统自带的 tar 不支持带密码的 rar：安装 7-Zip（免费）后再试")
                cmd = [exe, "-xf", str(path), "-C", tmp]
            try:
                res = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=600,
                                     creationflags=_creationflags())
            except subprocess.TimeoutExpired:
                raise ArchiveError("解压超时")
            out = (res.stdout + res.stderr).decode("utf-8", "ignore") + (res.stdout + res.stderr).decode("gbk", "ignore")
            if res.returncode != 0:
                if re.search(r"password|encrypt|密码", out, re.I):
                    if k == "tar":
                        raise ArchiveError("压缩包有密码，系统自带的 tar 解不了：安装 7-Zip（免费）后再试")
                    continue
                raise ArchiveError(f"解压失败（{Path(exe).name}）：{out.strip()[:120]}")
            tmpp = Path(tmp)
            listing = [(str(p.relative_to(tmpp)), p.stat().st_size) for p in tmpp.rglob("*") if p.is_file()]
            r = _precheck(path, [(n, s) for n, s in listing if _safe_rel(n)], max_files, force)
            if r:
                return r
            files = _collect(tmpp, dest, max_files)
            return Result("ok", files, len(files), password=pw, kind=kind)
    raise NeedPassword("压缩包有密码")


# ---------------------------------------------------------------- 公共
def _target(dest: Path, rel: str) -> Path:
    out = dest.joinpath(*rel.split("/"))
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        from .naming import unique_path
        out = unique_path(out)
    return out


def _copy_limited(fsrc, fdst, already: int) -> int:
    n = 0
    while True:
        chunk = fsrc.read(1 << 20)
        if not chunk:
            return n
        n += len(chunk)
        if already + n > MAX_TOTAL:
            raise ArchiveError("解压后超过 2 GB，已停止")
        fdst.write(chunk)


def _collect(tmp: Path, dest: Path, max_files: int) -> List[Path]:
    files = []
    for p in sorted(tmp.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        rel = _safe_rel(str(p.relative_to(tmp)))
        if not rel:
            continue
        out = _target(dest, rel)
        shutil.move(str(p), str(out))
        files.append(out)
    return files


def _precheck(path: Path, entries: List[Tuple[str, int]], max_files: int, force: bool) -> Optional[Result]:
    """决定拆还是不拆。返回 None 表示继续解压。"""
    n = len(entries)
    total = sum(max(0, s) for _, s in entries)
    if n == 0:
        return Result("whole", count=0, reason="压缩包是空的")
    if n > MAX_FILES or total > MAX_TOTAL:
        return Result("whole", count=n, reason=f"压缩包里有 {n} 个文件，太大不自动解压，整体归档")
    if force:
        return None
    machine = sum(1 for name, _ in entries if Path(name).suffix.lower() in MACHINE_EXT)
    if EVIDENCE_NAME.search(stem_of(path)) or (n > 10 and machine >= n * 0.6):
        return Result("whole", count=n, reason=f"像扫描结果/日志包（{n} 个文件），整体归档")
    if n > max_files:
        return Result("whole", count=n, reason=f"压缩包里有 {n} 个文件，超过 {max_files} 个，整体归档")
    return None


def suffix_of(path: Path) -> str:
    """压缩包的完整后缀（.tar.gz 这类双后缀不丢），改名归档时用。"""
    n = path.name.lower()
    for suf, _ in _SUFFIXES:
        if n.endswith(suf):
            return path.name[-len(suf):]
    return path.suffix


# ---------------------------------------------------------------- 只看不拆（整包归档时用）
DOC_RANK = {".docx": 0, ".pdf": 1, ".pptx": 2, ".xlsx": 3, ".xlsm": 3, ".doc": 4, ".md": 5, ".txt": 6}
PEEK_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
PEEK_MAX_DOC = 30 * 1024 ** 2
PEEK_MAX_EXTERNAL = 300 * 1024 ** 2    # rar 等要靠外部工具整体解开才能看，太大就只看名字


@dataclass
class Peek:
    status: str                       # ok | password（有密码，只拿到文件名或什么都没拿到）| error | empty
    names: List[str] = field(default_factory=list)            # 里面所有文件的相对路径
    files: List[Tuple[str, Path]] = field(default_factory=list)  # 解出来读的几份：(相对路径, 临时文件)
    reason: str = ""
    password: Optional[str] = None
    kind: str = ""
    sizes: dict = field(default_factory=dict)                 # 相对路径 → 解压后大小


def pick_for_peek(entries: Sequence[Tuple[str, int]], limit: int = 3) -> List[str]:
    """挑几份最能说明问题的：文档优先（docx > pdf > pptx > xlsx …），浅层目录、内容多的优先；没有文档时挑一张图片。"""
    docs = [(n, s) for n, s in entries if Path(n).suffix.lower() in DOC_RANK and 0 < s <= PEEK_MAX_DOC]
    docs.sort(key=lambda e: (DOC_RANK[Path(e[0]).suffix.lower()], e[0].count("/"), -e[1]))
    out = [n for n, _ in docs[:limit]]
    if not out:
        imgs = [(n, s) for n, s in entries if Path(n).suffix.lower() in PEEK_IMAGE_EXT and 0 < s <= 15 * 1024 ** 2]
        imgs.sort(key=lambda e: (e[0].count("/"), -e[1]))
        out = [n for n, _ in imgs[:1]]
    return out


def peek(path: Path, dest: Path, passwords: Sequence[str] = (), limit: int = 3) -> Peek:
    """列出压缩包里的文件，并把挑中的几份解到 dest（临时目录，用完由调用方删）。不改动压缩包本身。"""
    k = kind_of(path)
    if not k:
        return Peek("error", reason="不是压缩包")
    tries: List[Optional[str]] = [None] + [p for p in passwords if p]
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if k == "zip":
            try:
                return _zip_peek(path, dest, tries, limit)
            except ArchiveError as e:
                tool = _external_tool()
                if "AES" not in str(e) or not tool or tool[1] != "7z":
                    raise
                return _external_peek(path, dest, tries, limit, "zip")
        if k == "tar":
            return _tar_peek(path, dest, limit)
        if k == "7z":
            try:
                import py7zr  # noqa: F401
                return _7z_peek(path, dest, tries, limit)
            except ImportError:
                return _external_peek(path, dest, tries, limit, "7z")
        return _external_peek(path, dest, tries, limit, "rar")
    except NeedPassword as e:
        return Peek("password", reason=str(e), kind=k)
    except (ArchiveError, zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as e:
        return Peek("error", reason=str(e) or type(e).__name__, kind=k)


def _zip_peek(path: Path, dest: Path, tries, limit: int) -> Peek:
    with _zip_open(path) as zf:
        members = _zip_members(zf)
        names = [rel for _, rel in members]
        if not members:
            return Peek("empty", reason="压缩包是空的", kind="zip")
        try:
            pw, pwb = _zip_check_password(zf, members, tries)
        except NeedPassword:
            # zip 加密的只是内容，文件名还能看到，先拿文件名判断
            return Peek("password", names=names, reason="压缩包有密码，只看了里面的文件名", kind="zip",
                        sizes={rel: zi.file_size for zi, rel in members})
        by_rel = {rel: zi for zi, rel in members}
        files = []
        for rel in pick_for_peek([(rel, zi.file_size) for zi, rel in members], limit):
            out = _target(dest, rel)
            with zf.open(by_rel[rel], pwd=pwb) as fsrc, open(out, "wb") as fdst:
                _copy_limited(fsrc, fdst, 0)
            files.append((rel, out))
        return Peek("ok", names, files, password=pw, kind="zip", sizes={rel: zi.file_size for zi, rel in members})


def _tar_peek(path: Path, dest: Path, limit: int) -> Peek:
    with tarfile.open(str(path), "r:*") as tf:
        members = [(m, _safe_rel(m.name)) for m in tf.getmembers() if m.isfile()]
        members = [(m, rel) for m, rel in members if rel]
        if not members:
            return Peek("empty", reason="压缩包是空的", kind="tar")
        by_rel = {rel: m for m, rel in members}
        files = []
        for rel in pick_for_peek([(rel, m.size) for m, rel in members], limit):
            src = tf.extractfile(by_rel[rel])
            if src is None:
                continue
            out = _target(dest, rel)
            with src, open(out, "wb") as fdst:
                _copy_limited(src, fdst, 0)
            files.append((rel, out))
        return Peek("ok", [rel for _, rel in members], files, kind="tar", sizes={rel: m.size for m, rel in members})


def _7z_peek(path: Path, dest: Path, tries, limit: int) -> Peek:
    import py7zr
    seen: List[str] = []
    for pw in tries:
        try:
            with py7zr.SevenZipFile(str(path), mode="r", password=pw) as z:
                encrypted = z.needs_password()
                infos = [(i.filename, _safe_rel(i.filename), int(i.uncompressed or 0)) for i in z.list() if not i.is_directory]
        except Exception:
            continue                          # 文件名也加密了：没有密码打不开
        infos = [(raw, rel, size) for raw, rel, size in infos if rel]
        if not infos:
            return Peek("empty", reason="压缩包是空的", kind="7z")
        names = [rel for _, rel, _ in infos]
        sizes = {rel: size for _, rel, size in infos}
        seen = seen or names
        if encrypted and pw is None:
            if len(tries) == 1:
                return Peek("password", names=names, reason="压缩包有密码，只看了里面的文件名", kind="7z", sizes=sizes)
            continue
        pick = pick_for_peek([(rel, size) for _, rel, size in infos], limit)
        raw_of = {rel: raw for raw, rel, _ in infos}
        tmp = Path(tempfile.mkdtemp(dir=str(dest), prefix=".7z-"))
        try:
            with py7zr.SevenZipFile(str(path), mode="r", password=pw) as z:
                z.extract(path=str(tmp), targets=[raw_of[r] for r in pick])
            files = []
            for rel in pick:
                p = tmp.joinpath(*raw_of[rel].replace("\\", "/").split("/"))
                if p.is_file():
                    out = _target(dest, rel)
                    shutil.move(str(p), str(out))
                    files.append((rel, out))
            return Peek("ok", names, files, password=pw, kind="7z", sizes=sizes)
        except Exception:
            if encrypted:
                continue                      # 密码不对
            return Peek("ok", names, [], reason="里面的文件没能读出来，只看了文件名", kind="7z")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if seen:
        return Peek("password", names=seen, reason="压缩包有密码，只看了里面的文件名", kind="7z")
    raise NeedPassword("压缩包有密码")


def _external_peek(path: Path, dest: Path, tries, limit: int, kind: str) -> Peek:
    """rar 等：外部工具没有统一的列目录格式，整体解到临时目录再挑（太大的只按名字判断）。"""
    if path.stat().st_size > PEEK_MAX_EXTERNAL:
        return Peek("error", reason="压缩包太大，没有打开看内容", kind=kind)
    full = dest / ".all"
    r = _external_extract(path, full, tries, MAX_FILES, True, kind)
    if r.status != "ok":
        return Peek("empty" if r.count == 0 else "error", reason=r.reason, kind=kind)
    entries = [(str(p.relative_to(full)).replace("\\", "/"), p.stat().st_size) for p in r.files]
    by_rel = dict(zip([e[0] for e in entries], r.files))
    files = [(rel, by_rel[rel]) for rel in pick_for_peek(entries, limit)]
    return Peek("ok", [e[0] for e in entries], files, password=r.password, kind=kind, sizes=dict(entries))


def unpack(path: Path, dest: Path, passwords: Sequence[str] = (), max_files: int = 30, force: bool = False) -> Result:
    """解压到 dest。passwords：依次尝试的密码（不含空密码，会先试不带密码）。"""
    k = kind_of(path)
    if not k:
        return Result("error", reason="不是压缩包")
    tries: List[Optional[str]] = [None] + [p for p in passwords if p]
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if k == "zip":
            try:
                r = _zip_extract(path, dest, tries, max_files, force)
            except ArchiveError as e:      # AES 加密的 zip 又没装 pyzipper：有 7-Zip 就交给它
                tool = _external_tool()
                if "AES" not in str(e) or not tool or tool[1] != "7z":
                    raise
                r = _external_extract(path, dest, tries, max_files, force, "zip")
        elif k == "tar":
            r = _tar_extract(path, dest, max_files, force)
        elif k == "7z":
            r = _7z_extract(path, dest, tries, max_files, force)
        else:
            r = _external_extract(path, dest, tries, max_files, force, "rar")
    except NeedPassword as e:
        _rm_empty(dest)
        return Result("password", reason=str(e), kind=k)
    except (ArchiveError, zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as e:
        shutil.rmtree(dest, ignore_errors=True)
        return Result("error", reason=str(e) or type(e).__name__, kind=k)
    r.kind = r.kind or k
    if r.status != "ok":
        _rm_empty(dest)
    return r


def _rm_empty(d: Path) -> None:
    try:
        if d.exists() and not any(d.rglob("*")):
            shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass
