import customtkinter as ctk
import os
import shutil
import tempfile
import sys
import threading
from datetime import datetime
import tkinter as tk

from core.adb_helper import ADBHelper
from core.config import APP_NAME, APP_VERSION
from core.config_manager import ConfigManager
from ui.tabs.app_manage_tab import AppManageTab
from ui.tabs.tools_tab import ToolsTab
from ui.tabs.settings_tab import SettingsTab
from ui.tabs.apk_manager_tab import APKManagerTab

from tkinterdnd2 import TkinterDnD, DND_FILES

class TkinterDnD_CTk(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)

class MainWindow(TkinterDnD_CTk):
    def __init__(self):
        super().__init__()

        # 初始化配置
        self.config_manager = ConfigManager()
        # 初始化 ADB Helper，传入日志回调
        self.adb_helper = ADBHelper(log_callback=self.log_message)
        # 让 ADB Helper 在文件名拼接时能查到设备别名
        self.adb_helper.device_label_resolver = self.config_manager.get_device_alias

        # 窗口设置
        self.title(APP_NAME)
        self.geometry("1000x750")
        
        # 修复 Mac 下的快捷键 (Cmd+C/V/X/A)
        from core.platform_utils import PlatformUtils
        if PlatformUtils.get_os_type() == "mac":
            self.bind_mac_shortcuts()

        # 主窗口最小化时，保持子窗口显示
        self.bind("<Unmap>", self._on_minimize)

        # 设置主题
        ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
        ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

        # 布局配置
        self.grid_columnconfigure(0, weight=4, uniform="group1")
        self.grid_columnconfigure(1, weight=6, uniform="group1")
        self.grid_rowconfigure(0, weight=0) # 设备选择器高度自适应
        self.grid_rowconfigure(1, weight=0) # Tab 区域高度自适应
        self.grid_rowconfigure(2, weight=1) # 内容区域自动填充

        # === 顶部：设备选择器 ===
        self.create_device_selector()

        # === 顶部：Tab 导航栏 ===
        self.create_tab_selector()

        # === 右侧：全局日志输出区 ===
        self.create_log_area()

        # === 左侧/全局：动态内容面板区 ===
        self.create_content_panels()
        
        # 默认选中第一个 Tab
        self.on_tab_change("App 操作")

        # 欢迎日志
        self.log_message("工具启动完成，准备就绪...", "INFO")
        
        # 临时目录 (用于清理)
        self.temp_dir = tempfile.mkdtemp(prefix="adb_tool_temp_")
        
        # 绑定关闭窗口事件，确保清理进程
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 初始化紧凑模式状态
        hide_log = self.config_manager.get_hide_global_log()
        self.toggle_global_log(hide_log)

        # 启动后延迟做一次静默检查更新（等窗口完成绘制再发起网络请求）
        self.after(2000, self._auto_check_update)

    def bind_mac_shortcuts(self):
        """修复 Mac 系统的 Command 键复制粘贴等快捷键"""
        native_widgets = (tk.Entry, tk.Text, tk.Spinbox)

        def _on_mac_shortcut(event, action):
            widget = self.focus_get()
            if widget:
                if isinstance(widget, native_widgets):
                    return
                try:
                    widget.event_generate(f"<<{action}>>")
                except tk.TclError:
                    pass
            return "break"

        self.bind_all("<Command-c>", lambda e: _on_mac_shortcut(e, "Copy"))
        self.bind_all("<Command-v>", lambda e: _on_mac_shortcut(e, "Paste"))
        self.bind_all("<Command-x>", lambda e: _on_mac_shortcut(e, "Cut"))
        self.bind_all("<Command-a>", lambda e: _on_mac_shortcut(e, "SelectAll"))
        # 同时绑定小写和大写，防止开启 CapsLock 导致快捷键失效
        self.bind_all("<Command-C>", lambda e: _on_mac_shortcut(e, "Copy"))
        self.bind_all("<Command-V>", lambda e: _on_mac_shortcut(e, "Paste"))
        self.bind_all("<Command-X>", lambda e: _on_mac_shortcut(e, "Cut"))
        self.bind_all("<Command-A>", lambda e: _on_mac_shortcut(e, "SelectAll"))

    def create_device_selector(self):
        """创建全局设备选择器 + 右侧版本/检查更新区域"""
        self.device_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.device_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(10, 0))
        # col=3 作为弹性空列，把版本/按钮推到最右
        self.device_frame.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(self.device_frame, text="当前设备:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=(0, 10))

        self.device_var = ctk.StringVar(value="未选择设备")
        self.device_selector = ctk.CTkComboBox(
            self.device_frame,
            variable=self.device_var,
            values=[],
            command=self.on_device_change,
            state="readonly",
            width=200
        )
        self.device_selector.grid(row=0, column=1, padx=(0, 10))

        self.btn_refresh_devices = ctk.CTkButton(
            self.device_frame,
            text="刷新",
            width=80,
            command=self.refresh_device_list
        )
        self.btn_refresh_devices.grid(row=0, column=2)

        ctk.CTkLabel(
            self.device_frame,
            text=f"当前版本：v{APP_VERSION}",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=4, padx=(20, 10))

        self.btn_check_update = ctk.CTkButton(
            self.device_frame,
            text="检查更新",
            width=80,
            command=self.action_check_update,
        )
        self.btn_check_update.grid(row=0, column=5)

        # 初始刷新。必须推迟到 mainloop 启动后再发起：refresh 的工作线程会调
        # self.after() 回主线程，若 adb devices 返回得比 mainloop 启动还快
        # （server 已在运行时只要几十毫秒），非主线程调 after 会抛
        # "RuntimeError: main thread is not in main loop"，线程当场死亡，
        # _refreshing_devices 永远为 True → 设备列表刷不出来、刷新按钮失效。
        self.after(0, self.refresh_device_list)

    def action_check_update(self):
        """检查并更新到最新 Release。"""
        from ui.windows.update_window import UpdateFlow
        UpdateFlow(self, log_func=self.log_message, config_manager=self.config_manager).start()

    def _auto_check_update(self):
        """启动后静默检查更新：发现未跳过的新版本时弹窗，否则静默。"""
        try:
            from ui.windows.update_window import UpdateFlow
            UpdateFlow(
                self,
                log_func=self.log_message,
                config_manager=self.config_manager,
            ).start_silent()
        except Exception as e:
            self.log_message(f"自动检查更新启动失败: {e}", "WARNING")

    def _format_device_display(self, device_id):
        """将设备序列号转成下拉框显示文本。"""
        alias = self.config_manager.get_device_alias(device_id)
        if alias:
            return f"{alias} ({device_id})"
        return device_id

    def refresh_device_list(self):
        """刷新设备列表（在子线程执行 adb devices，避免阻塞 UI）。

        adb devices 可能因冷启动 daemon / 设备异常而耗时数秒，放主线程会冻住窗口。
        这里在子线程取设备列表，再用 after(0) 切回主线程更新控件（Tkinter 只能主线程改 UI）。
        """
        # 防止连点刷新时多个线程并发
        if getattr(self, "_refreshing_devices", False):
            return
        self._refreshing_devices = True
        # 每次刷新分配一个递增序号：子线程理论上会在 DEVICES_TIMEOUT 内通过
        # subprocess 的 timeout 返回，但如果 adb 子进程异常卡死导致线程本身
        # 永远不返回，按钮会一直 disabled 点不动。下面的超时兜底会强制恢复
        # 按钮以便重新触发刷新；旧线程即便之后才跑完，靠这个序号在
        # _apply_device_list 里识别为过时结果并丢弃，不会用旧数据覆盖新结果。
        self._device_refresh_gen = getattr(self, "_device_refresh_gen", 0) + 1
        gen = self._device_refresh_gen

        self.log_message("正在刷新设备列表...", "INFO")
        try:
            self.btn_refresh_devices.configure(state="disabled")
        except Exception:
            pass

        def _worker():
            try:
                devices = self.adb_helper.get_connected_devices()
                # 切回主线程更新 UI。after 必须也在 try 内：主循环未就绪/窗口已关时
                # 它会抛 RuntimeError，若不接住，线程死掉后 _refreshing_devices 无人复位
                self.after(0, lambda: self._apply_device_list(devices, gen))
            except Exception:
                # 无法回主线程时至少把并发锁复位，超时兜底会负责恢复按钮状态
                self._refreshing_devices = False

        threading.Thread(target=_worker, daemon=True).start()

        # 兜底：DEVICES_TIMEOUT(10s) 是 subprocess 自身的超时，正常情况下线程
        # 会在此之前完成。留出余量到 15s 还没结束，就当作卡死处理。
        self.after(15000, lambda: self._on_refresh_timeout(gen))

    def _on_refresh_timeout(self, gen):
        """刷新超时兜底：强制恢复按钮，避免线程卡死导致按钮永久不可点。"""
        if gen != getattr(self, "_device_refresh_gen", None):
            return  # 已经有更新的刷新在跑，或本次已正常结束
        if not getattr(self, "_refreshing_devices", False):
            return  # 已经正常结束
        self.log_message("刷新设备列表超时，已强制恢复按钮（原请求可能仍在后台运行）", "WARNING")
        self._refreshing_devices = False
        try:
            self.btn_refresh_devices.configure(state="normal")
        except Exception:
            pass

    def _apply_device_list(self, devices, gen=None):
        """在主线程根据子线程取回的设备列表更新下拉框等控件。"""
        # 期间又点了一次刷新（gen 变了），这次是过时结果，丢弃，避免覆盖新数据
        if gen is not None and gen != getattr(self, "_device_refresh_gen", None):
            return
        self._refreshing_devices = False
        # 窗口可能已关闭
        if not self.winfo_exists():
            return
        try:
            self.btn_refresh_devices.configure(state="normal")
        except Exception:
            pass

        if not devices:
            self._device_display_map = {}
            self.device_selector.configure(values=[])
            self.device_var.set("未选择设备")
            self.adb_helper.current_device_id = None
            self.log_message("未检测到连接的设备", "WARNING")
            return

        # 建立 显示文本 -> 真实序列号 的映射
        display_values = []
        self._device_display_map = {}
        for d in devices:
            disp = self._format_device_display(d)
            display_values.append(disp)
            self._device_display_map[disp] = d

        self.device_selector.configure(values=display_values)

        # 智能联动逻辑
        current = self.adb_helper.current_device_id
        if current in devices:
            # 当前设备还在，保持选中
            self.device_var.set(self._format_device_display(current))
            self.log_message(f"刷新设备列表，保持选中: {current}", "INFO")
        else:
            # 默认选中第一个
            new_device = devices[0]
            self.device_var.set(self._format_device_display(new_device))
            self.adb_helper.current_device_id = new_device
            self.log_message(f"自动选中设备: {new_device}", "SUCCESS")

    def _on_minimize(self, event):
        """主窗口最小化时，保持子窗口(Logcat/Firebase等)正常显示"""
        if event.widget == self and self.state() == "iconic":
            for w in self.winfo_children():
                if isinstance(w, ctk.CTkToplevel) and w.winfo_exists():
                    w.after(10, w.deiconify)

    def on_device_change(self, selected_device):
        """用户手动切换设备"""
        if selected_device and selected_device != "未选择设备":
            # 显示文本反查真实设备号
            real_id = getattr(self, "_device_display_map", {}).get(selected_device, selected_device)
            self.adb_helper.current_device_id = real_id
            self.log_message(f"已切换当前操作设备为: {selected_device}", "SUCCESS")
            # 通知已打开的 Logcat / Firebase 窗口重置
            if hasattr(self, 'tab_app'):
                logcat_win = getattr(self.tab_app, 'logcat_window', None)
                if logcat_win and logcat_win.winfo_exists():
                    logcat_win.reset_for_new_device()
                firebase_win = getattr(self.tab_app, 'firebase_window', None)
                if firebase_win and firebase_win.winfo_exists():
                    firebase_win.reset_for_new_device()

    def create_tab_selector(self):
        # 创建顶部 Tab 切换器 (Segmented Button)
        self.tab_selector = ctk.CTkSegmentedButton(self, values=["App 操作", "小工具", "设置", "APK 管理"], command=self.on_tab_change)
        self.tab_selector.grid(row=1, column=0, columnspan=2, pady=(10, 0), sticky="ew", padx=20)
        self.tab_selector.set("App 操作")

    def create_log_area(self):
        # 创建右侧 Frame (默认放在 row=2, column=1)
        self.log_frame = ctk.CTkFrame(self, corner_radius=10)
        self.log_frame.grid(row=2, column=1, sticky="nsew", padx=(10, 20), pady=20)
        self.log_frame.grid_rowconfigure(1, weight=1)
        self.log_frame.grid_columnconfigure(0, weight=1)

        # 标题
        log_label = ctk.CTkLabel(self.log_frame, text="全局日志监控 (Global Log)", font=ctk.CTkFont(size=16, weight="bold"))
        log_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")
        
        # 清除日志按钮
        ctk.CTkButton(self.log_frame, text="清除日志", width=80, height=24, 
                      fg_color="transparent", border_width=1, 
                      text_color=("gray10", "#DCE4EE"),
                      command=self.clear_log).grid(row=0, column=0, padx=10, pady=(10, 5), sticky="e")

        # 文本框 (使用 CTkTextbox)
        self.log_textbox = ctk.CTkTextbox(self.log_frame, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.log_textbox.configure(state="disabled") # 初始设为只读
        
        # 定义 Tag 颜色
        self.log_textbox.tag_config("INFO", foreground="#2b2b2b" if ctk.get_appearance_mode()=="Light" else "#dce4ee")
        self.log_textbox.tag_config("CMD", foreground="#1f6aa5" if ctk.get_appearance_mode()=="Light" else "#3b8ed0")
        self.log_textbox.tag_config("SUCCESS", foreground="#2d7d46" if ctk.get_appearance_mode()=="Light" else "#2cc985")
        self.log_textbox.tag_config("ERROR", foreground="#c42b1c" if ctk.get_appearance_mode()=="Light" else "#ff5252")

    def clear_log(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def log_message(self, message, level="INFO"):
        """
        日志记录函数，线程安全。
        可以在任何线程调用，会自动调度到主线程更新 UI。
        """
        # 使用 after 确保在主线程更新 UI
        self.after(0, lambda: self._update_log_ui(message, level))

    def _update_log_ui(self, message, level):
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {message}\n"
        
        try:
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", full_msg, level)
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
        except Exception:
            pass # 避免窗口关闭后报错

    def refresh_global_app_list(self):
        """
        当 App 配置或置顶设置发生变化时调用。
        刷新所有相关 Tab 的 App 列表。
        """
        self.log_message("正在刷新全局 App 列表...", "INFO")
        
        # 1. 刷新 App 操作页
        if hasattr(self, 'tab_app'):
            self.tab_app.refresh_app_list()
            
        # 2. 刷新 APK 管理页 (如果有)
        if hasattr(self, 'tab_apk_manager') and hasattr(self.tab_apk_manager, 'refresh_app_list'):
            self.tab_apk_manager.refresh_app_list()

    def create_content_panels(self):
        # 实例化各个 Tab 页面
        # 注意：这里我们将 self (MainWindow) 作为 parent 传入，但实际上它们会根据 on_tab_change 被 grid 到主窗口
        # 我们需要在 Tab 类中处理好布局
        
        self.tab_app = AppManageTab(self, self.adb_helper, self.config_manager, self.log_message)
        self.tab_tools = ToolsTab(self, self.adb_helper, self.config_manager, self.log_message)
        
        # 传入回调函数，实现跨 Tab 刷新
        self.tab_settings = SettingsTab(self, self.adb_helper, self.config_manager, self.log_message,
                                      on_config_changed=self.refresh_global_app_list,
                                      on_device_aliases_changed=self.refresh_device_list)
                                      
        self.tab_apk_manager = APKManagerTab(self, self.adb_helper, self.config_manager, self.log_message)

    def on_tab_change(self, selected_tab):
        """处理 Tab 切换事件"""
        # 1. 隐藏所有面板
        self.tab_app.grid_forget()
        self.tab_tools.grid_forget()
        self.tab_settings.grid_forget()
        self.tab_apk_manager.grid_forget()
        self.log_frame.grid_forget()

        # 2. 根据选择显示面板
        # 这里的 grid 参数需要与原 ADBManagerApp 保持一致
        hide_log = self.config_manager.get_hide_global_log()
        
        if selected_tab == "App 操作":
            self.tab_app.grid(row=2, column=0, sticky="nsew", padx=(20, 10), pady=20)
            if not hide_log:
                self.log_frame.grid(row=2, column=1, sticky="nsew", padx=(10, 20), pady=20)
        elif selected_tab == "小工具":
            self.tab_tools.grid(row=2, column=0, sticky="nsew", padx=(20, 10), pady=20)
            if not hide_log:
                self.log_frame.grid(row=2, column=1, sticky="nsew", padx=(10, 20), pady=20)
        elif selected_tab == "APK 管理":
            self.tab_apk_manager.grid(row=2, column=0, sticky="nsew", padx=(20, 10), pady=20)
            if not hide_log:
                self.log_frame.grid(row=2, column=1, sticky="nsew", padx=(10, 20), pady=20)
            # 切换到此页面时自动刷新列表 (如果有此方法)
            if hasattr(self.tab_apk_manager, 'refresh_apk_manager_list'):
                self.tab_apk_manager.refresh_apk_manager_list()
        elif selected_tab == "设置":
            self.tab_settings.grid(row=2, column=0, sticky="nsew", padx=(20, 10), pady=20)
            if not hide_log:
                self.log_frame.grid(row=2, column=1, sticky="nsew", padx=(10, 20), pady=20)

    def toggle_global_log(self, hide: bool):
        """切换全局日志面板的显示状态 (紧凑模式)"""
        if hide:
            self.log_frame.grid_remove()
            self.grid_columnconfigure(1, weight=0, uniform="")
            self.geometry("400x750")
        else:
            self.grid_columnconfigure(1, weight=6, uniform="group1")
            # 只有当不在切换 Tab 时才显式调用 grid，on_tab_change 也会处理
            self.log_frame.grid(row=2, column=1, sticky="nsew", padx=(10, 20), pady=20)
            self.geometry("1000x750")

    def on_closing(self):
        """窗口关闭时清理资源"""
        # 关闭子窗口（各自会终止自己的子进程）
        if hasattr(self, 'tab_app'):
            for attr in ('logcat_window', 'firebase_window'):
                win = getattr(self.tab_app, attr, None)
                if win and win.winfo_exists():
                    win.on_close()

        # 终止 adb_helper 管理的子进程
        if hasattr(self, 'adb_helper'):
            self.adb_helper.stop_logcat()
            self.adb_helper.stop_firebase_logcat()
            if self.adb_helper.recording_process:
                try:
                    self.adb_helper.recording_process.terminate()
                    self.adb_helper.recording_process.wait(timeout=2)
                except Exception:
                    pass
                self.adb_helper.recording_process = None

        # 清理临时目录
        if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception as e:
                print(f"Error cleaning up temp dir: {e}")

        self.destroy()
