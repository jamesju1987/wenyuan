#!/bin/bash
# 准备运行环境：找 Python 3.9+，建虚拟环境，安装依赖（先用清华镜像，失败再用官方源）
set -e
cd "$(dirname "$0")/.."

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "✗ 没有找到 Python 3.9 或以上版本。"
  echo "  请先安装 Python：https://www.python.org/downloads/macos/ （或在终端运行 xcode-select --install）"
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "· 首次运行：正在创建运行环境（使用 $PY）…"
  "$PY" -m venv .venv
fi

if ! cmp -s requirements.txt .venv/.installed 2>/dev/null; then
  echo "· 正在安装依赖，大约需要 1 分钟…"
  MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
  .venv/bin/python -m pip install -q --upgrade pip -i "$MIRROR" >/dev/null 2>&1 || true
  if ! .venv/bin/python -m pip install -q --retries 1 --timeout 20 -r requirements.txt -i "$MIRROR"; then
    echo "· 镜像安装失败，改用官方源重试…"
    .venv/bin/python -m pip install -q -r requirements.txt
  fi
  cp requirements.txt .venv/.installed
  echo "✓ 依赖安装完成"
fi

# 可选组件：装不上不影响启动，下次启动再试
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
install_optional() {   # $1 名称代号  $2 中文名  $3 大小  $4 额外的可选包
  local f="requirements-$1.txt" mark=".venv/.installed-$1"
  [ -f "$f" ] || return 0
  cmp -s "$f" "$mark" 2>/dev/null && return 0
  echo "· 正在安装$2（$3，只需一次）…"
  if .venv/bin/python -m pip install -q --retries 1 --timeout 30 -r "$f" -i "$MIRROR" \
     || .venv/bin/python -m pip install -q -r "$f"; then
    cp "$f" "$mark"
    [ -n "$4" ] && { .venv/bin/python -m pip install -q "$4" -i "$MIRROR" >/dev/null 2>&1 || true; }
    echo "✓ $2安装完成"
  else
    echo "! $2没装上（网络问题？），不影响其他功能，下次启动会再试"
  fi
}
install_optional ocr "图片文字识别组件" "约 100 MB" pillow-heif
install_optional archive "压缩包组件" "约 10 MB"
