"""截图预览与标注包。

对外只暴露 ScreenshotPreviewWindow，保持与旧单文件模块 `screenshot_preview.py`
相同的 import 路径：
    from ui.windows.screenshot_preview import ScreenshotPreviewWindow

注意：这里必须用 PEP 562 惰性导入。Qt 预览子进程只需要本包中无 UI 依赖的
`shared` / `export` 模块，若在包导入时就加载 preview_window，会把
customtkinter/tkinter 一并拉进 Qt 子进程。
"""

__all__ = ["ScreenshotPreviewWindow"]


def __getattr__(name):
    if name == "ScreenshotPreviewWindow":
        from .preview_window import ScreenshotPreviewWindow
        return ScreenshotPreviewWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
