# -*- coding: utf-8 -*-
"""
可视化 ADB 管理工具 (Visual ADB Manager)
入口文件
"""

import sys
import os

# 确保项目根目录在 sys.path 中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.platform_utils import PlatformUtils
# 在初始化任何 GUI 组件之前配置 DPI
PlatformUtils.setup_dpi_awareness()

from ui.main_window import MainWindow

if __name__ == "__main__":
    app = MainWindow()
    app.mainloop()
