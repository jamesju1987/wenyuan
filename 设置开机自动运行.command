#!/bin/bash
# 让文渊在登录 Mac 后自动在后台运行，收件箱随时自动整理（不需要一直开着终端窗口）。
cd "$(dirname "$0")"
APP_DIR="$(pwd)"
LABEL="com.guidang.archiver"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT="${GUIDANG_PORT:-8790}"

bash scripts/setup.sh || { read -n 1 -s -r -p "按任意键关闭窗口…"; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents" "$APP_DIR/data"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$APP_DIR/.venv/bin/python</string>
    <string>-m</string>
    <string>app.main</string>
  </array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>EnvironmentVariables</key><dict><key>GUIDANG_PORT</key><string>$PORT</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$APP_DIR/data/server.log</string>
  <key>StandardErrorPath</key><string>$APP_DIR/data/server.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 2
echo
echo "✓ 已设置为开机自动运行，现在已在后台启动。"
echo "  打开界面：http://127.0.0.1:$PORT 或双击「启动文渊.command」"
echo "  如需取消：双击「取消开机自动运行.command」"
open "http://127.0.0.1:$PORT"
read -n 1 -s -r -p "按任意键关闭窗口…"
