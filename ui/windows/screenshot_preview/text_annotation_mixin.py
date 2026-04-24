"""8 控制点文字标注编辑器。

canvas 原生绘制的透明文字输入框：虚线边框 + 8 控制点（角/边）可自由调整宽高，
移动靠拖边框内部区域，Esc 取消，点击其它区域或切换工具时 commit。

本 Mixin 拥有：
    self.text_editor  (dict, None 表示无活跃编辑器)
    self._committing_text
本 Mixin 读取但不拥有：
    self.canvas  (主窗口)
    self.current_color, self.line_width, self.drawing_mode  (主窗口)
    self.shapes  (主窗口)
    self.current_scale, self.img_offset_x/y  (CanvasMixin)
    self.update_image()  (CanvasMixin)
    self._push_history()  (HistoryMixin)
"""
import tkinter.font as tkfont

from .shared import (
    HANDLE_SIZE, HANDLE_HIT_PAD, BORDER_HIT_PAD,
    MIN_WIDTH_IMG, MIN_HEIGHT_IMG,
    font_size_from_width, preferred_tk_font,
)


# handle_idx (0 TL,1 T,2 TR,3 R,4 BR,5 B,6 BL,7 L) -> drag_kind
_HANDLE_DRAG_KIND = {
    0: 'resize_tl', 1: 'resize_t', 2: 'resize_tr',
    3: 'resize_r',
    4: 'resize_br', 5: 'resize_b', 6: 'resize_bl',
    7: 'resize_l',
}


class TextAnnotationMixin:

    def _init_text_state(self):
        self.text_editor = None
        self._committing_text = False

    # ------------------------------------------------------------------
    # 创建 / 重绘
    # ------------------------------------------------------------------

    def _create_text_editor(self, event):
        """在画布点击位置创建透明的文字编辑器。"""
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        img_x, img_y = self._canvas_to_img(canvas_x, canvas_y)

        font_size = font_size_from_width(self.line_width)
        default_width = max(MIN_WIDTH_IMG, font_size * 12)
        default_height = max(MIN_HEIGHT_IMG, int(font_size * 1.4))

        self.text_editor = {
            'content': '',
            'cursor_pos': 0,
            'anchor_img': [img_x, img_y],
            'width_img': float(default_width),
            'height_img': float(default_height),
            'color': self.current_color,
            'font_size': font_size,
            'text_id': None,
            'border_id': None,
            'handle_ids': [],
            'cursor_id': None,
            'drag_kind': None,
            'drag_start_canvas': None,
            'drag_start_anchor': None,
            'drag_start_width': None,
            'drag_start_height': None,
            'drag_start_img': None,
            'cursor_visible': True,
            'cursor_job': None,
        }

        self._redraw_text_editor()
        self._start_cursor_blink()

        try:
            self.canvas.focus_set()
        except Exception:
            pass

    def _compute_editor_bbox_canvas(self):
        """根据当前 editor 状态计算文字 bounding box（canvas 坐标）。

        高度取 max(文字内容实际高度, 用户设定的 height_img)。
        """
        ed = self.text_editor
        ax, ay = self._img_to_canvas(ed['anchor_img'][0], ed['anchor_img'][1])
        width_px = max(10, int(ed['width_img'] * self.current_scale))
        display_size = max(8, int(ed['font_size'] * self.current_scale))
        font_tuple = (preferred_tk_font(), display_size)

        content = ed['content']
        try:
            f = tkfont.Font(family=font_tuple[0], size=font_tuple[1])
            line_h = f.metrics('linespace')
            if content:
                probe = self.canvas.create_text(
                    -10000, -10000, text=content, anchor='nw',
                    width=width_px, font=font_tuple,
                )
                bbox = self.canvas.bbox(probe)
                self.canvas.delete(probe)
                content_h = (bbox[3] - bbox[1]) if bbox else line_h
            else:
                content_h = line_h
        except Exception:
            content_h = max(16, display_size + 4)

        explicit_h = max(10, int(ed['height_img'] * self.current_scale))
        h = max(content_h, explicit_h)

        pad = 2
        return (ax - pad, ay - pad, ax + width_px + pad, ay + h + pad)

    def _redraw_text_editor(self):
        """重绘文字编辑器的所有 canvas items（文字、虚线框、8 个控制点、光标）。"""
        ed = self.text_editor
        if ed is None:
            return

        # 删除旧 items
        for key in ('text_id', 'border_id', 'cursor_id'):
            if ed.get(key) is not None:
                try:
                    self.canvas.delete(ed[key])
                except Exception:
                    pass
                ed[key] = None
        for hid in ed.get('handle_ids', []) or []:
            try:
                self.canvas.delete(hid)
            except Exception:
                pass
        ed['handle_ids'] = []

        ax, ay = self._img_to_canvas(ed['anchor_img'][0], ed['anchor_img'][1])
        width_px = max(10, int(ed['width_img'] * self.current_scale))
        display_size = max(8, int(ed['font_size'] * self.current_scale))
        font_tuple = (preferred_tk_font(), display_size)

        ed['text_id'] = self.canvas.create_text(
            ax, ay,
            text=ed['content'],
            fill=ed['color'],
            anchor='nw',
            width=width_px,
            font=font_tuple,
        )

        x1, y1, x2, y2 = self._compute_editor_bbox_canvas()
        ed['border_id'] = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline="#6c9ef8", width=1, dash=(4, 3),
        )

        # 8 个控制点：TL, T, TR, R, BR, B, BL, L
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        handle_centers = [
            (x1, y1), (cx, y1), (x2, y1),
            (x2, cy),
            (x2, y2), (cx, y2), (x1, y2),
            (x1, cy),
        ]
        hs = HANDLE_SIZE / 2
        for hx, hy in handle_centers:
            hid = self.canvas.create_rectangle(
                hx - hs, hy - hs, hx + hs, hy + hs,
                outline="#6c9ef8", fill="#ffffff", width=1,
            )
            ed['handle_ids'].append(hid)

        if ed.get('cursor_visible', True):
            cx_pos, cy_pos, line_h = self._compute_cursor_canvas_pos(font_tuple, width_px, ax, ay)
            ed['cursor_id'] = self.canvas.create_line(
                cx_pos, cy_pos, cx_pos, cy_pos + line_h,
                fill=ed['color'], width=max(1, display_size // 12),
            )

    def _compute_cursor_canvas_pos(self, font_tuple, width_px, ax, ay):
        """返回当前光标的 canvas 坐标 (x, y_top) 和行高。"""
        ed = self.text_editor
        content = ed['content']
        cur = ed['cursor_pos']
        cur = max(0, min(cur, len(content)))
        try:
            f = tkfont.Font(family=font_tuple[0], size=font_tuple[1])
            line_h = f.metrics('linespace')
            measure = f.measure
        except Exception:
            line_h = max(14, font_tuple[1] + 4)
            measure = lambda s: len(s) * max(1, font_tuple[1])

        # 对 content[:cur] 做与 canvas create_text(width=...) 相同的软换行
        before = content[:cur]
        lines_so_far = 0
        last_line_text = ''
        for seg_idx, seg in enumerate(before.split('\n')):
            if seg_idx > 0:
                lines_so_far += 1
                last_line_text = ''
            cur_line = ''
            for ch in seg:
                if measure(cur_line + ch) <= width_px or cur_line == '':
                    cur_line += ch
                else:
                    lines_so_far += 1
                    cur_line = ch
            last_line_text = cur_line
        cursor_x_off = measure(last_line_text)
        cursor_y_off = lines_so_far * line_h
        return ax + cursor_x_off, ay + cursor_y_off, line_h

    # ------------------------------------------------------------------
    # 光标闪烁
    # ------------------------------------------------------------------

    def _start_cursor_blink(self):
        ed = self.text_editor
        if ed is None:
            return
        if ed.get('cursor_job') is not None:
            try:
                self.after_cancel(ed['cursor_job'])
            except Exception:
                pass
            ed['cursor_job'] = None

        def _tick():
            if self.text_editor is None:
                return
            self.text_editor['cursor_visible'] = not self.text_editor.get('cursor_visible', True)
            self._redraw_text_editor()
            self.text_editor['cursor_job'] = self.after(500, _tick)

        ed['cursor_visible'] = True
        ed['cursor_job'] = self.after(500, _tick)

    def _stop_cursor_blink(self):
        ed = self.text_editor
        if ed is None:
            return
        job = ed.get('cursor_job')
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
            ed['cursor_job'] = None

    # ------------------------------------------------------------------
    # 命中测试 & 鼠标样式
    # ------------------------------------------------------------------

    def _hit_test_editor(self, cx, cy):
        """返回 'outside' | 'inside' | 'handle_{i}'（i=0..7）。"""
        ed = self.text_editor
        if ed is None:
            return 'outside'
        x1, y1, x2, y2 = self._compute_editor_bbox_canvas()
        hs = HANDLE_SIZE / 2 + HANDLE_HIT_PAD
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2
        handle_centers = [
            (x1, y1), (mx, y1), (x2, y1),
            (x2, my),
            (x2, y2), (mx, y2), (x1, y2),
            (x1, my),
        ]
        for i, (hx, hy) in enumerate(handle_centers):
            if hx - hs <= cx <= hx + hs and hy - hs <= cy <= hy + hs:
                return f'handle_{i}'
        pad = BORDER_HIT_PAD
        if x1 - pad <= cx <= x2 + pad and y1 - pad <= cy <= y2 + pad:
            return 'inside'
        return 'outside'

    def _editor_cursor_for_hit(self, hit):
        if hit == 'inside':
            return 'fleur'
        if hit.startswith('handle_'):
            idx = int(hit.split('_')[1])
            return {
                0: 'size_nw_se', 1: 'size_ns', 2: 'size_ne_sw',
                3: 'size_we',
                4: 'size_nw_se', 5: 'size_ns', 6: 'size_ne_sw',
                7: 'size_we',
            }.get(idx, 'arrow')
        return None

    def _on_canvas_motion(self, event):
        if self.text_editor is None:
            return
        if self.text_editor.get('drag_kind'):
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        hit = self._hit_test_editor(cx, cy)
        cur = self._editor_cursor_for_hit(hit)
        if cur is None:
            if self.drawing_mode == "text":
                self.canvas.configure(cursor="xterm")
            elif self.drawing_mode:
                self.canvas.configure(cursor="crosshair")
            else:
                self.canvas.configure(cursor="arrow")
        else:
            self.canvas.configure(cursor=cur)

    # ------------------------------------------------------------------
    # 键盘输入
    # ------------------------------------------------------------------

    def _on_key_during_text_edit(self, event):
        if self.text_editor is None:
            return
        # Ctrl/Alt 组合键交给外部绑定（undo/copy/save 等）
        if event.state & 0x4 or event.state & 0x8 or event.state & 0x20000:
            return
        keysym = event.keysym
        ed = self.text_editor
        content = ed['content']
        cur = ed['cursor_pos']

        changed = True
        if keysym == 'BackSpace':
            if cur > 0:
                ed['content'] = content[:cur - 1] + content[cur:]
                ed['cursor_pos'] = cur - 1
        elif keysym == 'Delete':
            if cur < len(content):
                ed['content'] = content[:cur] + content[cur + 1:]
        elif keysym in ('Return', 'KP_Enter'):
            ed['content'] = content[:cur] + '\n' + content[cur:]
            ed['cursor_pos'] = cur + 1
        elif keysym == 'Escape':
            self.cancel_text_entry()
            return 'break'
        elif keysym == 'Left':
            ed['cursor_pos'] = max(0, cur - 1)
        elif keysym == 'Right':
            ed['cursor_pos'] = min(len(content), cur + 1)
        elif keysym == 'Home':
            ed['cursor_pos'] = 0
        elif keysym == 'End':
            ed['cursor_pos'] = len(content)
        elif event.char and (event.char.isprintable() or event.char == ' '):
            ed['content'] = content[:cur] + event.char + content[cur:]
            ed['cursor_pos'] = cur + 1
        else:
            changed = False

        if changed:
            ed['cursor_visible'] = True
            self._redraw_text_editor()
            return 'break'

    # ------------------------------------------------------------------
    # 拖拽 (移动 + 8 方向 resize)
    # ------------------------------------------------------------------

    def _start_drag_editor(self, kind, event, handle_idx=None):
        ed = self.text_editor
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        # 以当前显示 bbox 的高度作为 resize 基准，避免 content_h > height_img 时
        # 拖拽前几个像素无视觉反馈的问题
        bx1, by1, bx2, by2 = self._compute_editor_bbox_canvas()
        display_height_img = max(MIN_HEIGHT_IMG, (by2 - by1 - 4) / self.current_scale)
        ed['drag_start_canvas'] = (cx, cy)
        ed['drag_start_anchor'] = list(ed['anchor_img'])
        ed['drag_start_width'] = ed['width_img']
        ed['drag_start_height'] = max(ed['height_img'], display_height_img)
        ed['drag_start_img'] = self._canvas_to_img(cx, cy)
        if kind == 'move':
            ed['drag_kind'] = 'move'
            self.canvas.configure(cursor='fleur')
        elif kind == 'resize':
            ed['drag_kind'] = _HANDLE_DRAG_KIND.get(handle_idx, 'move')
            cur = self._editor_cursor_for_hit(f'handle_{handle_idx}') or 'arrow'
            self.canvas.configure(cursor=cur)

    def _update_drag_editor(self, event):
        ed = self.text_editor
        if ed is None or not ed.get('drag_kind'):
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        start_cx, start_cy = ed['drag_start_canvas']
        dx_img = (cx - start_cx) / self.current_scale
        dy_img = (cy - start_cy) / self.current_scale

        start_ax, start_ay = ed['drag_start_anchor']
        start_w = ed['drag_start_width']
        start_h = ed['drag_start_height']
        kind = ed['drag_kind']

        if kind == 'move':
            ed['anchor_img'][0] = start_ax + dx_img
            ed['anchor_img'][1] = start_ay + dy_img
            self._redraw_text_editor()
            return

        # 8 个控制点分解为"水平 + 垂直"两个轴
        # 水平：l=左边(anchor 随动)，r=右边(anchor 不动)，None=不变
        # 垂直：t=上边(anchor 随动)，b=下边(anchor 不动)，None=不变
        axis_map = {
            'resize_l':  ('l', None),
            'resize_r':  ('r', None),
            'resize_t':  (None, 't'),
            'resize_b':  (None, 'b'),
            'resize_tl': ('l', 't'),
            'resize_tr': ('r', 't'),
            'resize_bl': ('l', 'b'),
            'resize_br': ('r', 'b'),
        }
        hx, vy = axis_map.get(kind, (None, None))

        new_w = start_w
        new_ax = start_ax
        if hx == 'r':
            new_w = max(MIN_WIDTH_IMG, start_w + dx_img)
        elif hx == 'l':
            new_w = max(MIN_WIDTH_IMG, start_w - dx_img)
            new_ax = start_ax + (start_w - new_w)

        new_h = start_h
        new_ay = start_ay
        if vy == 'b':
            new_h = max(MIN_HEIGHT_IMG, start_h + dy_img)
        elif vy == 't':
            new_h = max(MIN_HEIGHT_IMG, start_h - dy_img)
            new_ay = start_ay + (start_h - new_h)

        ed['width_img'] = new_w
        ed['height_img'] = new_h
        ed['anchor_img'][0] = new_ax
        ed['anchor_img'][1] = new_ay

        self._redraw_text_editor()

    def _end_drag_editor(self, event):
        ed = self.text_editor
        if ed is None:
            return
        ed['drag_kind'] = None
        ed['drag_start_canvas'] = None
        try:
            self._on_canvas_motion(event)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 提交 / 取消
    # ------------------------------------------------------------------

    def commit_text_entry(self):
        """将当前输入框中的文字固化为标注形状。"""
        if self._committing_text or self.text_editor is None:
            return
        self._committing_text = True
        try:
            ed = self.text_editor
            self._stop_cursor_blink()
            text = ed['content']
            anchor = tuple(ed['anchor_img'])
            width_img = ed['width_img']
            height_img = ed['height_img']
            color = ed['color']
            font_size = ed['font_size']

            for key in ('text_id', 'border_id', 'cursor_id'):
                if ed.get(key) is not None:
                    try:
                        self.canvas.delete(ed[key])
                    except Exception:
                        pass
            for hid in ed.get('handle_ids', []) or []:
                try:
                    self.canvas.delete(hid)
                except Exception:
                    pass

            self.text_editor = None

            if text and text.strip():
                shape = {
                    'type': 'text',
                    'coords': (anchor[0], anchor[1], anchor[0], anchor[1]),
                    'color': color,
                    'width': self.line_width,
                    'text': text,
                    'font_size': font_size,
                    'width_img': float(width_img),
                    'height_img': float(height_img),
                }
                self.shapes.append(shape)
                self._push_history({'op': 'add', 'shape': shape, 'index': len(self.shapes) - 1})
            self.update_image()
        finally:
            self._committing_text = False

    def cancel_text_entry(self):
        """取消当前输入（Esc），不保存。"""
        if self._committing_text or self.text_editor is None:
            return
        self._committing_text = True
        try:
            ed = self.text_editor
            self._stop_cursor_blink()
            for key in ('text_id', 'border_id', 'cursor_id'):
                if ed.get(key) is not None:
                    try:
                        self.canvas.delete(ed[key])
                    except Exception:
                        pass
            for hid in ed.get('handle_ids', []) or []:
                try:
                    self.canvas.delete(hid)
                except Exception:
                    pass
            self.text_editor = None
        finally:
            self._committing_text = False
