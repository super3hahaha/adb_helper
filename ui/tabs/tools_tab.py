import customtkinter as ctk
import tkinter.messagebox as messagebox
import threading
import subprocess
from ui.utils import optimize_combobox_width
from ui.components.tooltip import ModernTooltip

class ToolsTab(ctk.CTkFrame):
    def __init__(self, parent, adb_helper, config_manager, log_func):
        super().__init__(parent, corner_radius=10)
        self.main_window = parent
        self.adb_helper = adb_helper
        self.config_manager = config_manager
        self.log = log_func
        
        self.setup_ui()

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # 0. 下拉选择框
        self.category_var = ctk.StringVar(value="设备与系统控制")
        self.category_selector = ctk.CTkOptionMenu(
            self,
            values=["设备与系统控制", "环境与状态模拟"],
            command=self.on_category_change,
            variable=self.category_var,
            corner_radius=8,
            height=32
        )
        self.category_selector.pack(pady=(10, 16), padx=10, fill="x")
        
        # 优化下拉框宽度
        optimize_combobox_width(self.category_selector, offset=200)

        # 创建两个容器用于切换显示
        self.container_system = ctk.CTkFrame(self, fg_color="transparent")
        self.container_simulation = ctk.CTkFrame(self, fg_color="transparent")

        # 初始化各部分 UI
        self._init_system_ui()
        self._init_simulation_ui()

        # 初始化显示状态
        self.on_category_change(self.category_var.get())

    def _init_system_ui(self):
        # 1. 设备检查与输入
        frame_dev = ctk.CTkFrame(self.container_system)
        frame_dev.pack(pady=5, padx=10, fill="x")
        
        frame_dev_header = ctk.CTkFrame(frame_dev, fg_color="transparent")
        frame_dev_header.pack(pady=(5, 2), padx=10, fill="x")
        ctk.CTkLabel(frame_dev_header, text="文本输入", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.help_btn = ctk.CTkButton(frame_dev_header, text="?", width=28, height=28, corner_radius=14, fg_color="gray50", hover_color="gray40", command=lambda: None)
        self.help_btn.pack(side="left", padx=(5, 0))
        ModernTooltip(self.help_btn, sections=[
            ("模拟按键输入 (仅 ASCII)",
             "通过 adb shell input text 逐字符模拟按键，无需安装。\n"
             "仅支持英文字母、数字和常见符号。\n"
             "使用前请将设备键盘切换到英文输入法。"),
            ("ADB Keyboard (支持所有语言)",
             "通过 ADB Keyboard 广播发送，支持中文、俄语等所有语言。\n"
             "首次使用会自动安装 ADB Keyboard APK。\n"
             "部分设备（如 OPPO）需手动在设置中切换默认输入法。"),
        ])

        # 发送文本 - 模拟按键模式
        ctk.CTkLabel(frame_dev, text="模拟按键输入 (仅支持英文字母、数字和常见符号，无需安装)", font=ctk.CTkFont(size=12), text_color="gray").pack(pady=(5, 0), anchor="w", padx=10)
        raw_input_frame = ctk.CTkFrame(frame_dev, fg_color="transparent")
        raw_input_frame.pack(pady=(0, 2), padx=10, fill="x")
        self.entry_raw_input_text = ctk.CTkEntry(raw_input_frame, placeholder_text="输入要发送的文本...")
        self.entry_raw_input_text.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(raw_input_frame, text="发送", width=60, command=self.action_send_raw_text).pack(side="right")
        ctk.CTkButton(raw_input_frame, text="x", width=20, height=20, fg_color="transparent", hover_color="gray70", text_color="gray50", font=ctk.CTkFont(size=11), command=lambda: self.entry_raw_input_text.delete(0, "end")).pack(side="right", padx=(0, 2))

        # 发送文本 - ADB Keyboard 模式
        ctk.CTkLabel(frame_dev, text="ADB Keyboard (支持所有语言)", font=ctk.CTkFont(size=12), text_color="gray").pack(pady=(5, 0), anchor="w", padx=10)
        input_frame = ctk.CTkFrame(frame_dev, fg_color="transparent")
        input_frame.pack(pady=(0, 5), padx=10, fill="x")
        self.entry_input_text = ctk.CTkEntry(input_frame, placeholder_text="输入要发送的文本...")
        self.entry_input_text.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(input_frame, text="发送", width=60, command=self.action_send_text).pack(side="right")
        ctk.CTkButton(input_frame, text="x", width=20, height=20, fg_color="transparent", hover_color="gray70", text_color="gray50", font=ctk.CTkFont(size=11), command=lambda: self.entry_input_text.delete(0, "end")).pack(side="right", padx=(0, 2))

        # 1.5 文件传输 (Push 至设备)
        frame_push = ctk.CTkFrame(self.container_system)
        frame_push.pack(pady=5, padx=10, fill="x")
        
        ctk.CTkLabel(frame_push, text="文件传输 (Push 至设备)", font=ctk.CTkFont(weight="bold")).pack(pady=(5, 2), anchor="w", padx=10)
        
        # 目标路径设置
        path_frame = ctk.CTkFrame(frame_push, fg_color="transparent")
        path_frame.pack(pady=2, padx=10, fill="x")
        ctk.CTkLabel(path_frame, text="目标路径:").pack(side="left", padx=(0, 5))
        self.entry_remote_path = ctk.CTkEntry(path_frame)
        self.entry_remote_path.insert(0, "/sdcard/Download/")
        self.entry_remote_path.pack(side="left", fill="x", expand=True)
        
        # 拖拽感应区
        self.drop_zone = ctk.CTkFrame(frame_push, height=80, fg_color="#e0e0e0", border_width=2, border_color="#aaaaaa")
        self.drop_zone.pack(pady=(2, 5), padx=10, fill="x")
        self.drop_zone.pack_propagate(False) # 保持高度
        
        lbl_drop = ctk.CTkLabel(self.drop_zone, text="请将文件或文件夹拖拽至此区域自动导入", text_color="#555555")
        lbl_drop.place(relx=0.5, rely=0.5, anchor="center")
        
        # 注册拖拽事件 (假设主窗口已经初始化了 TkinterDnD)
        # 需要使用 tkdnd 的 DND_FILES 常量，通常通过 widget.drop_target_register 注册
        try:
            from tkinterdnd2 import DND_FILES
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind('<<Drop>>', self.on_files_dropped)
        except Exception as e:
            self.log(f"拖拽功能初始化失败，可能未安装 tkinterdnd2: {e}", "ERROR")

        # 设备文件管理器
        self.file_manager_btn = ctk.CTkButton(frame_push, text="设备文件导出", command=self.open_device_file_manager)
        self.file_manager_btn.pack(pady=(5, 5), padx=10, fill="x")

        # 4. 无线调试 (Wireless Debugging)
        frame_wireless = ctk.CTkFrame(self.container_system)
        frame_wireless.pack(pady=5, padx=10, fill="x")
        
        ctk.CTkLabel(frame_wireless, text="无线调试 (Wireless Debugging)", font=ctk.CTkFont(weight="bold")).pack(pady=(5, 2), anchor="w", padx=10)

        frame_wireless_btns = ctk.CTkFrame(frame_wireless, fg_color="transparent")
        frame_wireless_btns.pack(pady=(2, 5), padx=10, fill="x")
        frame_wireless_btns.grid_columnconfigure(0, weight=1, uniform="wb")
        frame_wireless_btns.grid_columnconfigure(1, weight=1, uniform="wb")

        ctk.CTkButton(frame_wireless_btns, text="开启无线调试", command=self.action_start_wireless_debug).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ctk.CTkButton(frame_wireless_btns, text="关闭无线调试", command=self.action_stop_wireless_debug, fg_color="#c42b1c", hover_color="#8a1f15").grid(row=0, column=1, sticky="ew", padx=(2, 0))

        # 5. 系统工具
        frame_sys = ctk.CTkFrame(self.container_system)
        frame_sys.pack(pady=5, padx=10, fill="x")
        
        ctk.CTkLabel(frame_sys, text="系统工具", font=ctk.CTkFont(weight="bold")).pack(pady=(5, 2), anchor="w", padx=10)
        
        ctk.CTkButton(frame_sys, text="清除 Google Play 数据",
                      command=self.action_clear_google_play,
                      fg_color="#e0a800", hover_color="#b08800").pack(pady=2, padx=10, fill="x")

        ctk.CTkButton(frame_sys, text="查询设备系统版本",
                      command=self.action_query_device_info).pack(pady=(2, 5), padx=10, fill="x")

    def _init_simulation_ui(self):
        sim_btn_h = 28  # 紧凑按钮高度

        # 唤起系统时间设置
        ctk.CTkButton(self.container_simulation, text="唤起系统时间与日期设置", height=sim_btn_h,
                      command=self.action_open_date_settings).pack(pady=(6, 3), padx=10, fill="x")

        # 1.5 弱网/断网模拟
        frame_proxy = ctk.CTkFrame(self.container_simulation)
        frame_proxy.pack(pady=3, padx=10, fill="x")

        proxy_header = ctk.CTkFrame(frame_proxy, fg_color="transparent")
        proxy_header.pack(pady=(4, 1), padx=8, fill="x")
        ctk.CTkLabel(proxy_header, text="弱网/断网模拟", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.lbl_proxy_status = ctk.CTkLabel(proxy_header, text="当前状态：检测中...", font=ctk.CTkFont(size=11), text_color="gray", cursor="hand2")
        self.lbl_proxy_status.pack(side="left", padx=(8, 0))
        # 点击状态文字 = 手动重新从设备读取 settings 并刷新
        self.lbl_proxy_status.bind("<Button-1>", lambda e: self.refresh_proxy_status(verbose=True))

        # 第一行：假代理（模拟高延迟/慢网）
        row_proxy = ctk.CTkFrame(frame_proxy, fg_color="transparent")
        row_proxy.pack(pady=(1, 2), padx=8, fill="x")
        ctk.CTkButton(row_proxy, text="开启高延迟/慢网", height=sim_btn_h, command=self.action_enable_fake_proxy).pack(side="left", expand=True, fill="x", padx=(0, 2))
        ctk.CTkButton(row_proxy, text="清除假代理", height=sim_btn_h, fg_color="#c42b1c", hover_color="#8a1f15", command=self.action_disable_fake_proxy).pack(side="right", expand=True, fill="x", padx=(2, 0))

        # 第二行：假 DNS（模拟网络超时 / 彻底断网）
        row_dns = ctk.CTkFrame(frame_proxy, fg_color="transparent")
        row_dns.pack(pady=(0, 4), padx=8, fill="x")
        ctk.CTkButton(row_dns, text="开启网络超时", height=sim_btn_h, command=self.action_enable_fake_dns).pack(side="left", expand=True, fill="x", padx=(0, 2))
        ctk.CTkButton(row_dns, text="恢复正常DNS", height=sim_btn_h, fg_color="#c42b1c", hover_color="#8a1f15", command=self.action_disable_fake_dns).pack(side="right", expand=True, fill="x", padx=(2, 0))

        # 首次加载时检测一次当前代理 / DNS 状态
        self.after(500, self.refresh_proxy_status)

        # 2. 电池模拟
        frame_bat = ctk.CTkFrame(self.container_simulation)
        frame_bat.pack(pady=3, padx=10, fill="x")

        ctk.CTkLabel(frame_bat, text="电池状态模拟", font=ctk.CTkFont(weight="bold")).pack(pady=(4, 1), anchor="w", padx=8)

        ctk.CTkButton(frame_bat, text="模拟低电量 (10%)", height=sim_btn_h, command=self.adb_helper.sim_low_battery).pack(pady=1, padx=8, fill="x")
        ctk.CTkButton(frame_bat, text="模拟充满电 (100%)", height=sim_btn_h, command=self.adb_helper.sim_full_battery).pack(pady=1, padx=8, fill="x")
        ctk.CTkButton(frame_bat, text="恢复真实电量", height=sim_btn_h, fg_color="#c42b1c", hover_color="#8a1f15", command=self.adb_helper.reset_battery).pack(pady=(1, 4), padx=8, fill="x")

        # 2.5 来电模拟
        frame_call = ctk.CTkFrame(self.container_simulation)
        frame_call.pack(pady=3, padx=10, fill="x")

        ctk.CTkLabel(frame_call, text="来电模拟", font=ctk.CTkFont(weight="bold")).pack(pady=(4, 1), anchor="w", padx=8)

        ctk.CTkButton(frame_call, text="模拟来电 (RINGING)", height=sim_btn_h, command=self.adb_helper.sim_incoming_call).pack(pady=(1, 4), padx=8, fill="x")

        # 3. 网络模拟
        frame_net = ctk.CTkFrame(self.container_simulation)
        frame_net.pack(pady=3, padx=10, fill="x")

        ctk.CTkLabel(frame_net, text="Wi-Fi 模拟", font=ctk.CTkFont(weight="bold")).pack(pady=(4, 1), anchor="w", padx=8)

        grid_net = ctk.CTkFrame(frame_net, fg_color="transparent")
        grid_net.pack(pady=(1, 4), padx=8, fill="x")
        ctk.CTkButton(grid_net, text="断开 Wi-Fi", height=sim_btn_h, command=self.adb_helper.wifi_disable).pack(side="left", expand=True, fill="x", padx=(0, 2))
        ctk.CTkButton(grid_net, text="连接 Wi-Fi", height=sim_btn_h, command=self.adb_helper.wifi_enable).pack(side="right", expand=True, fill="x", padx=(2, 0))

        # 4. 铃声试听
        frame_ringtone = ctk.CTkFrame(self.container_simulation)
        frame_ringtone.pack(pady=3, padx=10, fill="x")

        ctk.CTkLabel(frame_ringtone, text="铃声试听", font=ctk.CTkFont(weight="bold")).pack(pady=(4, 1), anchor="w", padx=8)

        ctk.CTkButton(frame_ringtone, text="试听来电铃声", height=sim_btn_h, command=lambda: self.action_play_ringtone("ringtone")).pack(pady=1, padx=8, fill="x")
        ctk.CTkButton(frame_ringtone, text="试听通知铃声", height=sim_btn_h, command=lambda: self.action_play_ringtone("notification_sound")).pack(pady=1, padx=8, fill="x")
        ctk.CTkButton(frame_ringtone, text="试听闹钟铃声", height=sim_btn_h, command=lambda: self.action_play_ringtone("alarm_alert")).pack(pady=1, padx=8, fill="x")

        self.btn_contact_ringtone = ctk.CTkButton(frame_ringtone, text="试听联系人铃声", height=sim_btn_h, command=self.action_contact_ringtone)
        self.btn_contact_ringtone.pack(pady=(1, 4), padx=8, fill="x")

    def action_play_ringtone(self, sound_type):
        def _thread():
            try:
                # 1. 获取路径
                cmd = [self.adb_helper.adb_cmd, "-s", self.adb_helper.current_device_id, "shell", "settings", "get", "system", sound_type]
                
                kwargs = self.adb_helper._get_subprocess_kwargs()
                
                result = subprocess.run(cmd, **kwargs)
                if result.returncode != 0:
                    self.log(f"获取{sound_type}路径失败: {result.stderr}", "ERROR")
                    return
                
                raw_uri = result.stdout.strip()
                if not raw_uri or raw_uri == "null":
                    self.log(f"未设置{sound_type}或获取为空", "WARNING")
                    return
                
                # 2. 处理路径: 剔除 0@
                # 例如: content://0@media/... -> content://media/...
                if "0@" in raw_uri:
                    clean_uri = raw_uri.replace("0@", "")
                else:
                    clean_uri = raw_uri
                    
                self.log(f"获取到 URI: {clean_uri}", "INFO")
                
                # 3. 执行播放
                play_cmd = [self.adb_helper.adb_cmd, "-s", self.adb_helper.current_device_id, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", f"'{clean_uri}'", "-t", "audio/*"]
                play_result = subprocess.run(play_cmd, **kwargs)
                
                # am start 命令如果成功，通常会输出 "Starting: Intent { ... }"
                # 即使有 Warning (例如 Activity not started)，只要没有 Error，我们都可以认为是成功的
                if "Error" not in play_result.stderr and "Error" not in play_result.stdout:
                    self.log(f"正在播放{sound_type}...", "SUCCESS")
                else:
                    error_msg = play_result.stderr.strip() or play_result.stdout.strip()
                    self.log(f"播放可能失败: {error_msg}", "ERROR")
                    
            except Exception as e:
                self.log(f"试听铃声异常: {e}", "ERROR")
                
        threading.Thread(target=_thread, daemon=True).start()

    def on_files_dropped(self, event):
        """处理文件拖拽放下事件"""
        # TkinterDnD 会把多个路径用空格分隔，如果是带空格的路径会用 {} 包裹
        # 必须使用 tk.splitlist 来正确解析
        try:
            # event.widget.tk 是底层 tcl 解释器对象
            file_paths = event.widget.tk.splitlist(event.data)
        except Exception as e:
            self.log(f"解析拖拽路径失败: {e}", "ERROR")
            return
            
        if not file_paths:
            return
            
        remote_path = self.entry_remote_path.get().strip()
        if not remote_path:
            self.log("目标路径不能为空", "WARNING")
            return
            
        # 开启后台线程执行 push 操作
        def _push_thread():
            try:
                # 前置校验设备 (由于在非 UI 线程抛出异常不会导致主程序崩溃，可以直接在这里或者在 helper 里捕获)
                self.adb_helper.check_device()
                
                self.log(f"开始导入 {len(file_paths)} 个项目到设备: {remote_path} ...", "INFO")
                
                # 记录详细列表
                for i, path in enumerate(file_paths):
                    self.log(f"  [{i+1}/{len(file_paths)}] 准备导入: {path}", "INFO")
                
                success, msg = self.adb_helper.push_files(list(file_paths), remote_path)
                
                if success:
                    self.log(f"成功导入 {len(file_paths)} 个项目", "SUCCESS")
                else:
                    self.log(f"导入完成，但存在错误: {msg}", "WARNING")
                    
            except Exception as e: # 捕获 NoDeviceConnectedError 等异常
                self.log(f"导入文件中止或异常: {e}", "ERROR")
                
        threading.Thread(target=_push_thread, daemon=True).start()

    def on_category_change(self, value):
        if value == "设备与系统控制":
            self.container_simulation.pack_forget()
            self.container_system.pack(fill="both", expand=True)
        elif value == "环境与状态模拟":
            self.container_system.pack_forget()
            self.container_simulation.pack(fill="both", expand=True)

    def action_send_text(self):
        text = self.entry_input_text.get()
        if not text:
            messagebox.showwarning("提示", "请输入要发送的文本", parent=self)
            return

        # 检查是否需要安装 ADB Keyboard（首次使用时弹出提示）
        _, output = self.adb_helper.execute_adb_command(["adb", "shell", "pm", "list", "packages", self.adb_helper.ADB_KB_PKG])
        need_install = self.adb_helper.ADB_KB_PKG not in (output or "")

        loading_dialog = None
        if need_install:
            loading_dialog = ctk.CTkToplevel(self)
            loading_dialog.title("请稍候")
            loading_dialog.geometry("300x100")
            loading_dialog.resizable(False, False)
            loading_dialog.transient(self.winfo_toplevel())
            loading_dialog.grab_set()
            loading_dialog.update_idletasks()
            x = self.winfo_rootx() + (self.winfo_width() // 2) - 150
            y = self.winfo_rooty() + (self.winfo_height() // 2) - 50
            loading_dialog.geometry(f"+{x}+{y}")
            ctk.CTkLabel(loading_dialog, text="正在安装 ADB Keyboard...\n首次使用需要安装，请稍候", font=ctk.CTkFont(size=13)).pack(expand=True)

        def _thread():
            try:
                self.adb_helper.send_text(text)
                self.log(f"已发送文本: {text}", "SUCCESS")
            except Exception as e:
                self.log(f"发送文本异常: {e}", "ERROR")
            finally:
                if loading_dialog:
                    self.after(0, loading_dialog.destroy)

        threading.Thread(target=_thread, daemon=True).start()

    def action_send_raw_text(self):
        text = self.entry_raw_input_text.get()
        if not text:
            messagebox.showwarning("提示", "请输入要发送的文本", parent=self)
            return
        def _thread():
            try:
                self.adb_helper.send_raw_text(text)
                self.log(f"已通过模拟按键发送: {text}", "SUCCESS")
            except Exception as e:
                self.log(f"模拟按键发送异常: {e}", "ERROR")
        threading.Thread(target=_thread, daemon=True).start()

    def action_start_wireless_debug(self):
        # 检查是否已有无线连接的设备
        try:
            devices = self.adb_helper.get_connected_devices()
            wireless_devices = [d for d in devices if ":" in d]
            if wireless_devices:
                answer = messagebox.askyesnocancel(
                    "检测到无线设备",
                    f"当前已有无线连接的设备：\n{', '.join(wireless_devices)}\n\n是否断开现有无线连接后继续？\n\n是 → 断开并继续\n否 → 不断开，直接继续\n取消 → 取消操作",
                    parent=self
                )
                if answer is None:  # 取消
                    return
                if answer:  # 是，先断开
                    self.adb_helper.stop_wireless_debug()
                    self.main_window.refresh_device_list()
        except Exception:
            pass

        def on_ip_found(ip):
            # Show dialog in main thread
            self.after(0, lambda: self._prompt_unplug(ip))

        def on_failure(reason):
            if reason == "IP_NOT_FOUND":
                self.after(0, self._ask_manual_ip)
            else:
                self.after(0, lambda: messagebox.showerror("错误", f"无线调试启动失败: {reason}", parent=self))

        try:
            self.adb_helper.start_wireless_debug_flow(on_ip_found, on_failure, None)
        except Exception as e:
            self.log(f"开启无线调试异常: {e}", "ERROR")

    def _ask_manual_ip(self):
        dialog = ctk.CTkInputDialog(text="无法自动获取 IP 地址。\n请手动输入设备 IP (例如 192.168.x.x):", title="手动输入 IP")
        ip = dialog.get_input()
        if ip:
            self._prompt_unplug(ip)
        else:
            self.log("用户取消了手动 IP 输入", "WARNING")

    def _prompt_unplug(self, ip):
        # Prompt user to unplug USB
        if messagebox.askokcancel("准备连接", f"已获取设备 IP: {ip}\n\n请现在【拔掉 USB 数据线】，然后点击确定继续。", parent=self):
            try:
                self.adb_helper.connect_wireless_after_confirm(ip, self._on_connect_result)
            except Exception as e:
                self.log(f"连接无线调试异常: {e}", "ERROR")
        else:
            self.log("用户取消了无线调试连接", "WARNING")

    def _on_connect_result(self, success, ip):
        if success:
            self.after(0, lambda: self.main_window.refresh_device_list())
            self.after(0, lambda: messagebox.showinfo("成功", f"无线调试连接成功！\nIP: {ip}", parent=self))
        else:
            self.after(0, lambda: messagebox.showerror("失败", "无线调试连接失败，请重试。", parent=self))

    def action_stop_wireless_debug(self):
        def on_complete(count, error=None):
            if error:
                 self.after(0, lambda: messagebox.showerror("错误", f"发生异常: {error}", parent=self))
            elif count == 0:
                 self.after(0, lambda: messagebox.showinfo("提示", "当前没有已连接的无线调试设备", parent=self))
            else:
                 self.after(0, lambda: self.main_window.refresh_device_list())
                 self.after(0, lambda: messagebox.showinfo("成功", f"已断开 {count} 个无线设备连接", parent=self))
        
        self.adb_helper.stop_wireless_debug(on_complete)

    def action_clear_google_play(self):
        def _thread():
            try:
                success, _ = self.adb_helper.clear_google_play_data()
                if success:
                    self.log("Google Play 商店数据已成功清除！", "SUCCESS")
                else:
                    self.log("清除失败，请检查设备连接状态。", "ERROR")
            except Exception as e:
                self.log(f"清除 Google Play 数据异常: {e}", "ERROR")
        
        threading.Thread(target=_thread, daemon=True).start()

    FAKE_DNS_HOST = "fake.domain.test"

    def _run_adb_settings_cmd(self, args, action_label):
        """执行一条 adb settings 命令，打印命令与结果日志。返回 (ok, stdout)。"""
        device_id = self.adb_helper.current_device_id
        if not device_id:
            self.log(f"未选择设备，无法执行{action_label}", "ERROR")
            return False, ""
        cmd = [self.adb_helper.adb_cmd, "-s", device_id, "shell", "settings"] + list(args)
        self.log(f"执行命令: {' '.join(cmd)}", "INFO")
        try:
            kwargs = self.adb_helper._get_subprocess_kwargs()
            result = subprocess.run(cmd, **kwargs)
            if result.returncode == 0:
                out = (result.stdout or "").strip()
                self.log(f"结果: {out or 'Success'}", "SUCCESS")
                return True, out
            err = (result.stderr or "").strip() or "Failed"
            self.log(f"结果: {err}", "ERROR")
            return False, ""
        except Exception as e:
            self.log(f"{action_label}异常: {e}", "ERROR")
            return False, ""

    def action_enable_fake_proxy(self):
        """设置一个无效的 HTTP 代理以模拟高延迟/慢网"""
        def _thread():
            self._run_adb_settings_cmd(
                ["put", "global", "http_proxy", "1.1.1.1:9999"],
                "开启高延迟/慢网",
            )
            self.refresh_proxy_status(verbose=True)
        threading.Thread(target=_thread, daemon=True).start()

    def action_disable_fake_proxy(self):
        """清除 HTTP 代理"""
        def _thread():
            self._run_adb_settings_cmd(
                ["put", "global", "http_proxy", ":0"],
                "清除假代理",
            )
            self.refresh_proxy_status(verbose=True)
        threading.Thread(target=_thread, daemon=True).start()

    def action_enable_fake_dns(self):
        """将 Private DNS 指向不可解析的域名，模拟网络超时/彻底断网"""
        def _thread():
            ok1, _ = self._run_adb_settings_cmd(
                ["put", "global", "private_dns_mode", "hostname"],
                "开启网络超时",
            )
            if ok1:
                self._run_adb_settings_cmd(
                    ["put", "global", "private_dns_specifier", self.FAKE_DNS_HOST],
                    "开启网络超时",
                )
            self.refresh_proxy_status(verbose=True)
        threading.Thread(target=_thread, daemon=True).start()

    def action_disable_fake_dns(self):
        """恢复 Private DNS 为自动模式"""
        def _thread():
            self._run_adb_settings_cmd(
                ["put", "global", "private_dns_mode", "opportunistic"],
                "恢复正常DNS",
            )
            self.refresh_proxy_status(verbose=True)
        threading.Thread(target=_thread, daemon=True).start()

    def refresh_proxy_status(self, verbose=False):
        """后台执行 adb shell settings get 读取真实值，综合更新状态标签。

        verbose=True 时，会把 3 条查询的返回值合并成一行写入 Global Log，
        方便用户在日志面板直接看到状态标签是由哪些返回值推算出来的。
        """
        def _thread():
            try:
                device_id = self.adb_helper.current_device_id
                if not device_id:
                    self.after(0, lambda: self.lbl_proxy_status.configure(text="当前状态：无设备", text_color="gray"))
                    return

                kwargs = self.adb_helper._get_subprocess_kwargs()

                def get_setting(key):
                    r = subprocess.run(
                        [self.adb_helper.adb_cmd, "-s", device_id, "shell", "settings", "get", "global", key],
                        **kwargs,
                    )
                    return (r.stdout or "").strip()

                proxy_val = get_setting("http_proxy")
                dns_mode = get_setting("private_dns_mode")
                dns_spec = get_setting("private_dns_specifier")

                if verbose:
                    self.log(
                        f"状态查询: http_proxy={proxy_val or 'null'} | "
                        f"private_dns_mode={dns_mode or 'null'} | "
                        f"private_dns_specifier={dns_spec or 'null'}",
                        "INFO",
                    )

                proxy_active = bool(proxy_val) and proxy_val not in ("null", ":0")
                dns_active = (dns_mode == "hostname") and (dns_spec == self.FAKE_DNS_HOST)

                if proxy_active and dns_active:
                    text, color = "当前状态：混合异常生效中", "#c42b1c"
                elif proxy_active:
                    text, color = "当前状态：假代理生效中", "#c42b1c"
                elif dns_active:
                    text, color = "当前状态：假DNS生效中", "#c42b1c"
                else:
                    text, color = "当前状态：正常", "gray"

                self.after(0, lambda: self.lbl_proxy_status.configure(text=text, text_color=color))
            except Exception as e:
                if verbose:
                    self.log(f"状态查询异常: {e}", "ERROR")
                self.after(0, lambda: self.lbl_proxy_status.configure(text="当前状态：未知", text_color="gray"))
        threading.Thread(target=_thread, daemon=True).start()

    def action_open_date_settings(self):
        def _thread():
            try:
                self.adb_helper.open_date_settings()
                self.log("已唤起设备系统时间设置页", "SUCCESS")
            except Exception as e:
                self.log(f"唤起时间设置失败: {e}", "ERROR")
        threading.Thread(target=_thread, daemon=True).start()

    def action_query_device_info(self):
        def _thread():
            try:
                info = self.adb_helper.get_device_info()
                self.log(f"查询成功 -> {info}", "SUCCESS")
            except Exception as e:
                self.log(f"查询设备信息失败: {e}", "ERROR")

        threading.Thread(target=_thread, daemon=True).start()

    def action_contact_ringtone(self):
        self.btn_contact_ringtone.configure(state="disabled", text="⏳ 正在读取通讯录...")

        def _thread():
            try:
                contacts = self.adb_helper.get_all_contacts()
                if not contacts:
                    self.log("未能获取到通讯录数据，请检查手机是否为空或被系统拦截", "WARNING")
                    self.after(0, lambda: self.btn_contact_ringtone.configure(state="normal", text="试听联系人铃声"))
                    return

                self.log(f"成功获取 {len(contacts)} 个联系人", "SUCCESS")

                def _show_dialog():
                    self.btn_contact_ringtone.configure(state="normal", text="试听联系人铃声")
                    from ui.components.contact_selector import ContactRingtoneDialog
                    ContactRingtoneDialog(self, self.adb_helper, contacts, self.log)

                self.after(0, _show_dialog)
            except Exception as e:
                self.log(f"读取通讯录异常: {e}", "ERROR")
                self.after(0, lambda: self.btn_contact_ringtone.configure(state="normal", text="试听联系人铃声"))

        threading.Thread(target=_thread, daemon=True).start()

    def open_device_file_manager(self):
        from ui.components.file_manager_window import DeviceFileManagerWindow
        file_manager_window = DeviceFileManagerWindow(self, self.adb_helper, self.config_manager)
        file_manager_window.grab_set()
