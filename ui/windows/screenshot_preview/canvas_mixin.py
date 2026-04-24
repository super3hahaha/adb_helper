"""画布与图像显示：缩放、平移、重绘、坐标变换。

本 Mixin 拥有：
    self.current_scale, self.img_offset_x, self.img_offset_y
    self.pan_dx, self.pan_dy, self._last_pan
    self.tk_image, self._resize_timer, self._last_canvas_size
本 Mixin 读取但不拥有：
    self.canvas  (主窗口持有)
    self.original_image  (主窗口持有)
    self.shapes  (主窗口持有)
    self.text_editor  (TextAnnotationMixin 持有，只读)
"""
import tkinter as tk
from PIL import Image, ImageTk

from .shared import preferred_tk_font


class CanvasMixin:

    def _init_canvas_state(self):
        self.pan_dx = 0
        self.pan_dy = 0
        self._last_pan = None
        self.tk_image = None

    def _compute_fit_scale(self, img_w, img_h, canvas_w=None, canvas_h=None):
        """计算适应画布的初始缩放比例。"""
        avail_w = canvas_w if canvas_w and canvas_w > 10 else 860
        avail_h = canvas_h if canvas_h and canvas_h > 10 else 580
        return min(avail_w / img_w, avail_h / img_h, 1.0)

    # ---- 坐标变换 ----

    def _img_to_canvas(self, x, y):
        return (
            x * self.current_scale + self.img_offset_x,
            y * self.current_scale + self.img_offset_y,
        )

    def _canvas_to_img(self, cx, cy):
        return (
            (cx - self.img_offset_x) / self.current_scale,
            (cy - self.img_offset_y) / self.current_scale,
        )

    # ---- 重绘 ----

    def update_image(self):
        if not self.original_image:
            return

        width, height = self.original_image.size
        new_width = int(width * self.current_scale)
        new_height = int(height * self.current_scale)

        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        if canvas_width < 10 or canvas_height < 10:
            self.img_offset_x = 0
            self.img_offset_y = 0
            scroll_w, scroll_h = new_width, new_height
        else:
            self.img_offset_x = max(0, (canvas_width - new_width) // 2) + self.pan_dx
            self.img_offset_y = max(0, (canvas_height - new_height) // 2) + self.pan_dy
            scroll_w = max(canvas_width, new_width)
            scroll_h = max(canvas_height, new_height)

        resized_image = self.original_image.resize((new_width, new_height), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(resized_image)

        self.canvas.delete("all")
        self.canvas.create_image(self.img_offset_x, self.img_offset_y, anchor="nw", image=self.tk_image)
        self.canvas.configure(scrollregion=(0, 0, scroll_w, scroll_h))

        self.draw_shapes_on_canvas()

        # 若存在活跃的文字编辑器，canvas.delete("all") 已清除其 items，需要重建
        if self.text_editor is not None:
            self.text_editor['text_id'] = None
            self.text_editor['border_id'] = None
            self.text_editor['cursor_id'] = None
            self.text_editor['handle_ids'] = []
            self._redraw_text_editor()

    def draw_shapes_on_canvas(self):
        for shape in self.shapes:
            x1, y1 = self._img_to_canvas(shape['coords'][0], shape['coords'][1])
            x2, y2 = self._img_to_canvas(shape['coords'][2], shape['coords'][3])

            display_width = max(1, int(shape['width'] * self.current_scale))

            if shape['type'] == 'rect':
                self.canvas.create_rectangle(x1, y1, x2, y2, outline=shape['color'], width=display_width)
            elif shape['type'] == 'arrow':
                self.canvas.create_line(
                    x1, y1, x2, y2,
                    fill=shape['color'], width=display_width, arrow=tk.LAST,
                    arrowshape=(display_width * 4, display_width * 5, display_width * 2),
                )
            elif shape['type'] == 'text':
                display_size = max(8, int(shape.get('font_size', 24) * self.current_scale))
                kwargs = {
                    'text': shape.get('text', ''),
                    'fill': shape['color'],
                    'anchor': "nw",
                    'font': (preferred_tk_font(), display_size),
                }
                width_img = shape.get('width_img')
                if width_img:
                    kwargs['width'] = max(1, int(width_img * self.current_scale))
                self.canvas.create_text(x1, y1, **kwargs)

    def on_canvas_resize(self, event):
        # 仅当画布尺寸真正改变时更新，避免死循环
        if hasattr(self, '_last_canvas_size') and self._last_canvas_size == (event.width, event.height):
            return
        self._last_canvas_size = (event.width, event.height)

        # 延迟更新，避免频繁重绘
        if hasattr(self, '_resize_timer') and self._resize_timer is not None:
            try:
                self.after_cancel(self._resize_timer)
            except Exception:
                pass
        self._resize_timer = self.after(50, self.update_image)

    def reset_view(self):
        """恢复初始的图片缩放和位置。"""
        if not self.original_image:
            return
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        img_w, img_h = self.original_image.size
        self.current_scale = self._compute_fit_scale(img_w, img_h, canvas_width, canvas_height)
        self.pan_dx = 0
        self.pan_dy = 0
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.update_image()

    def on_mouse_wheel(self, event):
        if event.num == 5 or event.delta < 0:
            direction = -1
        else:
            direction = 1

        ctrl_pressed = bool(event.state & 0x4)

        if ctrl_pressed:
            if direction < 0:
                self.current_scale *= 0.9
            else:
                self.current_scale *= 1.1
            self.current_scale = max(0.1, min(self.current_scale, 5.0))
            self.update_image()
        else:
            self.canvas.yview_scroll(-direction, "units")
