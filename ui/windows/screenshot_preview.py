import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk, ImageDraw, ImageFont
import os
import math
import datetime
import sys

# Windows Clipboard
try:
    import win32clipboard
except ImportError:
    win32clipboard = None

class ScreenshotPreviewWindow(ctk.CTkToplevel):
    def __init__(self, parent, image_path, log_func=None, adb_helper=None, temp_dir="temp"):
        super().__init__(parent)
        self.image_path = image_path
        self.log_func = log_func
        self.adb_helper = adb_helper
        self.temp_dir = temp_dir
        self.title("截图预览 (Preview) - 标注模式")
        self.geometry("900x700")
        
        # 绑定主从关系，隐藏独立任务栏图标，并始终保持在主窗口上方
        self.transient(parent.winfo_toplevel())
        
        # 确保窗口弹出时获取焦点并置顶（不拦截其他窗口事件）
        self.after(10, lambda: (self.lift(), self.focus_force()))

        # 标注状态
        self.drawing_mode = "rect" # None, 'rect', 'arrow', 'text'
        self.current_color = "red"
        self.line_width = 9
        self.shapes = [] # List of dict: rect/arrow 用 coords (x1,y1,x2,y2)；text 额外有 'text' 和 'font_size'
        self.start_pos = None # (img_x, img_y)
        self.temp_shape_id = None
        self.is_saved_to_temp = False # 记录是否已保存到临时文件夹
        # 文字编辑态（canvas 原生绘制，支持透明背景 + 虚线框 + 8 个控制点）
        self.text_editor = None
        self._committing_text = False

        # 加载图片
        try:
            self.original_image = Image.open(image_path)
            
            # 默认缩放至适应窗口 (Fit to Window)
            avail_w = 860
            avail_h = 580
            img_w, img_h = self.original_image.size
            
            scale_w = avail_w / img_w
            scale_h = avail_h / img_h
            
            self.current_scale = min(scale_w, scale_h, 1.0)
            self.img_offset_x = 0
            self.img_offset_y = 0
            # 用户拖拽产生的额外偏移（自由平移）
            self.pan_dx = 0
            self.pan_dy = 0
            self._last_pan = None

            self.tk_image = None
        except Exception as e:
            messagebox.showerror("错误", f"无法加载图片: {e}")
            self.destroy()
            return

        # 布局配置
        self.grid_rowconfigure(1, weight=1) # Canvas 在 row 1
        self.grid_columnconfigure(0, weight=1)

        # 0. 顶部工具栏 (Drawing Toolbar)
        self.toolbar_frame = ctk.CTkFrame(self)
        self.toolbar_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        
        # 工具按钮
        self.btn_new_screenshot = ctk.CTkButton(self.toolbar_frame, text="➕", width=30, command=self.take_new_screenshot, fg_color="#2d7d46", hover_color="#1e5c32")
        self.btn_new_screenshot.pack(side="left", padx=(5, 2), pady=5)
        
        self.btn_pan = ctk.CTkButton(self.toolbar_frame, text="✋", width=40, command=lambda: self.set_mode(None))
        self.btn_pan.pack(side="left", padx=5, pady=5)

        self.btn_rect = ctk.CTkButton(self.toolbar_frame, text="⬜", width=40, command=lambda: self.set_mode("rect"))
        self.btn_rect.pack(side="left", padx=5, pady=5)

        self.btn_arrow = ctk.CTkButton(self.toolbar_frame, text="↗", width=40, command=lambda: self.set_mode("arrow"))
        self.btn_arrow.pack(side="left", padx=5, pady=5)

        self.btn_text = ctk.CTkButton(self.toolbar_frame, text="T", width=40, command=lambda: self.set_mode("text"))
        self.btn_text.pack(side="left", padx=5, pady=5)

        # 分隔符
        ttk.Separator(self.toolbar_frame, orient="vertical").pack(side="left", padx=10, fill="y", pady=5)

        # 颜色选择 (简单的一组按钮)
        ctk.CTkLabel(self.toolbar_frame, text="颜色:").pack(side="left", padx=5)
        colors = ["red", "blue", "green", "yellow"]
        self.color_var = tk.StringVar(value="red")
        
        for color in colors:
            btn = ctk.CTkButton(self.toolbar_frame, text="", width=24, height=24, fg_color=color, hover_color=color,
                                command=lambda c=color: self.set_color(c))
            btn.pack(side="left", padx=2, pady=5)
            
        # 线宽选择
        ctk.CTkLabel(self.toolbar_frame, text="粗细:").pack(side="left", padx=(15, 5))
        self.width_slider = ctk.CTkSlider(self.toolbar_frame, from_=1, to=24, number_of_steps=23, width=150, command=self.update_width_label)
        self.width_slider.set(9)
        self.width_slider.pack(side="left", padx=5)
        
        self.width_label = ctk.CTkLabel(self.toolbar_frame, text="9", width=30)
        self.width_label.pack(side="left", padx=5)
        
        # 撤销按钮
        self.btn_undo = ctk.CTkButton(self.toolbar_frame, text="↩ 撤销", width=80, fg_color="#c42b1c", hover_color="#8a1f15", command=self.undo_last_shape)
        self.btn_undo.pack(side="right", padx=10, pady=5)

        # 1. 图片显示区域 (Canvas with Scrollbars)
        self.canvas_frame = ctk.CTkFrame(self)
        self.canvas_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.canvas_frame.grid_rowconfigure(0, weight=1)
        self.canvas_frame.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self.canvas_frame, bg="#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#ffffff", highlightthickness=0, takefocus=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        # 滚动条
        self.v_scroll = ctk.CTkScrollbar(self.canvas_frame, orientation="vertical", command=self.canvas.yview)
        self.v_scroll.grid(row=0, column=1, sticky="ns")
        self.h_scroll = ctk.CTkScrollbar(self.canvas_frame, orientation="horizontal", command=self.canvas.xview)
        self.h_scroll.grid(row=1, column=0, sticky="ew")

        self.canvas.configure(yscrollcommand=self.v_scroll.set, xscrollcommand=self.h_scroll.set)

        # 绑定鼠标事件
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)  # Windows
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)    # Linux
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)    # Linux
        self.canvas.bind("<ButtonPress-1>", self.on_drag_start)
        self.canvas.bind("<B1-Motion>", self.on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_drag_end) # 新增释放事件
        self.canvas.bind("<Configure>", self.on_canvas_resize) # 绑定尺寸变化事件
        self.canvas.bind("<Key>", self._on_key_during_text_edit)
        self.canvas.bind("<Motion>", self._on_canvas_motion)

        # 2. 底部控制栏
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))

        ctk.CTkLabel(self.control_frame, text="提示: 按住空格+鼠标拖动，Ctrl+滚轮缩放").pack(side="left", padx=10)

        # 按钮从右向左添加，先添加的在最右边
        self.btn_save = ctk.CTkButton(self.control_frame, text="保存", command=self.save_to_temp)
        self.btn_save.pack(side="right", padx=10, pady=10)

        ctk.CTkButton(self.control_frame, text="另存为...", command=self.save_as, fg_color="#2d7d46", hover_color="#1e5c32").pack(side="right", padx=10, pady=10)

        ctk.CTkButton(self.control_frame, text="复制", command=self.copy_to_clipboard, fg_color="#2d7d46", hover_color="#1e5c32").pack(side="right", padx=10, pady=10)

        ctk.CTkButton(self.control_frame, text="位置复原", command=self.reset_view, fg_color="#6b6b6b", hover_color="#4a4a4a").pack(side="right", padx=10, pady=10)

        # 快捷键绑定
        from core.platform_utils import PlatformUtils
        is_mac = PlatformUtils.get_os_type() == "mac"
        ctrl_key = "<Command-" if is_mac else "<Control-"
        
        self.bind(f"{ctrl_key}c>", lambda e: self.copy_to_clipboard())
        self.bind(f"{ctrl_key}C>", lambda e: self.copy_to_clipboard())
        self.bind(f"{ctrl_key}z>", lambda e: self.undo_last_shape())
        self.bind(f"{ctrl_key}Z>", lambda e: self.undo_last_shape())
        self.bind(f"{ctrl_key}s>", lambda e: self.save_to_temp())
        self.bind(f"{ctrl_key}S>", lambda e: self.save_to_temp())

        # 空格键临时切换至平移模式（按住时平移，松开恢复原模式）
        self._mode_before_space = None
        self.bind("<KeyPress-space>", self._on_space_press)
        self.bind("<KeyRelease-space>", self._on_space_release)
        
        # 初始显示
        self.update_idletasks()
        self.update_image()
        self.set_mode("rect") # 默认矩形+红色
        
        # 窗口关闭清理
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def set_mode(self, mode):
        # 切换模式前，如有文字正在编辑则先固化
        if mode != "text" and self.text_editor is not None:
            self.commit_text_entry()

        self.drawing_mode = mode
        # 更新按钮状态
        colors = {"default": ["#3B8ED0", "#1F6AA5"], "active": ["#1F6AA5", "#144870"]} # CTk defaults

        self.btn_pan.configure(fg_color=colors["active"] if mode is None else colors["default"])
        self.btn_rect.configure(fg_color=colors["active"] if mode == "rect" else colors["default"])
        self.btn_arrow.configure(fg_color=colors["active"] if mode == "arrow" else colors["default"])
        self.btn_text.configure(fg_color=colors["active"] if mode == "text" else colors["default"])

        if mode == "text":
            self.canvas.configure(cursor="xterm")
        elif mode:
            self.canvas.configure(cursor="crosshair")
        else:
            self.canvas.configure(cursor="arrow")

    def _on_space_press(self, event):
        # 文字编辑中按下空格应插入空格字符，不切换到平移模式
        if self.text_editor is not None:
            return
        # 忽略键盘自动重复触发；仅在第一次按下时记录原模式并切换到平移
        if self._mode_before_space is not None:
            return
        if self.drawing_mode is None:
            return  # 已经是平移模式，无需切换
        self._mode_before_space = self.drawing_mode
        self.set_mode(None)

    def _on_space_release(self, event):
        if self._mode_before_space is None:
            return
        prev = self._mode_before_space
        self._mode_before_space = None
        self.set_mode(prev)

    def set_color(self, color):
        self.current_color = color
        self.color_var.set(color)
        if self.text_editor is not None:
            self.text_editor['color'] = color
            self._redraw_text_editor()

    def update_width_label(self, value):
        self.line_width = int(value)
        self.width_label.configure(text=str(self.line_width))
        if self.text_editor is not None:
            self.text_editor['font_size'] = self._font_size_from_width(self.line_width)
            self._redraw_text_editor()

    def _font_size_from_width(self, line_width):
        """将粗细滑块值 (1-24) 映射为字体大小，默认 9 -> 约 48pt。"""
        return max(16, int(line_width) * 4 + 12)

    def _preferred_tk_font(self):
        """选择一个可显示中文的 Tk 字体族。"""
        if sys.platform == "darwin":
            return "PingFang SC"
        if sys.platform.startswith("win"):
            return "Microsoft YaHei"
        return "DejaVu Sans"

    def _wrap_text_pil(self, text, font, max_width):
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

    def _get_pil_font(self, size):
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

    # ------------------------------------------------------------------
    # Canvas-native 文字编辑器
    # ------------------------------------------------------------------
    HANDLE_SIZE = 7  # 控制点方块边长（canvas 像素）
    HANDLE_HIT_PAD = 7  # 命中判定的额外像素
    BORDER_HIT_PAD = 3  # 虚线边框的命中区宽度（小于 HANDLE_HIT_PAD，保证角点优先命中）
    MIN_WIDTH_IMG = 40  # 文字框最小宽度（图像坐标）
    MIN_HEIGHT_IMG = 16  # 文字框最小高度（图像坐标）

    def _create_text_editor(self, event):
        """在画布点击位置创建透明的文字编辑器。"""
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        img_x = (canvas_x - self.img_offset_x) / self.current_scale
        img_y = (canvas_y - self.img_offset_y) / self.current_scale

        font_size = self._font_size_from_width(self.line_width)
        # 默认宽度：约 12 个字的宽度；默认高度：一行
        default_width = max(self.MIN_WIDTH_IMG, font_size * 12)
        default_height = max(self.MIN_HEIGHT_IMG, int(font_size * 1.4))

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

        # canvas 获取键盘焦点以接收输入
        try:
            self.canvas.focus_set()
        except Exception:
            pass

    def _compute_editor_bbox_canvas(self):
        """根据当前 editor 状态计算文字 bounding box（canvas 坐标）。返回 (x1,y1,x2,y2)。

        高度取 max(文字内容实际高度, 用户设定的 height_img)，以便内容超出
        用户设定时仍可见，同时用户可自由扩大外框。
        """
        ed = self.text_editor
        ax = ed['anchor_img'][0] * self.current_scale + self.img_offset_x
        ay = ed['anchor_img'][1] * self.current_scale + self.img_offset_y
        width_px = max(10, int(ed['width_img'] * self.current_scale))
        display_size = max(8, int(ed['font_size'] * self.current_scale))
        font_tuple = (self._preferred_tk_font(), display_size)

        content = ed['content']
        # 估算内容高度：至少一行
        try:
            import tkinter.font as tkfont
            f = tkfont.Font(family=font_tuple[0], size=font_tuple[1])
            line_h = f.metrics('linespace')
            if content:
                probe = self.canvas.create_text(-10000, -10000, text=content, anchor='nw',
                                                width=width_px, font=font_tuple)
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
        """重绘文字编辑器的所有 canvas items（文字、虚线框、8 个控制点）。"""
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

        ax_img, ay_img = ed['anchor_img']
        ax = ax_img * self.current_scale + self.img_offset_x
        ay = ay_img * self.current_scale + self.img_offset_y
        width_px = max(10, int(ed['width_img'] * self.current_scale))
        display_size = max(8, int(ed['font_size'] * self.current_scale))
        font_tuple = (self._preferred_tk_font(), display_size)

        # 绘制文字（canvas 原生支持按 width 自动换行）
        ed['text_id'] = self.canvas.create_text(
            ax, ay,
            text=ed['content'],
            fill=ed['color'],
            anchor='nw',
            width=width_px,
            font=font_tuple,
        )

        # 计算 bbox
        x1, y1, x2, y2 = self._compute_editor_bbox_canvas()
        # 虚线边框（编辑态样式）
        ed['border_id'] = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline="#6c9ef8", width=1, dash=(4, 3)
        )

        # 8 个控制点位置：TL, T, TR, R, BR, B, BL, L
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        handle_centers = [
            (x1, y1), (cx, y1), (x2, y1),
            (x2, cy),
            (x2, y2), (cx, y2), (x1, y2),
            (x1, cy),
        ]
        hs = self.HANDLE_SIZE / 2
        for hx, hy in handle_centers:
            hid = self.canvas.create_rectangle(
                hx - hs, hy - hs, hx + hs, hy + hs,
                outline="#6c9ef8", fill="#ffffff", width=1
            )
            ed['handle_ids'].append(hid)

        # 光标
        if ed.get('cursor_visible', True):
            cx_pos, cy_pos, line_h = self._compute_cursor_canvas_pos(font_tuple, width_px, ax, ay)
            ed['cursor_id'] = self.canvas.create_line(
                cx_pos, cy_pos, cx_pos, cy_pos + line_h,
                fill=ed['color'], width=max(1, display_size // 12)
            )

    def _compute_cursor_canvas_pos(self, font_tuple, width_px, ax, ay):
        """返回当前光标的 canvas 坐标 (x, y_top) 和行高。"""
        ed = self.text_editor
        content = ed['content']
        cur = ed['cursor_pos']
        cur = max(0, min(cur, len(content)))
        try:
            import tkinter.font as tkfont
            f = tkfont.Font(family=font_tuple[0], size=font_tuple[1])
            line_h = f.metrics('linespace')
            measure = f.measure
        except Exception:
            line_h = max(14, font_tuple[1] + 4)
            measure = lambda s: len(s) * max(1, font_tuple[1])

        # 对 content[:cur] 进行与 canvas create_text(width=...) 相同的软换行
        before = content[:cur]
        # 将 before 按 \n 分段，对每段再按 width_px 自动换行
        lines_so_far = 0
        last_line_text = ''
        for seg_idx, seg in enumerate(before.split('\n')):
            if seg_idx > 0:
                lines_so_far += 1
                last_line_text = ''
            # 对 seg 执行软换行
            cur_line = ''
            for ch in seg:
                if measure(cur_line + ch) <= width_px or cur_line == '':
                    cur_line += ch
                else:
                    lines_so_far += 1
                    cur_line = ch
            last_line_text = cur_line
        # 光标 x 相对于最后一行起点的偏移
        cursor_x_off = measure(last_line_text)
        cursor_y_off = lines_so_far * line_h
        return ax + cursor_x_off, ay + cursor_y_off, line_h

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

    def _hit_test_editor(self, cx, cy):
        """返回 'outside' | 'inside' | 'handle_{i}'（i=0..7）。"""
        ed = self.text_editor
        if ed is None:
            return 'outside'
        x1, y1, x2, y2 = self._compute_editor_bbox_canvas()
        # 先判定 handle（优先级高于边框/内部）
        hs = self.HANDLE_SIZE / 2 + self.HANDLE_HIT_PAD
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
        # 再判定是否在 bbox 内部（含边框）
        pad = self.BORDER_HIT_PAD
        if x1 - pad <= cx <= x2 + pad and y1 - pad <= cy <= y2 + pad:
            return 'inside'
        return 'outside'

    def _editor_cursor_for_hit(self, hit):
        if hit == 'inside':
            return 'fleur'
        if hit.startswith('handle_'):
            idx = int(hit.split('_')[1])
            # 0 TL, 1 T, 2 TR, 3 R, 4 BR, 5 B, 6 BL, 7 L
            return {
                0: 'size_nw_se', 1: 'size_ns', 2: 'size_ne_sw',
                3: 'size_we',
                4: 'size_nw_se', 5: 'size_ns', 6: 'size_ne_sw',
                7: 'size_we',
            }.get(idx, 'arrow')
        return None

    def _on_canvas_motion(self, event):
        # 编辑态下动态更新鼠标样式
        if self.text_editor is None:
            return
        if self.text_editor.get('drag_kind'):
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        hit = self._hit_test_editor(cx, cy)
        cur = self._editor_cursor_for_hit(hit)
        if cur is None:
            # 回到当前模式默认光标
            if self.drawing_mode == "text":
                self.canvas.configure(cursor="xterm")
            elif self.drawing_mode:
                self.canvas.configure(cursor="crosshair")
            else:
                self.canvas.configure(cursor="arrow")
        else:
            self.canvas.configure(cursor=cur)

    def _on_key_during_text_edit(self, event):
        if self.text_editor is None:
            return
        # 让 Ctrl/Alt 组合键交给外部绑定处理（undo/copy/save 等）
        if event.state & 0x4 or event.state & 0x8 or event.state & 0x20000:
            # 但只对产生字母的组合忽略；对单独的 Shift 不忽略
            return
        keysym = event.keysym
        ed = self.text_editor
        content = ed['content']
        cur = ed['cursor_pos']

        changed = True
        if keysym == 'BackSpace':
            if cur > 0:
                ed['content'] = content[:cur-1] + content[cur:]
                ed['cursor_pos'] = cur - 1
        elif keysym == 'Delete':
            if cur < len(content):
                ed['content'] = content[:cur] + content[cur+1:]
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
            # 按键时临时显示光标
            ed['cursor_visible'] = True
            self._redraw_text_editor()
            return 'break'

    # handle_idx (0 TL,1 T,2 TR,3 R,4 BR,5 B,6 BL,7 L) -> drag_kind
    _HANDLE_DRAG_KIND = {
        0: 'resize_tl', 1: 'resize_t', 2: 'resize_tr',
        3: 'resize_r',
        4: 'resize_br', 5: 'resize_b', 6: 'resize_bl',
        7: 'resize_l',
    }

    def _start_drag_editor(self, kind, event, handle_idx=None):
        ed = self.text_editor
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        # 以当前显示 bbox 的高度作为 resize 基准，避免 content_h > height_img 时
        # 拖拽前几个像素无视觉反馈的问题
        bx1, by1, bx2, by2 = self._compute_editor_bbox_canvas()
        display_height_img = max(self.MIN_HEIGHT_IMG, (by2 - by1 - 4) / self.current_scale)
        ed['drag_start_canvas'] = (cx, cy)
        ed['drag_start_anchor'] = list(ed['anchor_img'])
        ed['drag_start_width'] = ed['width_img']
        ed['drag_start_height'] = max(ed['height_img'], display_height_img)
        ed['drag_start_img'] = (
            (cx - self.img_offset_x) / self.current_scale,
            (cy - self.img_offset_y) / self.current_scale,
        )
        if kind == 'move':
            ed['drag_kind'] = 'move'
            self.canvas.configure(cursor='fleur')
        elif kind == 'resize':
            ed['drag_kind'] = self._HANDLE_DRAG_KIND.get(handle_idx, 'move')
            cur = self._editor_cursor_for_hit(f'handle_{handle_idx}') or 'arrow'
            self.canvas.configure(cursor=cur)

    def _update_drag_editor(self, event):
        ed = self.text_editor
        if ed is None or not ed.get('drag_kind'):
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        start_cx, start_cy = ed['drag_start_canvas']
        dx_canvas = cx - start_cx
        dy_canvas = cy - start_cy
        dx_img = dx_canvas / self.current_scale
        dy_img = dy_canvas / self.current_scale

        start_ax, start_ay = ed['drag_start_anchor']
        start_w = ed['drag_start_width']
        start_h = ed['drag_start_height']
        kind = ed['drag_kind']

        if kind == 'move':
            ed['anchor_img'][0] = start_ax + dx_img
            ed['anchor_img'][1] = start_ay + dy_img
            self._redraw_text_editor()
            return

        # resize_* 把 8 个控制点分解为"水平方向 + 垂直方向"两个轴
        # 水平：l=左边（anchor 随动），r=右边（anchor 不动），none=不变
        # 垂直：t=上边（anchor 随动），b=下边（anchor 不动），none=不变
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
            new_w = max(self.MIN_WIDTH_IMG, start_w + dx_img)
        elif hx == 'l':
            new_w = max(self.MIN_WIDTH_IMG, start_w - dx_img)
            new_ax = start_ax + (start_w - new_w)

        new_h = start_h
        new_ay = start_ay
        if vy == 'b':
            new_h = max(self.MIN_HEIGHT_IMG, start_h + dy_img)
        elif vy == 't':
            new_h = max(self.MIN_HEIGHT_IMG, start_h - dy_img)
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
        # 触发一次鼠标样式刷新
        try:
            self._on_canvas_motion(event)
        except Exception:
            pass

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

            # 清理 canvas items
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
                self.shapes.append({
                    'type': 'text',
                    'coords': (anchor[0], anchor[1], anchor[0], anchor[1]),
                    'color': color,
                    'width': self.line_width,
                    'text': text,
                    'font_size': font_size,
                    'width_img': float(width_img),
                    'height_img': float(height_img),
                })
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

    def take_new_screenshot(self):
        if not self.adb_helper:
            if self.log_func:
                self.log_func("无法重新截图: 未提供 ADB 助手", "ERROR")
            return
            
        # 如果当前截图没有保存，先删除它
        if not self.is_saved_to_temp and self.image_path and os.path.exists(self.image_path):
            try:
                os.remove(self.image_path)
                if self.log_func:
                    self.log_func(f"截图 {os.path.basename(self.image_path)} 已从temp删除", "INFO")
            except Exception as e:
                print(f"Error deleting unsaved screenshot: {e}")
                
        # 禁用按钮，显示正在截图状态
        self.btn_new_screenshot.configure(state="disabled", text="⏳")
        if self.log_func:
            self.log_func("正在重新截取屏幕...", "INFO")
            
        def on_complete(local_path):
            # 恢复按钮状态
            self.after(0, lambda: self.btn_new_screenshot.configure(state="normal", text="➕"))
            
            if local_path and os.path.exists(local_path):
                if self.log_func:
                    self.log_func(f"新截图已保存至临时目录: {local_path}", "SUCCESS")
                
                # 在主线程中更新 UI
                self.after(0, lambda: self._load_new_image(local_path))
            else:
                if self.log_func:
                    self.log_func("重新截图失败或文件未生成", "ERROR")
                    
        try:
            self.adb_helper.take_screenshot(self.temp_dir, on_complete)
        except Exception as e:
            if self.log_func:
                self.log_func(f"重新截图异常: {e}", "ERROR")
            self.btn_new_screenshot.configure(state="normal", text="➕")

    def _load_new_image(self, new_image_path):
        """加载新的图片并重置状态"""
        self.image_path = new_image_path
        self.is_saved_to_temp = False
        self.shapes = []  # 清空标注
        
        try:
            self.original_image = Image.open(new_image_path)
            
            # 重新计算缩放比例
            avail_w = 860
            avail_h = 580
            img_w, img_h = self.original_image.size
            
            scale_w = avail_w / img_w
            scale_h = avail_h / img_h
            
            self.current_scale = min(scale_w, scale_h, 1.0)
            
            # 刷新显示
            self.update_image()
            self.set_mode("rect")  # 重置为矩形模式
        except Exception as e:
            messagebox.showerror("错误", f"无法加载新图片: {e}", parent=self)

    def on_close(self):
        if not self.is_saved_to_temp:
            try:
                if os.path.exists(self.image_path):
                    filename = os.path.basename(self.image_path)
                    os.remove(self.image_path)
                    if self.log_func:
                        self.log_func(f"截图 {filename} 已从 temp 删除", "INFO")
            except Exception:
                pass
        self.destroy()

    def save_to_temp(self):
        try:
            final_image = self.get_annotated_image()
            # 使用 optimize 压缩 png 大小
            final_image.save(self.image_path, optimize=True)
            self.is_saved_to_temp = True
            if self.log_func:
                self.log_func(f"截图已保存至临时文件夹: {self.image_path}", "SUCCESS")
            # 保存成功后不再自动关闭窗口，允许继续操作或点击+号新建
        except Exception as e:
            if self.log_func:
                self.log_func(f"保存截图失败: {e}", "ERROR")
            messagebox.showerror("错误", f"保存失败: {e}", parent=self)

    def on_canvas_resize(self, event):
        # 仅当画布尺寸真正改变时更新，避免死循环
        if hasattr(self, '_last_canvas_size') and self._last_canvas_size == (event.width, event.height):
            return
        self._last_canvas_size = (event.width, event.height)
        
        # 延迟更新，避免频繁重绘
        if hasattr(self, '_resize_timer'):
            self.after_cancel(self._resize_timer)
        self._resize_timer = self.after(50, self.update_image)

    def update_image(self):
        if not self.original_image: return
        
        # 计算新尺寸
        width, height = self.original_image.size
        new_width = int(width * self.current_scale)
        new_height = int(height * self.current_scale)
        
        # 获取 Canvas 当前尺寸
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        # 如果窗口尚未完全绘制，宽高可能很小
        if canvas_width < 10 or canvas_height < 10:
            self.img_offset_x = 0
            self.img_offset_y = 0
            scroll_w, scroll_h = new_width, new_height
        else:
            self.img_offset_x = max(0, (canvas_width - new_width) // 2) + self.pan_dx
            self.img_offset_y = max(0, (canvas_height - new_height) // 2) + self.pan_dy
            scroll_w = max(canvas_width, new_width)
            scroll_h = max(canvas_height, new_height)
        
        # 重新采样
        resized_image = self.original_image.resize((new_width, new_height), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(resized_image)
        
        # 更新 Canvas
        self.canvas.delete("all")
        self.canvas.create_image(self.img_offset_x, self.img_offset_y, anchor="nw", image=self.tk_image)
        self.canvas.configure(scrollregion=(0, 0, scroll_w, scroll_h))
        
        # 重绘所有标注
        self.draw_shapes_on_canvas()

        # 若存在活跃的文字编辑器，重建其 canvas items（因 canvas.delete("all") 已清除）
        if self.text_editor is not None:
            # 使 items 关联失效，避免 _redraw 内部 delete 报错
            self.text_editor['text_id'] = None
            self.text_editor['border_id'] = None
            self.text_editor['cursor_id'] = None
            self.text_editor['handle_ids'] = []
            self._redraw_text_editor()

    def draw_shapes_on_canvas(self):
        for shape in self.shapes:
            # 将原始坐标转换为当前缩放后的 Canvas 坐标
            x1 = shape['coords'][0] * self.current_scale + self.img_offset_x
            y1 = shape['coords'][1] * self.current_scale + self.img_offset_y
            x2 = shape['coords'][2] * self.current_scale + self.img_offset_x
            y2 = shape['coords'][3] * self.current_scale + self.img_offset_y

            display_width = max(1, int(shape['width'] * self.current_scale))

            if shape['type'] == 'rect':
                self.canvas.create_rectangle(x1, y1, x2, y2, outline=shape['color'], width=display_width)
            elif shape['type'] == 'arrow':
                self.canvas.create_line(x1, y1, x2, y2, fill=shape['color'], width=display_width, arrow=tk.LAST, arrowshape=(display_width*4, display_width*5, display_width*2))
            elif shape['type'] == 'text':
                display_size = max(8, int(shape.get('font_size', 24) * self.current_scale))
                kwargs = {
                    'text': shape.get('text', ''),
                    'fill': shape['color'],
                    'anchor': "nw",
                    'font': (self._preferred_tk_font(), display_size),
                }
                width_img = shape.get('width_img')
                if width_img:
                    kwargs['width'] = max(1, int(width_img * self.current_scale))
                self.canvas.create_text(x1, y1, **kwargs)

    def reset_view(self):
        """恢复初始的图片缩放和位置"""
        if not self.original_image:
            return
        # 重新按当前画布大小计算适应缩放
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        avail_w = canvas_width if canvas_width > 10 else 860
        avail_h = canvas_height if canvas_height > 10 else 580
        img_w, img_h = self.original_image.size
        self.current_scale = min(avail_w / img_w, avail_h / img_h, 1.0)
        # 清空平移偏移
        self.pan_dx = 0
        self.pan_dy = 0
        # 重置滚动条到原点
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.update_image()

    def on_mouse_wheel(self, event):
        # 判断滚轮方向
        if event.num == 5 or event.delta < 0:
            direction = -1  # 向下
        else:
            direction = 1   # 向上

        # 判断是否按住 Ctrl (event.state bit 0x4)
        ctrl_pressed = bool(event.state & 0x4)

        if ctrl_pressed:
            # 缩放
            if direction < 0:
                self.current_scale *= 0.9
            else:
                self.current_scale *= 1.1
            self.current_scale = max(0.1, min(self.current_scale, 5.0))
            self.update_image()
        else:
            # 普通滚动：垂直滚动条
            self.canvas.yview_scroll(-direction, "units")

    def on_drag_start(self, event):
        # 优先处理活跃的文字编辑器：内部/控制点 -> 开始拖拽；外部 -> 先固化
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
            # 仍处于文字模式则在新位置开启输入
            if self.drawing_mode == "text":
                self._create_text_editor(event)
                return
            # 其它模式继续走后续流程

        if self.drawing_mode == "text":
            self._create_text_editor(event)
            return
        if self.drawing_mode:
            # 记录起始点 (转换为图片原始坐标)
            canvas_x = self.canvas.canvasx(event.x)
            canvas_y = self.canvas.canvasy(event.y)
            img_x = (canvas_x - self.img_offset_x) / self.current_scale
            img_y = (canvas_y - self.img_offset_y) / self.current_scale
            self.start_pos = (img_x, img_y)
        else:
            # 平移模式：记录拖动起点，使用自由偏移
            self._last_pan = (event.x, event.y)
            self.canvas.configure(cursor="fleur")

    def on_drag_move(self, event):
        # 文字编辑器的拖拽优先
        if self.text_editor is not None and self.text_editor.get('drag_kind'):
            self._update_drag_editor(event)
            return
        if self.drawing_mode and self.start_pos:
            # 绘制临时形状
            if self.temp_shape_id:
                self.canvas.delete(self.temp_shape_id)
            
            start_img_x, start_img_y = self.start_pos
            
            cur_canvas_x = self.canvas.canvasx(event.x)
            cur_canvas_y = self.canvas.canvasy(event.y)
            
            start_canvas_x = start_img_x * self.current_scale + self.img_offset_x
            start_canvas_y = start_img_y * self.current_scale + self.img_offset_y
            
            # 显示时的线宽
            display_width = max(1, int(self.line_width * self.current_scale))
            
            if self.drawing_mode == 'rect':
                self.temp_shape_id = self.canvas.create_rectangle(
                    start_canvas_x, start_canvas_y, cur_canvas_x, cur_canvas_y,
                    outline=self.current_color, width=display_width
                )
            elif self.drawing_mode == 'arrow':
                self.temp_shape_id = self.canvas.create_line(
                    start_canvas_x, start_canvas_y, cur_canvas_x, cur_canvas_y,
                    fill=self.current_color, width=display_width, arrow=tk.LAST,
                    arrowshape=(display_width*4, display_width*5, display_width*2)
                )
        elif self._last_pan is not None:
            # 自由平移：通过移动 canvas 上的所有元素，同时累计偏移量
            dx = event.x - self._last_pan[0]
            dy = event.y - self._last_pan[1]
            self._last_pan = (event.x, event.y)
            self.pan_dx += dx
            self.pan_dy += dy
            self.img_offset_x += dx
            self.img_offset_y += dy
            self.canvas.move("all", dx, dy)

    def on_drag_end(self, event):
        # 结束文字编辑器拖拽
        if self.text_editor is not None and self.text_editor.get('drag_kind'):
            self._end_drag_editor(event)
            return
        if self._last_pan is not None:
            self._last_pan = None
            # 恢复光标
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
            
            end_img_x = (cur_canvas_x - self.img_offset_x) / self.current_scale
            end_img_y = (cur_canvas_y - self.img_offset_y) / self.current_scale
            
            # 保存形状数据 (原始坐标)
            shape = {
                'type': self.drawing_mode,
                'coords': (self.start_pos[0], self.start_pos[1], end_img_x, end_img_y),
                'color': self.current_color,
                'width': self.line_width
            }
            self.shapes.append(shape)
            self.start_pos = None
            
            # 永久绘制
            self.update_image()

    def get_annotated_image(self):
        """合成图片和标注，若标注超出图片范围，自动扩展画布"""
        if not self.shapes:
            return self.original_image
        
        # 计算所有形状的边界
        min_x, min_y = 0, 0
        max_x, max_y = self.original_image.width, self.original_image.height
        
        for shape in self.shapes:
            x1, y1, x2, y2 = shape['coords']
            width = shape['width']

            if shape['type'] == 'text':
                # 根据字体估算文字包围盒（含换行）
                font = self._get_pil_font(shape.get('font_size', 24))
                text = shape.get('text', '')
                width_img = shape.get('width_img')
                wrapped = self._wrap_text_pil(text, font, width_img) if width_img else text
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
                # 文字框宽高以用户设置的 width_img/height_img 为准，同时兼容内容溢出
                max_x = max(max_x, x1 + max(text_w, width_img or 0) + 4)
                max_y = max(max_y, y1 + max(text_h, height_img or 0) + 4)
                continue

            # 考虑线宽和箭头的额外范围（粗略估计）
            padding = width * 4 + 15 if shape['type'] == 'arrow' else width

            min_x = min(min_x, min(x1, x2) - padding)
            min_y = min(min_y, min(y1, y2) - padding)
            max_x = max(max_x, max(x1, x2) + padding)
            max_y = max(max_y, max(y1, y2) + padding)
            
        # 确保不会无意义地缩小（即 min 不能大于0，max 不能小于原图大小）
        min_x = int(math.floor(min(0, min_x)))
        min_y = int(math.floor(min(0, min_y)))
        max_x = int(math.ceil(max(self.original_image.width, max_x)))
        max_y = int(math.ceil(max(self.original_image.height, max_y)))
        
        new_width = max_x - min_x
        new_height = max_y - min_y
        
        # 创建新画布，无论原图格式，扩展区统一使用白色背景
        if self.original_image.mode == 'RGBA':
            output_image = Image.new('RGBA', (new_width, new_height), (255, 255, 255, 255))
        else:
            output_image = Image.new('RGB', (new_width, new_height), (255, 255, 255))
            
        # 将原图贴在正确的位置
        offset_x = -min_x
        offset_y = -min_y
        output_image.paste(self.original_image, (offset_x, offset_y))
        
        draw = ImageDraw.Draw(output_image)
        
        for shape in self.shapes:
            # 调整坐标到新画布
            x1, y1, x2, y2 = shape['coords']
            nx1 = x1 + offset_x
            ny1 = y1 + offset_y
            nx2 = x2 + offset_x
            ny2 = y2 + offset_y
            
            color = shape['color']
            width = shape['width']
            
            if shape['type'] == 'text':
                font = self._get_pil_font(shape.get('font_size', 24))
                text = shape.get('text', '')
                width_img = shape.get('width_img')
                wrapped = self._wrap_text_pil(text, font, width_img) if width_img else text
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
                # PIL 没有直接的 arrow，需要手动绘制
                # 画主线
                draw.line((nx1, ny1, nx2, ny2), fill=color, width=width)
                
                # 计算箭头
                angle = math.atan2(ny2 - ny1, nx2 - nx1)
                arrow_len = width * 3 + 15 # 箭头长度
                arrow_angle = math.pi / 6 # 30度
                
                # 箭头翼1
                ax1 = nx2 - arrow_len * math.cos(angle - arrow_angle)
                ay1 = ny2 - arrow_len * math.sin(angle - arrow_angle)
                draw.line((nx2, ny2, ax1, ay1), fill=color, width=width)
                
                # 箭头翼2
                ax2 = nx2 - arrow_len * math.cos(angle + arrow_angle)
                ay2 = ny2 - arrow_len * math.sin(angle + arrow_angle)
                draw.line((nx2, ny2, ax2, ay2), fill=color, width=width)
                
        return output_image

    def undo_last_shape(self, event=None):
        if self.shapes:
            self.shapes.pop()
            self.update_image()
            
    def copy_to_clipboard(self):
        try:
            from io import BytesIO
            
            # 获取合成后的图片
            final_image = self.get_annotated_image()
            
            if sys.platform == "darwin":
                import tempfile
                import subprocess
                
                # Mac 下使用 osascript 复制图片最稳定（pbcopy 不支持直接复制图片数据）
                with tempfile.NamedTemporaryFile(suffix=".tiff", delete=False) as tmp:
                    final_image.convert("RGB").save(tmp.name, "TIFF")
                    tmp_path = tmp.name
                
                try:
                    script = f'set the clipboard to (read (POSIX file "{tmp_path}") as TIFF picture)'
                    subprocess.run(['osascript', '-e', script], check=True)
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
            elif win32clipboard:
                output = BytesIO()
                final_image.convert("RGB").save(output, "BMP")
                data = output.getvalue()[14:]
                output.close()
                
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
                win32clipboard.CloseClipboard()
            else:
                messagebox.showwarning("警告", "当前系统暂不支持直接复制图片到剪贴板", parent=self)
            # 复制成功不弹窗
        except Exception as e:
            messagebox.showerror("错误", f"复制失败: {e}", parent=self)

    def save_as(self):
        try:
            # 默认使用 png，并添加 jpg 支持
            file_path = filedialog.asksaveasfilename(
                defaultextension=".png",
                filetypes=[("PNG 图像", "*.png"), ("JPEG 图像", "*.jpg"), ("所有文件", "*.*")],
                initialfile=os.path.basename(self.image_path)
            )
            if file_path:
                final_image = self.get_annotated_image()
                # 如果用户选择 jpg，需要转换为 RGB 模式
                if file_path.lower().endswith(('.jpg', '.jpeg')):
                    if final_image.mode in ('RGBA', 'P'):
                        final_image = final_image.convert('RGB')
                    final_image.save(file_path, quality=85, optimize=True)
                else:
                    final_image.save(file_path, optimize=True)
                self.is_saved_to_temp = True  # 视同已保存，关闭时不删原图
                if self.log_func:
                    self.log_func(f"截图另存为: {file_path}", "SUCCESS")
                messagebox.showinfo("成功", f"截图已保存至:\n{file_path}", parent=self)
                # 另存为也自动关闭预览窗口
                self.destroy()
        except Exception as e:
            if self.log_func:
                self.log_func(f"另存为失败: {e}", "ERROR")
            messagebox.showerror("错误", f"保存失败: {e}", parent=self)
