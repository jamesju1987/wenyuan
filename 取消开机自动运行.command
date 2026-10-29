#!/bin/bash
LABEL="com.guidang.archiver"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST"
echo "✓ 已取消开机自动运行，后台服务已停止。归档库和数据都保留不变。"
read -n 1 -s -r -p "按任意键关闭窗口…"
