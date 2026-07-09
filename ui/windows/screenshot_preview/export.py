"""标注合成导出：把 shapes 渲染回 PIL Image。

纯 PIL 实现，不依赖任何 UI 框架。Tk 标注窗（preview_window）与
Qt 标注子进程（ui/windows/qt_preview/preview_app.py）共用本模块，
保证两边保存出来的图片逐字节一致。

shapes 数据结构（与窗口内存中的一致）：
    每项 dict：'type'('rect'|'arrow'|'text') / 'coords'(x1,y1,x2,y2 图像坐标) /
    'color' / 'width'；text 额外 'text'/'font_size'/'width_img'/'height_img'
"""
import math

from PIL import Image, ImageDraw

from .shared import get_pil_font, wrap_text_pil


def render_annotated_image(original_image, shapes):
    """合成图片和标注，若标注超出图片范围，自动扩展画布。"""
    if not shapes:
        return original_image

    # 计算所有形状的边界
    min_x, min_y = 0, 0
    max_x, max_y = original_image.width, original_image.height

    for shape in shapes:
        x1, y1, x2, y2 = shape['coords']
        width = shape['width']

        if shape['type'] == 'text':
            font = get_pil_font(shape.get('font_size', 24))
            text = shape.get('text', '')
            width_img = shape.get('width_img')
            wrapped = wrap_text_pil(text, font, width_img) if width_img else text
            try:
                measure_img = Image.new('RGB', (1, 1))
                measure_draw = ImageDraw.Draw(measure_img)
                bbox = measure_draw.multiline_textbbox((0, 0), wrapped, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
            except Exception:
                lines = wrapped.split('\n') if wrapped else ['']
                text_w = max((len(l) * shape.get('font_size', 24) for l in lines), default=0)
                text_h = shape.get('font_size', 24) * len(lines)
            height_img = shape.get('height_img')
            min_x = min(min_x, x1)
            min_y = min(min_y, y1)
            max_x = max(max_x, x1 + max(text_w, width_img or 0) + 4)
            max_y = max(max_y, y1 + max(text_h, height_img or 0) + 4)
            continue

        # 线宽和箭头的额外范围（粗略估计）
        padding = width * 4 + 15 if shape['type'] == 'arrow' else width

        min_x = min(min_x, min(x1, x2) - padding)
        min_y = min(min_y, min(y1, y2) - padding)
        max_x = max(max_x, max(x1, x2) + padding)
        max_y = max(max_y, max(y1, y2) + padding)

    min_x = int(math.floor(min(0, min_x)))
    min_y = int(math.floor(min(0, min_y)))
    max_x = int(math.ceil(max(original_image.width, max_x)))
    max_y = int(math.ceil(max(original_image.height, max_y)))

    new_width = max_x - min_x
    new_height = max_y - min_y

    if original_image.mode == 'RGBA':
        output_image = Image.new('RGBA', (new_width, new_height), (255, 255, 255, 255))
    else:
        output_image = Image.new('RGB', (new_width, new_height), (255, 255, 255))

    offset_x = -min_x
    offset_y = -min_y
    output_image.paste(original_image, (offset_x, offset_y))

    draw = ImageDraw.Draw(output_image)

    for shape in shapes:
        x1, y1, x2, y2 = shape['coords']
        nx1 = x1 + offset_x
        ny1 = y1 + offset_y
        nx2 = x2 + offset_x
        ny2 = y2 + offset_y

        color = shape['color']
        width = shape['width']

        if shape['type'] == 'text':
            font = get_pil_font(shape.get('font_size', 24))
            text = shape.get('text', '')
            width_img = shape.get('width_img')
            wrapped = wrap_text_pil(text, font, width_img) if width_img else text
            try:
                draw.multiline_text((nx1, ny1), wrapped, fill=color, font=font)
            except Exception:
                try:
                    draw.text((nx1, ny1), wrapped, fill=color, font=font)
                except Exception:
                    draw.text((nx1, ny1), wrapped, fill=color)
            continue

        if shape['type'] == 'rect':
            rx1, rx2 = sorted((nx1, nx2))
            ry1, ry2 = sorted((ny1, ny2))
            draw.rectangle((rx1, ry1, rx2, ry2), outline=color, width=width)
        elif shape['type'] == 'arrow':
            # PIL 没有直接的 arrow
            draw.line((nx1, ny1, nx2, ny2), fill=color, width=width)

            angle = math.atan2(ny2 - ny1, nx2 - nx1)
            arrow_len = width * 3 + 15
            arrow_angle = math.pi / 6  # 30°

            ax1 = nx2 - arrow_len * math.cos(angle - arrow_angle)
            ay1 = ny2 - arrow_len * math.sin(angle - arrow_angle)
            draw.line((nx2, ny2, ax1, ay1), fill=color, width=width)

            ax2 = nx2 - arrow_len * math.cos(angle + arrow_angle)
            ay2 = ny2 - arrow_len * math.sin(angle + arrow_angle)
            draw.line((nx2, ny2, ax2, ay2), fill=color, width=width)

    return output_image
