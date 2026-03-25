# -*- coding: utf-8 -*-
"""
可视化 ADB 管理工具 (Visual ADB Manager)
入口文件
"""

import sys
import os
import datetime

# 修复 PyInstaller macOS --windowed 模式下 sys.stdout/sys.stderr 为 None 导致的 print 崩溃
# 并且将输出重定向到日志文件，方便调试闪退问题
if sys.stdout is None or getattr(sys, 'frozen', False):
    log_path = os.path.expanduser('~/adb_helper_crash.log')
    try:
        log_file = open(log_path, 'a', encoding='utf-8')
        log_file.write(f"\n\n--- App Started at {datetime.datetime.now()} ---\n")
        if sys.stdout is None:
            sys.stdout = log_file
        if sys.stderr is None:
            sys.stderr = log_file
    except Exception:
        pass

# 修复打包后 tkinterdnd2 找不到动态库的问题
if getattr(sys, 'frozen', False):
    os.environ['TKDND_LIBRARY'] = os.path.join(sys._MEIPASS, 'tkinterdnd2')

# 确保项目根目录在 sys.path 中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.platform_utils import PlatformUtils
# 在初始化任何 GUI 组件之前配置 DPI
PlatformUtils.setup_dpi_awareness()

from ui.main_window import MainWindow

if __name__ == "__main__":
    app = MainWindow()
    app.mainloop()
