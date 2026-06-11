# -*- coding: utf-8 -*-
"""
可视化 ADB 管理工具 (Visual ADB Manager)
入口文件
"""

import sys
import os
import datetime
import traceback

# --- 关键修复：确保在 Mac 双击运行时工作目录正确 ---
# Mac 双击 .app 运行时，当前工作目录(CWD)默认是 '/'，这会导致很多相对路径的读取失败
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后的运行路径
    app_dir = os.path.dirname(sys.executable)
    # 如果在 .app 内部，sys.executable 会在 Contents/MacOS 目录下
    if app_dir.endswith('MacOS'):
        # 我们可以将工作目录设置到 MEIPASS (临时解压目录)
        os.chdir(sys._MEIPASS)

# 修复 PyInstaller macOS --windowed 模式下 sys.stdout/sys.stderr 为 None 导致的 print 崩溃
# 并且将输出重定向到日志文件，方便调试闪退问题
if sys.stdout is None or getattr(sys, 'frozen', False):
    log_path = os.path.expanduser('~/adb_helper_crash.log')
    try:
        log_file = open(log_path, 'a', encoding='utf-8')
        log_file.write(f"\n\n--- App Started at {datetime.datetime.now()} ---\n")
        # 记录一下当前的工作目录和环境变量，帮助调试
        log_file.write(f"CWD: {os.getcwd()}\n")
        log_file.write(f"PATH: {os.environ.get('PATH', '')}\n")
        
        class LogWriter:
            def __init__(self, file):
                self.file = file
            def write(self, msg):
                self.file.write(msg)
                self.file.flush()
            def flush(self):
                self.file.flush()
                
        writer = LogWriter(log_file)
        if sys.stdout is None or getattr(sys, 'frozen', False):
            sys.stdout = writer
        if sys.stderr is None or getattr(sys, 'frozen', False):
            sys.stderr = writer
            
        # 挂载一个全局异常钩子，把致命错误写入日志
        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            log_file.write("Uncaught exception:\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=log_file)
            log_file.flush()
        sys.excepthook = handle_exception
            
    except Exception:
        pass

# 修复打包后 tkinterdnd2 找不到动态库的问题
if getattr(sys, 'frozen', False):
    os.environ['TKDND_LIBRARY'] = os.path.join(sys._MEIPASS, 'tkinterdnd2')

# 确保项目根目录在 sys.path 中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# --- Tcl/Tk 库路径修复 (macOS + uv/standalone Python) ---
# uv 装的 standalone CPython 在 venv 里运行时, tkinter 解析 Tcl 库目录会失败
# (报 "Can't find a usable init.tcl"), 因为它按 venv 前缀去找而库实际在 base 解释器下。
# 这里在导入 tkinter 之前, 按 base_prefix 显式指向 tcl8.6/tk8.6。
# 仅在源码运行(非 PyInstaller 打包)且目录确实存在时设置, 不影响 Windows 与打包版。
if sys.platform == "darwin" and not getattr(sys, "frozen", False):
    _tcl_dir = os.path.join(sys.base_prefix, "lib", "tcl8.6")
    _tk_dir = os.path.join(sys.base_prefix, "lib", "tk8.6")
    if "TCL_LIBRARY" not in os.environ and os.path.isdir(_tcl_dir):
        os.environ["TCL_LIBRARY"] = _tcl_dir
    if "TK_LIBRARY" not in os.environ and os.path.isdir(_tk_dir):
        os.environ["TK_LIBRARY"] = _tk_dir

from core.platform_utils import PlatformUtils
# 在初始化任何 GUI 组件之前配置 DPI
PlatformUtils.setup_dpi_awareness()

from ui.main_window import MainWindow

if __name__ == "__main__":
    app = MainWindow()
    app.mainloop()
