"""矩形 / 箭头 绘制工具 + 鼠标事件分发。

本 Mixin 拥有：
    self.start_pos, self.temp_shape_id
本 Mixin 读取但不拥有：
    self.canvas, self.drawing_mode, self.current_color, self.line_width  (主窗口)
    self.shapes  (主窗口)
    self.text_editor  (TextAnnotationMixin)
    self.current_scale, self.img_offset_x/y, self._last_pan, self.pan_dx/dy  (CanvasMixin)

on_drag_start 的分发优先级：
    1) 活跃文字编辑器的控制点 / 内部  -> 交给 _start_drag_editor
    2) 点击空白且编辑器活跃 -> commit 后按模式继续
    3) drawing_mode == 'text' -> 创建新编辑器
    4) drawing_mode in ('rect','arrow') -> 开始矩形/箭头绘制
    5) drawing_mode is None -> 自由平移
"""
import tkinter as tk


class DrawingToolsMixin:

    def _init_drawing_state(self):
        self.start_pos = None
        self.temp_shape_id = None

    def on_drag_start(self, event):
        # 优先处理活跃的文字编辑器
        if self.text_editor is not None:
            cx = self.canvas.canvasx(event.x)
            cy = self.canvas.canvasy(event.y)
            hit = self._hit_test_editor(cx, cy)
            if hit == 'inside':
                self._start_drag_editor('move', event)
                return
            if hit.startswith('handle_'):
                idx = int(hit.split('_')[1])
                self._start_drag_editor('resize', event, handle_idx=idx)
                return
            # 点击空白区域：固化当前编辑
            self.commit_text_entry()
            if self.drawing_mode == "text":
                self._create_text_editor(event)
                return

        if self.drawing_mode == "text":
            self._create_text_editor(event)
            return
        if self.drawing_mode:
            canvas_x = self.canvas.canvasx(event.x)
            canvas_y = self.canvas.canvasy(event.y)
            img_x, img_y = self._canvas_to_img(canvas_x, canvas_y)
            self.start_pos = (img_x, img_y)
        else:
            self._last_pan = (event.x, event.y)
            self.canvas.configure(cursor="fleur")

    def on_drag_move(self, event):
        # 文字编辑器拖拽优先
        if self.text_editor is not None and self.text_editor.get('drag_kind'):
            self._update_drag_editor(event)
            return
        if self.drawing_mode and self.start_pos:
            if self.temp_shape_id:
                self.canvas.delete(self.temp_shape_id)

            start_img_x, start_img_y = self.start_pos
            cur_canvas_x = self.canvas.canvasx(event.x)
            cur_canvas_y = self.canvas.canvasy(event.y)
            start_canvas_x, start_canvas_y = self._img_to_canvas(start_img_x, start_img_y)

            display_width = max(1, int(self.line_width * self.current_scale))

            if self.drawing_mode == 'rect':
                self.temp_shape_id = self.canvas.create_rectangle(
                    start_canvas_x, start_canvas_y, cur_canvas_x, cur_canvas_y,
                    outline=self.current_color, width=display_width,
                )
            elif self.drawing_mode == 'arrow':
                self.temp_shape_id = self.canvas.create_line(
                    start_canvas_x, start_canvas_y, cur_canvas_x, cur_canvas_y,
                    fill=self.current_color, width=display_width, arrow=tk.LAST,
                    arrowshape=(display_width * 4, display_width * 5, display_width * 2),
                )
        elif self._last_pan is not None:
            # 自由平移
            dx = event.x - self._last_pan[0]
            dy = event.y - self._last_pan[1]
            self._last_pan = (event.x, event.y)
            self.pan_dx += dx
            self.pan_dy += dy
            self.img_offset_x += dx
            self.img_offset_y += dy
            self.canvas.move("all", dx, dy)

    def on_drag_end(self, event):
        if self.text_editor is not None and self.text_editor.get('drag_kind'):
            self._end_drag_editor(event)
            return
        if self._last_pan is not None:
            self._last_pan = None
            if self.drawing_mode is None:
                self.canvas.configure(cursor="arrow")
            else:
                self.canvas.configure(cursor="crosshair")
        if self.drawing_mode and self.start_pos:
            if self.temp_shape_id:
                self.canvas.delete(self.temp_shape_id)
                self.temp_shape_id = None

            cur_canvas_x = self.canvas.canvasx(event.x)
            cur_canvas_y = self.canvas.canvasy(event.y)
            end_img_x, end_img_y = self._canvas_to_img(cur_canvas_x, cur_canvas_y)

            shape = {
                'type': self.drawing_mode,
                'coords': (self.start_pos[0], self.start_pos[1], end_img_x, end_img_y),
                'color': self.current_color,
                'width': self.line_width,
            }
            self.shapes.append(shape)
            self._push_history({'op': 'add', 'shape': shape, 'index': len(self.shapes) - 1})
            self.start_pos = None

            self.update_image()
