"""截图预览与标注主窗口。

职责：
    - 顶层窗口生命周期（创建、关闭、重新截图、另存/复制）
    - 工具栏与快捷键构建
    - 把各 Mixin 串起来的 __init__
    - 将标注合成回 PIL Image 的导出路径（get_annotated_image）

Mixin 构成：
    CanvasMixin             — 图像显示/缩放/平移/重绘
    DrawingToolsMixin       — 矩形/箭头 鼠标事件分发
    TextAnnotationMixin     — 8 控制点文字编辑器
    HistoryMixin            — Undo/Redo 栈

MRO 注意：ctk.CTkToplevel 必须放第一基类；各 Mixin 不重写 __init__，
由本窗口 __init__ 显式调用 _init_xxx_state()。
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageDraw
import os
import math
import sys

# Windows Clipboard
try:
    import win32clipboard
except ImportError:
    win32clipboard = None

from .canvas_mixin import CanvasMixin
from .drawing_tools_mixin import DrawingToolsMixin
from .text_annotation_mixin import TextAnnotationMixin
from .history_mixin import HistoryMixin
from .shared import (
    DEFAULT_LINE_WIDTH,
    get_pil_font, wrap_text_pil,
)


class ScreenshotPreviewWindow(
    ctk.CTkToplevel,
    CanvasMixin,
    DrawingToolsMixin,
    TextAnnotationMixin,
    HistoryMixin,
):
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

        # 窗口级状态
        self.drawing_mode = "rect"  # None, 'rect', 'arrow', 'text'
        self.current_color = "red"
        self.line_width = DEFAULT_LINE_WIDTH
        self.shapes = []  # 每项为 dict：rect/arrow 用 coords；text 额外含 'text'/'font_size'/'width_img'/'height_img'
        self.is_saved_to_temp = False

        # 初始化各 Mixin 的独立状态
        self._init_canvas_state()
        self._init_drawing_state()
        self._init_text_state()
        self._init_history_state()

        # 加载图片
        try:
            self.original_image = Image.open(image_path)
            img_w, img_h = self.original_image.size
            # 初始显示前窗口未绘制完成，用占位尺寸估算
            self.current_scale = self._compute_fit_scale(img_w, img_h, 860, 580)
            self.img_offset_x = 0
            self.img_offset_y = 0
        except Exception as e:
            messagebox.showerror("错误", f"无法加载图片: {e}")
            self.destroy()
            return

        # 布局配置
        self.grid_rowconfigure(1, weight=1)  # Canvas 在 row 1
        self.grid_columnconfigure(0, weight=1)

        self._build_toolbar()
        self._build_canvas()
        self._build_control_bar()
        self._bind_shortcuts()

        # 初始显示
        self.update_idletasks()
        self.update_image()
        self.set_mode("rect")  # 默认矩形+红色

        # 窗口关闭清理
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        self.toolbar_frame = ctk.CTkFrame(self)
        self.toolbar_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))

        # 工具按钮
        self.btn_new_screenshot = ctk.CTkButton(
            self.toolbar_frame, text="➕", width=30, command=self.take_new_screenshot,
            fg_color="#2d7d46", hover_color="#1e5c32",
        )
        self.btn_new_screenshot.pack(side="left", padx=(5, 2), pady=5)

        self.btn_pan = ctk.CTkButton(self.toolbar_frame, text="✋", width=40, command=lambda: self.set_mode(None))
        self.btn_pan.pack(side="left", padx=5, pady=5)

        self.btn_rect = ctk.CTkButton(self.toolbar_frame, text="⬜", width=40, command=lambda: self.set_mode("rect"))
        self.btn_rect.pack(side="left", padx=5, pady=5)

        self.btn_arrow = ctk.CTkButton(self.toolbar_frame, text="↗", width=40, command=lambda: self.set_mode("arrow"))
        self.btn_arrow.pack(side="left", padx=5, pady=5)

        self.btn_text = ctk.CTkButton(self.toolbar_frame, text="T", width=40, command=lambda: self.set_mode("text"))
        self.btn_text.pack(side="left", padx=5, pady=5)

        ttk.Separator(self.toolbar_frame, orient="vertical").pack(side="left", padx=10, fill="y", pady=5)

        # 颜色选择
        ctk.CTkLabel(self.toolbar_frame, text="颜色:").pack(side="left", padx=5)
        colors = ["red", "blue", "green", "yellow"]
        self.color_var = tk.StringVar(value="red")

        for color in colors:
            btn = ctk.CTkButton(
                self.toolbar_frame, text="", width=24, height=24,
                fg_color=color, hover_color=color,
                command=lambda c=color: self.set_color(c),
            )
            btn.pack(side="left", padx=2, pady=5)

        # 线宽选择
        ctk.CTkLabel(self.toolbar_frame, text="粗细:").pack(side="left", padx=(15, 5))
        self.width_slider = ctk.CTkSlider(
            self.toolbar_frame, from_=1, to=24, number_of_steps=23,
            width=150, command=self.update_width_label,
        )
        self.width_slider.set(DEFAULT_LINE_WIDTH)
        self.width_slider.pack(side="left", padx=5)

        self.width_label = ctk.CTkLabel(self.toolbar_frame, text=str(DEFAULT_LINE_WIDTH), width=30)
        self.width_label.pack(side="left", padx=5)

        # 撤销按钮
        self.btn_undo = ctk.CTkButton(
            self.toolbar_frame, text="↩ 撤销", width=80,
            fg_color="#c42b1c", hover_color="#8a1f15",
            command=self.undo_last_shape,
        )
        self.btn_undo.pack(side="right", padx=10, pady=5)

    def _build_canvas(self):
        self.canvas_frame = ctk.CTkFrame(self)
        self.canvas_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.canvas_frame.grid_rowconfigure(0, weight=1)
        self.canvas_frame.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self.canvas_frame,
            bg="#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#ffffff",
            highlightthickness=0, takefocus=1,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.v_scroll = ctk.CTkScrollbar(self.canvas_frame, orientation="vertical", command=self.canvas.yview)
        self.v_scroll.grid(row=0, column=1, sticky="ns")
        self.h_scroll = ctk.CTkScrollbar(self.canvas_frame, orientation="horizontal", command=self.canvas.xview)
        self.h_scroll.grid(row=1, column=0, sticky="ew")

        self.canvas.configure(yscrollcommand=self.v_scroll.set, xscrollcommand=self.h_scroll.set)

        # 鼠标事件
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)  # Windows
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)     # Linux
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)     # Linux
        self.canvas.bind("<ButtonPress-1>", self.on_drag_start)
        self.canvas.bind("<B1-Motion>", self.on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_drag_end)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.canvas.bind("<Key>", self._on_key_during_text_edit)
        self.canvas.bind("<Motion>", self._on_canvas_motion)

    def _build_control_bar(self):
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))

        ctk.CTkLabel(self.control_frame, text="提示: 按住空格+鼠标拖动，Ctrl+滚轮缩放").pack(side="left", padx=10)

        # 从右向左添加，先添加的在最右
        self.btn_save = ctk.CTkButton(self.control_frame, text="保存", command=self.save_to_temp)
        self.btn_save.pack(side="right", padx=10, pady=10)

        ctk.CTkButton(
            self.control_frame, text="另存为...", command=self.save_as,
            fg_color="#2d7d46", hover_color="#1e5c32",
        ).pack(side="right", padx=10, pady=10)

        ctk.CTkButton(
            self.control_frame, text="复制", command=self.copy_to_clipboard,
            fg_color="#2d7d46", hover_color="#1e5c32",
        ).pack(side="right", padx=10, pady=10)

        ctk.CTkButton(
            self.control_frame, text="位置复原", command=self.reset_view,
            fg_color="#6b6b6b", hover_color="#4a4a4a",
        ).pack(side="right", padx=10, pady=10)

    def _bind_shortcuts(self):
        from core.platform_utils import PlatformUtils
        is_mac = PlatformUtils.get_os_type() == "mac"
        ctrl_key = "<Command-" if is_mac else "<Control-"

        self.bind(f"{ctrl_key}c>", lambda e: self.copy_to_clipboard())
        self.bind(f"{ctrl_key}C>", lambda e: self.copy_to_clipboard())
        self.bind(f"{ctrl_key}z>", lambda e: self.undo_last_shape())
        self.bind(f"{ctrl_key}Z>", lambda e: self.undo_last_shape())
        # Redo：Ctrl+Y 与 Ctrl+Shift+Z 双绑定
        self.bind(f"{ctrl_key}y>", lambda e: self.redo_last_shape())
        self.bind(f"{ctrl_key}Y>", lambda e: self.redo_last_shape())
        self.bind(f"{ctrl_key}Shift-z>", lambda e: self.redo_last_shape())
        self.bind(f"{ctrl_key}Shift-Z>", lambda e: self.redo_last_shape())
        self.bind(f"{ctrl_key}s>", lambda e: self.save_to_temp())
        self.bind(f"{ctrl_key}S>", lambda e: self.save_to_temp())

        # 空格键临时切换至平移模式（按住平移，松开恢复）
        self._mode_before_space = None
        self.bind("<KeyPress-space>", self._on_space_press)
        self.bind("<KeyRelease-space>", self._on_space_release)

    # ------------------------------------------------------------------
    # 模式/颜色/线宽控制
    # ------------------------------------------------------------------

    def set_mode(self, mode):
        # 切换模式前，如有文字正在编辑则先固化
        if mode != "text" and self.text_editor is not None:
            self.commit_text_entry()

        self.drawing_mode = mode
        colors = {"default": ["#3B8ED0", "#1F6AA5"], "active": ["#1F6AA5", "#144870"]}

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
        if self._mode_before_space is not None:
            return  # 忽略键盘自动重复
        if self.drawing_mode is None:
            return  # 已经是平移模式
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
        from .shared import font_size_from_width
        self.line_width = int(value)
        self.width_label.configure(text=str(self.line_width))
        if self.text_editor is not None:
            self.text_editor['font_size'] = font_size_from_width(self.line_width)
            self._redraw_text_editor()

    # ------------------------------------------------------------------
    # 顶层窗口操作
    # ------------------------------------------------------------------

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

        self.btn_new_screenshot.configure(state="disabled", text="⏳")
        if self.log_func:
            self.log_func("正在重新截取屏幕...", "INFO")

        def on_complete(local_path):
            self.after(0, lambda: self.btn_new_screenshot.configure(state="normal", text="➕"))

            if local_path and os.path.exists(local_path):
                if self.log_func:
                    self.log_func(f"新截图已保存至临时目录: {local_path}", "SUCCESS")
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
        """加载新的图片并重置状态。"""
        self.image_path = new_image_path
        self.is_saved_to_temp = False
        self.shapes = []
        self._clear_history()

        try:
            self.original_image = Image.open(new_image_path)
            img_w, img_h = self.original_image.size
            canvas_w = self.canvas.winfo_width()
            canvas_h = self.canvas.winfo_height()
            self.current_scale = self._compute_fit_scale(img_w, img_h, canvas_w, canvas_h)
            self.pan_dx = 0
            self.pan_dy = 0

            self.update_image()
            self.set_mode("rect")
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
            final_image.save(self.image_path, optimize=True)
            self.is_saved_to_temp = True
            if self.log_func:
                self.log_func(f"截图已保存至临时文件夹: {self.image_path}", "SUCCESS")
        except Exception as e:
            if self.log_func:
                self.log_func(f"保存截图失败: {e}", "ERROR")
            messagebox.showerror("错误", f"保存失败: {e}", parent=self)

    def copy_to_clipboard(self):
        try:
            from io import BytesIO

            final_image = self.get_annotated_image()

            if sys.platform == "darwin":
                import tempfile
                import subprocess

                # Mac 下用 osascript 复制图片最稳定（pbcopy 不支持直接复制图片数据）
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
        except Exception as e:
            messagebox.showerror("错误", f"复制失败: {e}", parent=self)

    def save_as(self):
        try:
            file_path = filedialog.asksaveasfilename(
                defaultextension=".png",
                filetypes=[("PNG 图像", "*.png"), ("JPEG 图像", "*.jpg"), ("所有文件", "*.*")],
                initialfile=os.path.basename(self.image_path),
            )
            if file_path:
                final_image = self.get_annotated_image()
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
                self.destroy()
        except Exception as e:
            if self.log_func:
                self.log_func(f"另存为失败: {e}", "ERROR")
            messagebox.showerror("错误", f"保存失败: {e}", parent=self)

    # ------------------------------------------------------------------
    # 导出：合成标注到 PIL Image
    # ------------------------------------------------------------------

    def get_annotated_image(self):
        """合成图片和标注，若标注超出图片范围，自动扩展画布。"""
        if not self.shapes:
            return self.original_image

        # 计算所有形状的边界
        min_x, min_y = 0, 0
        max_x, max_y = self.original_image.width, self.original_image.height

        for shape in self.shapes:
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
        max_x = int(math.ceil(max(self.original_image.width, max_x)))
        max_y = int(math.ceil(max(self.original_image.height, max_y)))

        new_width = max_x - min_x
        new_height = max_y - min_y

        if self.original_image.mode == 'RGBA':
            output_image = Image.new('RGBA', (new_width, new_height), (255, 255, 255, 255))
        else:
            output_image = Image.new('RGB', (new_width, new_height), (255, 255, 255))

        offset_x = -min_x
        offset_y = -min_y
        output_image.paste(self.original_image, (offset_x, offset_y))

        draw = ImageDraw.Draw(output_image)

        for shape in self.shapes:
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
