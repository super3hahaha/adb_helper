"""Qt 截图预览标注（独立子进程）。

macOS Retina 下 Tk Canvas 位图恒按 1x 栅格化导致预览模糊（见
docs/handoff_retina_preview_migration.md），故预览/标注窗迁移为
PySide6 独立子进程，与主进程通过 stdin/stdout JSON 行 IPC 通信。

- launcher.py     父进程侧：拉起子进程、读回日志、代理重截
- preview_app.py  子进程入口：完整标注窗（由 main.py --qt-preview 调起）

注意：本包 __init__ 不 import 任何子模块 —— launcher 在主进程用
（不能碰 PySide6 的重初始化），preview_app 在子进程用（不能碰 ctk/tkinter）。
"""
