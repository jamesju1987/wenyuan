# 用 pythonw 运行（没有命令行窗口）。由启动脚本、开机启动项、右键菜单调用，不需要手动打开。
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from app.tray import main  # noqa: E402

main()
