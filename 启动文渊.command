#!/bin/bash
# 双击启动文渊：准备环境 → 启动服务 → 自动打开浏览器。关闭此窗口即退出。
cd "$(dirname "$0")"
PORT="${GUIDANG_PORT:-8790}"
URL="http://127.0.0.1:$PORT"

LABEL="com.guidang.archiver"
if curl -s -o /dev/null "$URL/api/state"; then
  RUNNING="$(curl -s "$URL/api/state" | sed -n 's/.*"version":"\([^"]*\)".*/\1/p')"
  LOCAL="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' app/__init__.py)"
  if [ -n "$LOCAL" ] && [ "$RUNNING" != "$LOCAL" ]; then
    if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
      echo "· 后台正在运行旧版本 $RUNNING，正在升级到 $LOCAL…"
      bash scripts/setup.sh || true
      launchctl kickstart -k "gui/$(id -u)/$LABEL"
      for i in $(seq 1 30); do sleep 0.5; curl -s -o /dev/null "$URL/api/state" && break; done
      echo "✓ 已升级并重启"
    else
      echo "旧版本 $RUNNING 还在运行。请先关闭原来的文渊窗口，再双击本文件。"
      read -n 1 -s -r -p "按任意键关闭窗口…"
      exit 1
    fi
  else
    echo "文渊已经在运行，正在打开 $URL"
  fi
  open "$URL"
  exit 0
fi

if ! bash scripts/setup.sh; then
  echo
  read -n 1 -s -r -p "按任意键关闭窗口…"
  exit 1
fi

( for i in $(seq 1 30); do
    if curl -s -o /dev/null "$URL/api/state"; then open "$URL"; break; fi
    sleep 0.5
  done ) &

exec .venv/bin/python -m app.main
