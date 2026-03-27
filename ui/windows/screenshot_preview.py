import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk, ImageDraw
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
        self.drawing_mode = "rect" # None, 'rect', 'arrow'
        self.current_color = "red"
        self.line_width = 9
        self.shapes = [] # List of dict: {'type': 'rect'|'arrow', 'coords': (x1,y1,x2,y2), 'color': str, 'width': int}
        self.start_pos = None # (img_x, img_y)
        self.temp_shape_id = None
        self.is_saved_to_temp = False # 记录是否已保存到临时文件夹

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
        
        self.btn_pan = ctk.CTkButton(self.toolbar_frame, text="✋ 平移", width=80, command=lambda: self.set_mode(None))
        self.btn_pan.pack(side="left", padx=5, pady=5)
        
        self.btn_rect = ctk.CTkButton(self.toolbar_frame, text="⬜ 矩形", width=80, command=lambda: self.set_mode("rect"))
        self.btn_rect.pack(side="left", padx=5, pady=5)
        
        self.btn_arrow = ctk.CTkButton(self.toolbar_frame, text="↗ 箭头", width=80, command=lambda: self.set_mode("arrow"))
        self.btn_arrow.pack(side="left", padx=5, pady=5)
        
        # 分隔符
        ttk.Separator(self.toolbar_frame, orient="vertical").pack(side="left", padx=10, fill="y", pady=5)
        
        # 颜色选择 (简单的一组按钮)
        ctk.CTkLabel(self.toolbar_frame, text="颜色:").pack(side="left", padx=5)
        colors = ["red", "blue", "green", "yellow", "black", "white"]
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

        self.canvas = tk.Canvas(self.canvas_frame, bg="#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#ffffff", highlightthickness=0)
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

        # 2. 底部控制栏
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))

        ctk.CTkLabel(self.control_frame, text="提示: 滚轮缩放，左键拖拽 (Ctrl+C 复制)").pack(side="left", padx=10)

        # 按钮从右向左添加，先添加的在最右边
        self.btn_save = ctk.CTkButton(self.control_frame, text="保存", command=self.save_to_temp)
        self.btn_save.pack(side="right", padx=10, pady=10)

        ctk.CTkButton(self.control_frame, text="另存为...", command=self.save_as, fg_color="#2d7d46", hover_color="#1e5c32").pack(side="right", padx=10, pady=10)

        ctk.CTkButton(self.control_frame, text="复制", command=self.copy_to_clipboard, fg_color="#2d7d46", hover_color="#1e5c32").pack(side="right", padx=10, pady=10)

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
        
        # 初始显示
        self.update_idletasks()
        self.update_image()
        self.set_mode("rect") # 默认矩形+红色
        
        # 窗口关闭清理
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def set_mode(self, mode):
        self.drawing_mode = mode
        # 更新按钮状态
        colors = {"default": ["#3B8ED0", "#1F6AA5"], "active": ["#1F6AA5", "#144870"]} # CTk defaults
        
        self.btn_pan.configure(fg_color=colors["active"] if mode is None else colors["default"])
        self.btn_rect.configure(fg_color=colors["active"] if mode == "rect" else colors["default"])
        self.btn_arrow.configure(fg_color=colors["active"] if mode == "arrow" else colors["default"])
        
        if mode:
            self.canvas.configure(cursor="crosshair")
        else:
            self.canvas.configure(cursor="arrow")

    def set_color(self, color):
        self.current_color = color
        self.color_var.set(color)
        
    def update_width_label(self, value):
        self.line_width = int(value)
        self.width_label.configure(text=str(self.line_width))

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
            self.img_offset_x = max(0, (canvas_width - new_width) // 2)
            self.img_offset_y = max(0, (canvas_height - new_height) // 2)
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

    def draw_shapes_on_canvas(self):
        for shape in self.shapes:
            # 将原始坐标转换为当前缩放后的 Canvas 坐标
            x1 = shape['coords'][0] * self.current_scale + self.img_offset_x
            y1 = shape['coords'][1] * self.current_scale + self.img_offset_y
            x2 = shape['coords'][2] * self.current_scale + self.img_offset_x
            y2 = shape['coords'][3] * self.current_scale + self.img_offset_y
            
            # display_width = max(1, int(shape['width'] * self.current_scale))
            display_width = max(1, int(shape['width'] * self.current_scale))
            
            if shape['type'] == 'rect':
                self.canvas.create_rectangle(x1, y1, x2, y2, outline=shape['color'], width=display_width)
            elif shape['type'] == 'arrow':
                self.canvas.create_line(x1, y1, x2, y2, fill=shape['color'], width=display_width, arrow=tk.LAST, arrowshape=(display_width*4, display_width*5, display_width*2))

    def on_mouse_wheel(self, event):
        if event.num == 5 or event.delta < 0:
            self.current_scale *= 0.9
        else:
            self.current_scale *= 1.1
        self.current_scale = max(0.1, min(self.current_scale, 5.0))
        self.update_image()

    def on_drag_start(self, event):
        if self.drawing_mode:
            # 记录起始点 (转换为图片原始坐标)
            canvas_x = self.canvas.canvasx(event.x)
            canvas_y = self.canvas.canvasy(event.y)
            img_x = (canvas_x - self.img_offset_x) / self.current_scale
            img_y = (canvas_y - self.img_offset_y) / self.current_scale
            self.start_pos = (img_x, img_y)
        else:
            self.canvas.scan_mark(event.x, event.y)

    def on_drag_move(self, event):
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
        else:
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def on_drag_end(self, event):
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
            
            if shape['type'] == 'rect':
                draw.rectangle((nx1, ny1, nx2, ny2), outline=color, width=width)
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
