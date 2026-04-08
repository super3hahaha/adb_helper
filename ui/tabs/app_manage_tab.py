import customtkinter as ctk
import tkinter.messagebox as messagebox
import tkinter.filedialog as filedialog
import os
import shutil
import datetime
import threading
import glob
from tkinterdnd2 import DND_FILES
from ui.components.tooltip import ModernTooltip

from ui.utils import optimize_combobox_width
from ui.windows.screenshot_preview import ScreenshotPreviewWindow
from ui.components.logcat_window import LogcatWindow

class AppManageTab(ctk.CTkFrame):
    def __init__(self, parent, adb_helper, config_manager, log_func):
        super().__init__(parent, corner_radius=10)
        self.adb_helper = adb_helper
        self.config_manager = config_manager
        self.log = log_func
        
        # State
        self.is_recording = False
        self.current_app_pkg = None

        self.setup_ui()
        
        # Initial data load
        self.refresh_app_list()
        self.refresh_apk_list()

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # 1. App 选择器
        frame_app_select = ctk.CTkFrame(self, fg_color="transparent")
        frame_app_select.pack(pady=(5, 0), padx=5, fill="x")
        
        ctk.CTkLabel(frame_app_select, text="选择目标 App:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(5, 5))
        self.app_selector = ctk.CTkComboBox(frame_app_select, command=self.on_app_selected, height=28)
        self.app_selector.pack(side="left", fill="x", expand=True, padx=5)
        optimize_combobox_width(self.app_selector)
        self.app_selector.set("请先在设置中添加 App")

        # App 信息显示 (包名)
        self.lbl_app_info = ctk.CTkLabel(self, text="当前包名: -", text_color="gray", height=20, font=ctk.CTkFont(size=11))
        self.lbl_app_info.pack(pady=(0, 5), anchor="w", padx=10, fill="x")

        # 2. 中间操作按钮 (合并为两行)
        frame_actions = ctk.CTkFrame(self)
        frame_actions.pack(pady=5, padx=5, fill="x")
        
        frame_actions.grid_columnconfigure(0, weight=1, uniform="btn_cols")
        frame_actions.grid_columnconfigure(1, weight=1, uniform="btn_cols")

        # 第一行：卸载与清除数据
        ctk.CTkButton(frame_actions, text="卸载选中 App", command=self.action_uninstall_app, fg_color="#c42b1c", hover_color="#8a1f15", height=28).grid(row=0, column=0, sticky="ew", padx=(2, 2), pady=2)
        
        frame_clear_wrapper = ctk.CTkFrame(frame_actions, fg_color="transparent")
        frame_clear_wrapper.grid(row=0, column=1, sticky="ew", padx=(2, 2), pady=2)
        
        btn_help = ctk.CTkButton(frame_clear_wrapper, text="?", width=28, height=28, corner_radius=14, fg_color="gray50", hover_color="gray40", command=lambda: None)
        btn_help.pack(side="right", padx=(2, 0))
        ModernTooltip(btn_help, sections=[
            ("为什么清除数据/执行命令会失败？",
             "很多国内手机品牌（如小米、OPPO、vivo 等）为了防止恶意软件通过 USB 篡改手机，"
             "对 ADB 权限做了阉割或额外限制。仅仅开启\"USB调试\"是不够的。"),
            ("小米 / Redmi (MIUI / HyperOS)",
             "进入手机的\"设置\" -> \"开发者选项\"，找到并开启【USB调试 (安全设置)】。\n"
             "（注：开启此项通常需要插入 SIM 卡并登录小米账号）。\n"
             "此选项的作用是允许通过 USB 修改权限或模拟点击。开启后再执行命令即可成功。"),
            ("OPPO / vivo / realme",
             "进入手机的\"开发者选项\"，往下拉找到类似【禁止权限监控】"
             "或者是安全相关的 USB 调试选项，将其开启。"),
        ])
        
        ctk.CTkButton(frame_clear_wrapper, text="清除 App 数据", command=self.action_clear_data, fg_color="#e0a800", hover_color="#b08800", height=28, anchor="e").pack(side="left", expand=True, fill="x")

        # 第二行：强制停止与启动App
        ctk.CTkButton(frame_actions, text="启动 App (Launch)", command=self.action_launch_app, fg_color="#3B8ED0", hover_color="#36719F", height=28).grid(row=1, column=0, sticky="ew", padx=(2, 2), pady=2)
        ctk.CTkButton(frame_actions, text="强制停止 (Force Stop)", command=self.action_force_stop, fg_color="#e0a800", hover_color="#b08800", height=28).grid(row=1, column=1, sticky="ew", padx=(2, 2), pady=2)

        # 第三行：截图与录屏
        self.btn_screenshot = ctk.CTkButton(frame_actions, text="截取屏幕", command=self.action_take_screenshot, height=28)
        self.btn_screenshot.grid(row=2, column=0, sticky="ew", padx=(2, 2), pady=2)
        self.btn_screen_record = ctk.CTkButton(frame_actions, text="录制屏幕", command=self.action_screen_record, height=28)
        self.btn_screen_record.grid(row=2, column=1, sticky="ew", padx=(2, 2), pady=2)

        # 第四行：Logcat
        ctk.CTkButton(frame_actions, text="查看 Logcat (实时监控)", command=self.action_view_logcat, height=28, fg_color="#3B8ED0", hover_color="#36719F").grid(row=3, column=0, columnspan=2, sticky="ew", padx=(2, 2), pady=2)

        # 3. 智能安装区域 (紧凑版)
        frame_install = ctk.CTkFrame(self)
        frame_install.pack(pady=5, padx=5, fill="x")

        ctk.CTkLabel(frame_install, text="智能安装 (Smart Install)", font=ctk.CTkFont(weight="bold"), height=20).pack(pady=(5, 2), anchor="w", padx=5)
        
        # APK 选择行
        frame_apk_select = ctk.CTkFrame(frame_install, fg_color="transparent")
        frame_apk_select.pack(fill="x", pady=2, padx=5)
        
        self.apk_selector = ctk.CTkComboBox(frame_apk_select, height=28)
        self.apk_selector.pack(side="left", fill="x", expand=True, padx=(0, 5))
        optimize_combobox_width(self.apk_selector, offset=170)
        self.apk_selector.set("未找到匹配的 APK")
        
        self.btn_refresh_apk = ctk.CTkButton(frame_apk_select, text="刷新", command=self.refresh_apk_list, width=60, height=28, fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"))
        self.btn_refresh_apk.pack(side="right")
        self.apk_path_map = {}  # {显示名: 绝对路径}

        # 安装按钮
        ctk.CTkButton(frame_install, text="安装选中的 APK", command=self.action_install_apk, height=28).pack(pady=(5, 5), padx=5, fill="x")

        # 3.5 手动拖拽安装区域 (高度减小)
        self.frame_drag_install = ctk.CTkFrame(self, height=60, fg_color=("gray85", "gray25"))
        self.frame_drag_install.pack(pady=5, padx=5, fill="x")
        self.frame_drag_install.pack_propagate(False) 
        
        lbl_drag = ctk.CTkLabel(self.frame_drag_install, text="拖拽 APK 至此安装", font=ctk.CTkFont(size=13))
        lbl_drag.pack(expand=True)

        # 绑定拖拽事件
        self.frame_drag_install.drop_target_register(DND_FILES)
        self.frame_drag_install.dnd_bind('<<Drop>>', self.on_apk_drop)

        # 4. Firebase 本地调试区域
        frame_firebase = ctk.CTkFrame(self)
        frame_firebase.pack(pady=5, padx=5, fill="x")

        ctk.CTkLabel(frame_firebase, text="Firebase 调试", font=ctk.CTkFont(weight="bold"), height=20).pack(pady=(5, 2), anchor="w", padx=5)
        
        frame_fb_btns = ctk.CTkFrame(frame_firebase, fg_color="transparent")
        frame_fb_btns.pack(fill="x", pady=(0, 5), padx=5)

        self.btn_start_firebase = ctk.CTkButton(frame_fb_btns, text="开启 Firebase 调试并抓取", command=self.action_start_firebase_debug, fg_color="#2d7d46", hover_color="#1e5c32", height=28)
        self.btn_start_firebase.pack(side="left", expand=True, padx=2, fill="x")

    # --- Actions ---

    def _handle_auto_launch(self, pkg):
        """Helper to auto-launch app if enabled in settings"""
        if not pkg: return
        
        if self.config_manager.get_auto_launch_enabled():
            self.log(f"正在自动启动 App: {pkg}...", "INFO")
            # Running in the background thread from on_complete
            success, output = self.adb_helper.launch_app(pkg)
            if success:
                self.log(f"自动启动成功: {pkg}", "SUCCESS")
            else:
                self.log(f"自动启动失败: {output}", "ERROR")

    def on_apk_drop(self, event):
        # event.data might contain multiple files or curly braces if paths have spaces
        file_path = event.data.strip('{}')
        if not file_path.lower().endswith('.apk'):
            self.log("拖入的文件不是 APK，已取消操作", "WARNING")
            return
            
        if not os.path.exists(file_path):
            self.log(f"文件不存在: {file_path}", "ERROR")
            return

        self.log(f"开始手动安装: {os.path.basename(file_path)}...", "INFO")
        
        def _install_thread():
            success, output = self.adb_helper.install_apk_sync(file_path)
            if success:
                self.log(f"安装成功: {os.path.basename(file_path)}\n{output}", "SUCCESS")
            else:
                self.log(f"安装失败: {os.path.basename(file_path)}\n{output}", "ERROR")
                
        threading.Thread(target=_install_thread, daemon=True).start()

    def refresh_app_list(self, force_select_pinned=False):
        """Refresh the app list from config."""
        apps = self.config_manager.get_apps()
        if not apps:
            self.app_selector.set("请先在设置中添加 App")
            self.app_selector.configure(values=[])
            return

        app_labels = [app['name'] for app in apps]
        self.app_selector.configure(values=app_labels)
        
        # Restore selection or select first
        current = self.app_selector.get()
        pinned = self.config_manager.get_pinned_app()
        
        # 强制选中置顶 App，或者当前选中项不在列表中（可能被重命名或删除了），或者当前是默认提示文本
        should_select_pinned = force_select_pinned or \
                               current not in app_labels or \
                               current == "请先在设置中添加 App"

        if should_select_pinned and pinned and pinned in app_labels:
            self.app_selector.set(pinned)
            self.on_app_selected(pinned)
        elif current not in app_labels:
            # 默认选中第一个（ConfigManager 已排序，第一个就是置顶的）
            self.app_selector.set(app_labels[0])
            self.on_app_selected(app_labels[0])
        else:
            # 保持当前选中
            self.on_app_selected(current)

    def on_app_selected(self, choice):
        # Extract pkg
        apps = self.config_manager.get_apps()
        for app in apps:
            if app['name'] == choice:
                self.current_app_pkg = app['pkg']
                self.lbl_app_info.configure(text=f"当前包名: {app['pkg']}")
                # Refresh matching APK list
                self.refresh_apk_list()
                return
        self.current_app_pkg = None
        self.lbl_app_info.configure(text="当前包名: -")

    def action_start_app(self):
        if not self.current_app_pkg:
            self.log("请先选择一个 App", "WARNING")
            return
        
        try:
            self.adb_helper.launch_app(self.current_app_pkg)
        except Exception as e:
            self.log(f"启动 App 异常: {e}", "ERROR")

    def action_stop_app(self):
        if not self.current_app_pkg:
            self.log("请先选择一个 App", "WARNING")
            return
            
        try:
            self.adb_helper.stop_app(self.current_app_pkg)
        except Exception as e:
            self.log(f"停止 App 异常: {e}", "ERROR")

    def action_uninstall_app(self):
        if not self.current_app_pkg:
            messagebox.showwarning("提示", "请先选择一个 App", parent=self)
            return
        
        # 直接执行卸载，不再二次确认
        try:
            self.adb_helper.uninstall_app(self.current_app_pkg)
        except Exception as e:
            self.log(f"卸载 App 异常: {e}", "ERROR")

    def action_clear_data(self):
        if not self.current_app_pkg:
            messagebox.showwarning("提示", "请先选择一个 App", parent=self)
            return
            
        # 直接执行清除数据，不再二次确认
        pkg = self.current_app_pkg
        try:
            self.adb_helper.clear_data(pkg, on_complete=lambda success=True: self._handle_auto_launch(pkg) if success else None)
        except Exception as e:
            self.log(f"清除数据异常: {e}", "ERROR")

    def action_force_stop(self):
        if not self.current_app_pkg:
            messagebox.showwarning("提示", "请先选择一个 App", parent=self)
            return
        pkg = self.current_app_pkg
        def _thread():
            try:
                self.adb_helper.force_stop_app(pkg)
                self.log(f"已强制停止 {pkg}", "SUCCESS")
                self._handle_auto_launch(pkg)
            except Exception as e:
                self.log(f"强制停止失败: {e}", "ERROR")
        threading.Thread(target=_thread, daemon=True).start()

    def action_launch_app(self):
        if not self.current_app_pkg:
            messagebox.showwarning("提示", "请先选择一个 App", parent=self)
            return
        pkg = self.current_app_pkg
        def _thread():
            try:
                self.adb_helper.launch_app(pkg)
                self.log(f"已启动 {pkg}", "SUCCESS")
            except Exception as e:
                self.log(f"启动 App 失败: {e}", "ERROR")
        threading.Thread(target=_thread, daemon=True).start()

    def action_take_screenshot(self):
        temp_dir = self.config_manager.get_temp_dir()
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

        self.log("正在截取屏幕...", "INFO")

        def on_complete(local_path):
            if local_path and os.path.exists(local_path):
                self.log(f"截图已保存至临时目录: {local_path}", "SUCCESS")
                self.after(0, lambda: self.show_screenshot_preview(local_path))
            else:
                self.log("截图失败或文件未生成", "ERROR")
                self.after(0, lambda: messagebox.showerror("失败", "截图失败", parent=self))

        try:
            self.adb_helper.take_screenshot(temp_dir, on_complete)
        except Exception as e:
            self.log(f"截图异常: {e}", "ERROR")

    def show_screenshot_preview(self, image_path):
        temp_dir = self.config_manager.get_temp_dir()
        ScreenshotPreviewWindow(self.winfo_toplevel(), image_path, log_func=self.log, adb_helper=self.adb_helper, temp_dir=temp_dir)

    def action_screen_record(self):
        if self.is_recording:
            # Stop recording
            self.log("正在停止录制并拉取视频...", "INFO")
            self.btn_screen_record.configure(text="处理中...", state="disabled")
            
            def on_complete(local_path):
                self.is_recording = False
                self.after(0, lambda: self.btn_screen_record.configure(text="录制屏幕", fg_color=["#3B8ED0", "#1F6AA5"], hover_color=["#36719F", "#144870"], state="normal"))
                
                if local_path and os.path.exists(local_path):
                    self.log(f"视频已拉取至临时目录: {local_path}", "SUCCESS")
                    
                    def ask_save():
                        # 自定义弹窗
                        dialog = ctk.CTkToplevel(self)
                        dialog.title("录屏结束")
                        dialog.geometry("400x150")
                        dialog.resizable(False, False)
                        dialog.transient(self.winfo_toplevel())
                        dialog.grab_set()
                        
                        # 居中
                        dialog.update_idletasks()
                        x = self.winfo_rootx() + (self.winfo_width() // 2) - (400 // 2)
                        y = self.winfo_rooty() + (self.winfo_height() // 2) - (150 // 2)
                        dialog.geometry(f"+{x}+{y}")
                        
                        ctk.CTkLabel(dialog, text="视频已生成，是否保存到 Temp 目录？", font=ctk.CTkFont(size=14)).pack(pady=(25, 20))
                        
                        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
                        btn_frame.pack(fill="x", padx=40)
                        
                        def on_save():
                            self.log(f"视频已保存至: {local_path}", "SUCCESS")
                            dialog.destroy()
                            
                        def on_cancel():
                            try:
                                filename = os.path.basename(local_path)
                                os.remove(local_path)
                                self.log(f"视频 {filename} 已从 temp 删除", "INFO")
                            except Exception as e:
                                self.log(f"删除临时视频失败: {e}", "ERROR")
                            dialog.destroy()
                            
                        # 拦截右上角关闭按钮
                        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
                            
                        ctk.CTkButton(btn_frame, text="保存到 Temp", command=on_save, width=120, fg_color="#2d7d46", hover_color="#1e5c32").pack(side="left", padx=10)
                        ctk.CTkButton(btn_frame, text="取消并删除", command=on_cancel, width=120, fg_color="#c42b1c", hover_color="#8a1f15").pack(side="right", padx=10)

                    self.after(0, ask_save)
                else:
                    self.log("录制失败或未生成文件", "ERROR")
                    self.after(0, lambda: messagebox.showerror("失败", "录制失败", parent=self))

            try:
                self.adb_helper.stop_recording(self.config_manager.get_temp_dir(), on_complete)
            except Exception as e:
                self.log(f"停止录制异常: {e}", "ERROR")
                self.is_recording = False
                self.btn_screen_record.configure(text="录制屏幕", fg_color=["#3B8ED0", "#1F6AA5"], hover_color=["#36719F", "#144870"], state="normal")
            
        else:
            # Start recording
            temp_dir = self.config_manager.get_temp_dir()
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
                
            try:
                if self.adb_helper.start_recording():
                    self.is_recording = True
                    self.btn_screen_record.configure(text="停止录制", fg_color="#c42b1c", hover_color="#8a1f15")
                    self.log("开始录制屏幕 (最大3分钟)...", "INFO")
                else:
                    messagebox.showerror("失败", "无法启动录制", parent=self)
            except Exception as e:
                self.log(f"启动录制异常: {e}", "ERROR")

    def action_view_logcat(self):
        # 即使没有选中 App 也可以打开 Logcat，只是默认包名为空
        pkg = self.current_app_pkg if self.current_app_pkg else ""
        
        # 打开独立窗口
        try:
            self.logcat_window = LogcatWindow(self, self.adb_helper, default_pkg=pkg, log_func=self.log)
            self.log("已打开 Logcat 监控窗口", "INFO")
        except Exception as e:
            self.log(f"打开 Logcat 窗口失败: {e}", "ERROR")

    def refresh_apk_list(self):
        apk_dir = self.config_manager.get_apk_dir()
        if not apk_dir or not os.path.exists(apk_dir):
            self.apk_selector.set("APK 目录无效，请在设置中配置")
            self.apk_selector.configure(values=[])
            return

        # 禁用按钮，显示扫描状态
        self.btn_refresh_apk.configure(state="disabled", text="扫描中...")

        keyword = ""
        apps = self.config_manager.get_apps()
        for app in apps:
            if app['pkg'] == self.current_app_pkg:
                keyword = app.get('keyword', "")
                break

        def _scan():
            apk_items = []  # [(显示名, 绝对路径, mtime)]
            max_depth = 3
            try:
                base_path = os.path.normpath(apk_dir)
                for root, dirs, files in os.walk(base_path):
                    # 限制递归深度
                    depth = root.replace(base_path, "").count(os.sep)
                    if depth >= max_depth:
                        dirs.clear()
                        continue
                    for f in files:
                        if f.lower().endswith(".apk"):
                            if keyword and keyword.lower() not in f.lower():
                                continue
                            full_path = os.path.join(root, f)
                            # 生成相对路径作为显示名
                            rel_path = os.path.relpath(full_path, base_path)
                            mtime = os.path.getmtime(full_path)
                            apk_items.append((rel_path, full_path, mtime))
            except Exception as e:
                self.after(0, lambda: self.log(f"读取 APK 目录失败: {e}", "ERROR"))

            # 按修改时间降序排序
            apk_items.sort(key=lambda x: x[2], reverse=True)

            # 回主线程更新 UI
            def _update_ui():
                self.btn_refresh_apk.configure(state="normal", text="刷新")
                # 过滤掉隐藏的 APK
                hidden_apks = set(self.config_manager.get_hidden_apks())
                visible_items = [item for item in apk_items if item[0] not in hidden_apks]
                # 智能安装只显示文件名，不带子文件夹前缀
                self.apk_path_map = {os.path.basename(item[1]): item[1] for item in visible_items}
                display_names = [os.path.basename(item[1]) for item in visible_items]
                if display_names:
                    self.apk_selector.configure(values=display_names)
                    self.apk_selector.set(display_names[0])
                else:
                    self.apk_selector.configure(values=[])
                    self.apk_selector.set("未找到匹配的 APK" if keyword else "目录中无 APK")
            self.after(0, _update_ui)

        threading.Thread(target=_scan, daemon=True).start()

    def action_install_apk(self):
        selection = self.apk_selector.get()
        if not selection or selection.startswith("未找到") or selection.startswith("APK 目录") or selection.startswith("目录中无"):
            messagebox.showwarning("提示", "请先选择一个有效的 APK", parent=self)
            return

        # 优先从路径映射中获取绝对路径，兼容旧逻辑
        apk_path = self.apk_path_map.get(selection)
        if not apk_path:
            apk_dir = self.config_manager.get_apk_dir()
            apk_path = os.path.join(apk_dir, selection)

        if not os.path.exists(apk_path):
            messagebox.showerror("错误", "APK 文件不存在", parent=self)
            return

        self.log(f"开始安装: {selection}", "INFO")
        pkg = self.current_app_pkg
        try:
            self.adb_helper.install_apk(apk_path, on_complete=lambda success=True: self._handle_auto_launch(pkg) if success else None)
        except Exception as e:
            self.log(f"安装异常: {str(e)}", "ERROR")

    def action_start_firebase_debug(self):
        pkg = self.current_app_pkg
        if not pkg:
            messagebox.showwarning("提示", "请先选择一个 App", parent=self)
            return

        self.btn_start_firebase.configure(state="disabled", text="⏳ 正在开启...")
        
        def _thread():
            self.adb_helper.enable_firebase_debug(pkg)
            self.after(0, _on_enabled)
            
        def _on_enabled():
            self.btn_start_firebase.configure(state="normal", text="开启 Firebase 调试并抓取")
            from ui.components.firebase_window import FirebaseWindow
            self.firebase_window = FirebaseWindow(self.winfo_toplevel(), self.adb_helper, pkg)

        threading.Thread(target=_thread, daemon=True).start()
