"""截图预览与标注包。

对外只暴露 ScreenshotPreviewWindow，保持与旧单文件模块 `screenshot_preview.py`
相同的 import 路径：
    from ui.windows.screenshot_preview import ScreenshotPreviewWindow
"""
from .preview_window import ScreenshotPreviewWindow

__all__ = ["ScreenshotPreviewWindow"]
