# -*- coding: utf-8 -*-
"""
可视化 ADB 管理工具 (Visual ADB Manager)
入口文件
"""

import sys
import os

# 修复 PyInstaller macOS --windowed 模式下 sys.stdout/sys.stderr 为 None 导致的 print 崩溃
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

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
