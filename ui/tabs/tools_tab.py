import customtkinter as ctk
import tkinter.messagebox as messagebox
import threading
import subprocess
from ui.utils import optimize_combobox_width

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
        
        ctk.CTkLabel(frame_dev, text="设备与输入", font=ctk.CTkFont(weight="bold")).pack(pady=(5, 2), anchor="w", padx=10)
        ctk.CTkButton(frame_dev, text="检查设备连接 (adb devices)", command=lambda: self.adb_helper.run_adb_async(["adb", "devices"], check_dev=False)).pack(pady=2, padx=10, fill="x")
        
        # 发送文本
        input_frame = ctk.CTkFrame(frame_dev, fg_color="transparent")
        input_frame.pack(pady=(2, 5), padx=10, fill="x")
        self.entry_input_text = ctk.CTkEntry(input_frame, placeholder_text="输入要发送的文本...")
        self.entry_input_text.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(input_frame, text="发送", width=60, command=self.action_send_text).pack(side="right")

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
        
        ctk.CTkButton(frame_wireless, text="开启无线调试 (Connect TCP/IP)", command=self.action_start_wireless_debug).pack(pady=2, padx=10, fill="x")
        ctk.CTkButton(frame_wireless, text="关闭无线调试 (Disconnect TCP/IP)", command=self.action_stop_wireless_debug, fg_color="#c42b1c", hover_color="#8a1f15").pack(pady=(2, 5), padx=10, fill="x")

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
        # 唤起系统时间设置
        ctk.CTkButton(self.container_simulation, text="唤起系统时间与日期设置",
                      command=self.action_open_date_settings).pack(pady=5, padx=10, fill="x")

        # 2. 电池模拟
        frame_bat = ctk.CTkFrame(self.container_simulation)
        frame_bat.pack(pady=5, padx=10, fill="x")

        ctk.CTkLabel(frame_bat, text="电池状态模拟", font=ctk.CTkFont(weight="bold")).pack(pady=(5, 2), anchor="w", padx=10)
        
        ctk.CTkButton(frame_bat, text="模拟低电量 (10%)", command=self.adb_helper.sim_low_battery).pack(pady=2, padx=10, fill="x")
        ctk.CTkButton(frame_bat, text="模拟充满电 (100%)", command=self.adb_helper.sim_full_battery).pack(pady=2, padx=10, fill="x")
        ctk.CTkButton(frame_bat, text="恢复真实电量", fg_color="#c42b1c", hover_color="#8a1f15", command=self.adb_helper.reset_battery).pack(pady=(2, 5), padx=10, fill="x")

        # 3. 网络模拟
        frame_net = ctk.CTkFrame(self.container_simulation)
        frame_net.pack(pady=5, padx=10, fill="x")
        
        ctk.CTkLabel(frame_net, text="Wi-Fi 模拟", font=ctk.CTkFont(weight="bold")).pack(pady=(5, 2), anchor="w", padx=10)
        
        grid_net = ctk.CTkFrame(frame_net, fg_color="transparent")
        grid_net.pack(pady=(2, 5), padx=10, fill="x")
        ctk.CTkButton(grid_net, text="断开 Wi-Fi", command=self.adb_helper.wifi_disable).pack(side="left", expand=True, padx=2)
        ctk.CTkButton(grid_net, text="连接 Wi-Fi", command=self.adb_helper.wifi_enable).pack(side="right", expand=True, padx=2)

        # 4. 铃声试听
        frame_ringtone = ctk.CTkFrame(self.container_simulation)
        frame_ringtone.pack(pady=5, padx=10, fill="x")
        
        ctk.CTkLabel(frame_ringtone, text="铃声试听", font=ctk.CTkFont(weight="bold")).pack(pady=(5, 2), anchor="w", padx=10)
        
        ctk.CTkButton(frame_ringtone, text="试听来电铃声", command=lambda: self.action_play_ringtone("ringtone")).pack(pady=2, padx=10, fill="x")
        ctk.CTkButton(frame_ringtone, text="试听通知铃声", command=lambda: self.action_play_ringtone("notification_sound")).pack(pady=2, padx=10, fill="x")
        ctk.CTkButton(frame_ringtone, text="试听闹钟铃声", command=lambda: self.action_play_ringtone("alarm_alert")).pack(pady=2, padx=10, fill="x")

        self.btn_contact_ringtone = ctk.CTkButton(frame_ringtone, text="试听联系人铃声", command=self.action_contact_ringtone)
        self.btn_contact_ringtone.pack(pady=(2, 5), padx=10, fill="x")

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
        try:
            self.adb_helper.send_text(text)
            self.log(f"已发送文本: {text}", "SUCCESS")
        except Exception as e:
            self.log(f"发送文本异常: {e}", "ERROR")

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
