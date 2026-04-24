"""截图预览模块共享工具：字体/文本换行/常量。

全部为模块级纯函数，不依赖任何 self 状态。供多个 Mixin 及主窗口共用，
避免跨 Mixin 的隐式依赖。
"""
import sys
from PIL import ImageFont


# ---------- 常量 ----------

DEFAULT_LINE_WIDTH = 9

# 文字编辑器控制点相关（canvas 像素）
HANDLE_SIZE = 7          # 控制点方块边长
HANDLE_HIT_PAD = 7       # 控制点命中判定的额外像素
BORDER_HIT_PAD = 3       # 虚线边框命中区宽度（< HANDLE_HIT_PAD，保证角点优先）
MIN_WIDTH_IMG = 40       # 文字框最小宽度（图像坐标）
MIN_HEIGHT_IMG = 16      # 文字框最小高度（图像坐标）


# ---------- 字体 ----------

def font_size_from_width(line_width):
    """将粗细滑块值 (1-24) 映射为字体大小，默认 9 -> 约 48pt。"""
    return max(16, int(line_width) * 4 + 12)


def preferred_tk_font():
    """选择一个可显示中文的 Tk 字体族。"""
    if sys.platform == "darwin":
        return "PingFang SC"
    if sys.platform.startswith("win"):
        return "Microsoft YaHei"
    return "DejaVu Sans"


def get_pil_font(size):
    """按平台尝试获取可显示中文的 PIL 字体，失败则退回默认字体。"""
    candidates = []
    if sys.platform.startswith("win"):
        candidates += ["msyh.ttc", "msyh.ttf", "simhei.ttf", "simsun.ttc", "arial.ttf"]
    elif sys.platform == "darwin":
        candidates += ["/System/Library/Fonts/PingFang.ttc", "/Library/Fonts/Arial Unicode.ttf"]
    else:
        candidates += ["DejaVuSans.ttf", "NotoSansCJK-Regular.ttc"]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


# ---------- 文本换行 ----------

def wrap_text_pil(text, font, max_width):
    """按像素宽度对文本做自动换行，保留用户显式换行符。"""
    if not text or not max_width or max_width <= 0:
        return text

    def measure(s):
        if not s:
            return 0
        try:
            bbox = font.getbbox(s)
            return bbox[2] - bbox[0]
        except Exception:
            try:
                return font.getsize(s)[0]
            except Exception:
                return len(s) * 10

    out = []
    for raw_line in text.split('\n'):
        if raw_line == '':
            out.append('')
            continue
        cur = ''
        for ch in raw_line:
            if cur == '' or measure(cur + ch) <= max_width:
                cur += ch
            else:
                out.append(cur)
                cur = ch
        if cur:
            out.append(cur)
    return '\n'.join(out)
