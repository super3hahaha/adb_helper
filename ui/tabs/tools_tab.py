import customtkinter as ctk
import tkinter.messagebox as messagebox
import threading
import subprocess
from ui.utils import optimize_combobox_width, attach_scrollable
from ui.components.tooltip import ModernTooltip
from core.throttle_proxy import ThrottleProxy

class ToolsTab(ctk.CTkFrame):
    def __init__(self, parent, adb_helper, config_manager, log_func):
        super().__init__(parent, corner_radius=10)
        self.main_window = parent
        self.adb_helper = adb_helper
        self.config_manager = config_manager
        self.log = log_func

        # 精确弱网限速代理（延迟到首次开启时才真正 start）
        self.shaper = ThrottleProxy(log=self.log)
        self._shaper_applied = None   # 上次已推给代理的 (delay, rate, loss)，用于去重
        # 代理指向的是哪台设备。shaper 服务本身是单例，关闭时必须回原设备清 http_proxy——
        # 若跟着下拉框走，会把代理留在原设备上而服务已停，那台设备直接断网
        self._shaper_device_id = None

        self.setup_ui()

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 滚动容器：窗口高度不足以容纳所有内容时自动显示滚动条
        self.scroll_container = attach_scrollable(self)
        self.scroll_container.grid(row=0, column=0, sticky="nsew")
        container = self.scroll_container

        # 0. 下拉选择框
        self.category_var = ctk.StringVar(value="设备与系统控制")
        self.category_selector = ctk.CTkOptionMenu(
            container,
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
        self.container_system = ctk.CTkFrame(container, fg_color="transparent")
        self.container_simulation = ctk.CTkFrame(container, fg_color="transparent")

        # 初始化各部分 UI
        self._init_system_ui()
        self._init_simulation_ui()

        # 初始化显示状态
        self.on_category_change(self.category_var.get())

    def _init_system_ui(self):
        sys_btn_h = 28  # 紧凑按钮高度

        # 1. 设备检查与输入
        frame_dev = ctk.CTkFrame(self.container_system)
        frame_dev.pack(pady=3, padx=10, fill="x")

        frame_dev_header = ctk.CTkFrame(frame_dev, fg_color="transparent")
        frame_dev_header.pack(pady=(4, 1), padx=8, fill="x")
        ctk.CTkLabel(frame_dev_header, text="文本输入", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.help_btn = ctk.CTkButton(frame_dev_header, text="?", width=22, height=22, corner_radius=11, fg_color="gray50", hover_color="gray40", command=lambda: None)
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
            ("获取并复制当前输入框内容",
             "通过 uiautomator dump 读取手机当前界面输入框的文本，复制到电脑剪贴板。\n"
             "优先取当前聚焦的输入框；密码类输入框读不到真实内容。"),
        ])

        # 发送文本 - 模拟按键模式
        ctk.CTkLabel(frame_dev, text="模拟按键输入 (仅支持英文字母、数字和常见符号，无需安装)", font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(2, 0), anchor="w", padx=8)
        raw_input_frame = ctk.CTkFrame(frame_dev, fg_color="transparent")
        raw_input_frame.pack(pady=(0, 1), padx=8, fill="x")
        self.entry_raw_input_text = ctk.CTkEntry(raw_input_frame, height=sys_btn_h, placeholder_text="输入要发送的文本...")
        self.entry_raw_input_text.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(raw_input_frame, text="发送", width=56, height=sys_btn_h, command=self.action_send_raw_text).pack(side="right")
        ctk.CTkButton(raw_input_frame, text="x", width=20, height=20, fg_color="transparent", hover_color="gray70", text_color="gray50", font=ctk.CTkFont(size=11), command=lambda: self.entry_raw_input_text.delete(0, "end")).pack(side="right", padx=(0, 2))

        # 发送文本 - ADB Keyboard 模式
        ctk.CTkLabel(frame_dev, text="ADB Keyboard (支持所有语言)", font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(2, 0), anchor="w", padx=8)
        input_frame = ctk.CTkFrame(frame_dev, fg_color="transparent")
        input_frame.pack(pady=(0, 1), padx=8, fill="x")
        self.entry_input_text = ctk.CTkEntry(input_frame, height=sys_btn_h, placeholder_text="输入要发送的文本...")
        self.entry_input_text.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(input_frame, text="发送", width=56, height=sys_btn_h, command=self.action_send_text).pack(side="right")
        ctk.CTkButton(input_frame, text="x", width=20, height=20, fg_color="transparent", hover_color="gray70", text_color="gray50", font=ctk.CTkFont(size=11), command=lambda: self.entry_input_text.delete(0, "end")).pack(side="right", padx=(0, 2))

        # 获取当前输入框内容
        get_input_frame = ctk.CTkFrame(frame_dev, fg_color="transparent")
        get_input_frame.pack(pady=(0, 4), padx=8, fill="x")
        ctk.CTkButton(get_input_frame, text="获取并复制当前输入框内容", height=sys_btn_h, command=self.action_get_input_text).pack(fill="x")

        # 1.5 文件传输 (Push 至设备)
        frame_push = ctk.CTkFrame(self.container_system)
        frame_push.pack(pady=3, padx=10, fill="x")

        ctk.CTkLabel(frame_push, text="文件传输 (Push 至设备)", font=ctk.CTkFont(weight="bold")).pack(pady=(4, 1), anchor="w", padx=8)

        # 目标路径设置
        self.DEFAULT_PUSH_PATH = "/sdcard/Download/"
        path_frame = ctk.CTkFrame(frame_push, fg_color="transparent")
        path_frame.pack(pady=1, padx=8, fill="x")
        ctk.CTkLabel(path_frame, text="目标路径:").pack(side="left", padx=(0, 5))
        self.entry_remote_path = ctk.CTkEntry(path_frame, height=sys_btn_h)
        saved_push_path = self.config_manager.get_default_device_push_path()
        self.entry_remote_path.insert(0, saved_push_path)
        self.entry_remote_path.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(path_frame, text="↺", width=28, height=sys_btn_h, font=ctk.CTkFont(size=14), command=self._reset_push_path).pack(side="left", padx=(3, 0))

        # 拖拽感应区
        self.drop_zone = ctk.CTkFrame(frame_push, height=70, fg_color="#e0e0e0", border_width=2, border_color="#aaaaaa")
        self.drop_zone.pack(pady=(2, 3), padx=8, fill="x")
        self.drop_zone.pack_propagate(False) # 保持高度

        lbl_drop = ctk.CTkLabel(self.drop_zone, text="请将文件或文件夹拖拽至此区域自动导入", font=ctk.CTkFont(size=11), text_color="#555555")
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
        self.file_manager_btn = ctk.CTkButton(frame_push, text="设备文件导出", height=sys_btn_h, command=self.open_device_file_manager)
        self.file_manager_btn.pack(pady=(2, 4), padx=8, fill="x")

        # 4. 无线调试 (Wireless Debugging)
        frame_wireless = ctk.CTkFrame(self.container_system)
        frame_wireless.pack(pady=3, padx=10, fill="x")

        ctk.CTkLabel(frame_wireless, text="无线调试 (Wireless Debugging)", font=ctk.CTkFont(weight="bold")).pack(pady=(4, 1), anchor="w", padx=8)

        frame_wireless_btns = ctk.CTkFrame(frame_wireless, fg_color="transparent")
        frame_wireless_btns.pack(pady=(1, 4), padx=8, fill="x")
        frame_wireless_btns.grid_columnconfigure(0, weight=1, uniform="wb")
        frame_wireless_btns.grid_columnconfigure(1, weight=1, uniform="wb")

        ctk.CTkButton(frame_wireless_btns, text="开启无线调试", height=sys_btn_h, command=self.action_start_wireless_debug).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ctk.CTkButton(frame_wireless_btns, text="无线设备管理", height=sys_btn_h, command=self.action_manage_wireless).grid(row=0, column=1, sticky="ew", padx=(2, 0))

        # 5. 系统工具
        frame_sys = ctk.CTkFrame(self.container_system)
        frame_sys.pack(pady=3, padx=10, fill="x")

        ctk.CTkLabel(frame_sys, text="系统工具", font=ctk.CTkFont(weight="bold")).pack(pady=(4, 1), anchor="w", padx=8)

        frame_sys_query_btns = ctk.CTkFrame(frame_sys, fg_color="transparent")
        frame_sys_query_btns.pack(pady=1, padx=8, fill="x")
        frame_sys_query_btns.grid_columnconfigure(0, weight=1, uniform="sys_query")
        frame_sys_query_btns.grid_columnconfigure(1, weight=1, uniform="sys_query")
        ctk.CTkButton(frame_sys_query_btns, text="查询设备系统版本", height=sys_btn_h,
                      command=self.action_query_device_info).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        self.btn_screen_info = ctk.CTkButton(frame_sys_query_btns, text="屏幕信息", height=sys_btn_h,
                                              command=self.action_show_screen_info)
        self.btn_screen_info.grid(row=0, column=1, sticky="ew", padx=(2, 0))

        frame_nav_btns = ctk.CTkFrame(frame_sys, fg_color="transparent")
        frame_nav_btns.pack(pady=(1, 1), padx=8, fill="x")
        frame_nav_btns.grid_columnconfigure(0, weight=1, uniform="nav")
        frame_nav_btns.grid_columnconfigure(1, weight=1, uniform="nav")
        ctk.CTkButton(frame_nav_btns, text="切换全面屏手势", height=sys_btn_h,
                      command=self.action_enable_gesture_nav).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ctk.CTkButton(frame_nav_btns, text="切换为三键导航", height=sys_btn_h,
                      command=self.action_enable_threebutton_nav).grid(row=0, column=1, sticky="ew", padx=(2, 0))

        frame_lang_btns = ctk.CTkFrame(frame_sys, fg_color="transparent")
        frame_lang_btns.pack(pady=(1, 4), padx=8, fill="x")
        frame_lang_btns.grid_columnconfigure(0, weight=1, uniform="lang")
        frame_lang_btns.grid_columnconfigure(1, weight=1, uniform="lang")
        ctk.CTkButton(frame_lang_btns, text="切换系统语言", height=sys_btn_h,
                      command=self.action_open_language_settings).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ctk.CTkButton(frame_lang_btns, text="唤起系统时间与日期设置", height=sys_btn_h,
                      command=self.action_open_date_settings).grid(row=0, column=1, sticky="ew", padx=(2, 0))

    def _init_simulation_ui(self):
        sim_btn_h = 28  # 紧凑按钮高度

        # 1.5 弱网/断网模拟
        frame_proxy = ctk.CTkFrame(self.container_simulation)
        frame_proxy.pack(pady=2, padx=10, fill="x")

        proxy_header = ctk.CTkFrame(frame_proxy, fg_color="transparent")
        proxy_header.pack(pady=(2, 1), padx=8, fill="x")
        ctk.CTkLabel(proxy_header, text="弱网/断网模拟", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.proxy_help_btn = ctk.CTkButton(proxy_header, text="?", width=22, height=22, corner_radius=11, fg_color="gray50", hover_color="gray40", command=lambda: None)
        self.proxy_help_btn.pack(side="left", padx=(5, 0))
        ModernTooltip(self.proxy_help_btn, sections=[
            ("开启高延迟/慢网",
             "把系统全局 HTTP 代理指向一个连不上的假地址，App 发 HTTP(S) 请求时会去连这个无效代理，卡着重试，表现为“慢、高延迟”。\n"
             "只作用在代理层，只影响走代理的 HTTP(S) 流量；不走代理的直连/非 HTTP 流量可能还是通的，相对较轻。\n"
             "不能设置具体延迟数值，只是一种粗糙的“卡顿”模拟。"),
            ("开启网络超时",
             "把 Android 的 Private DNS 强制指向一个不存在的域名，导致设备所有 DNS 解析失败。\n"
             "作用在 DNS 解析层，几乎所有联网请求都会解析失败、完不成，表现为“断网/超时”，比高延迟/慢网更彻底。"),
            ("精确弱网模拟",
             "起一个真正能转发流量的本地代理（非假地址），设备把 HTTP(S) 流量指过来后，在转发字节的过程中人为注入可配置的延迟(ms)/限速(KB/s)/丢包率(%)。\n"
             "和上面两个“制造故障”的取巧方案不同，这个能设具体参数、精确复现某种网络质量，而不是简单地卡死或断网。\n"
             "同样只覆盖走代理的 HTTP(S) 流量，UDP/QUIC、直连流量不受影响。"),
        ])
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
        row_dns.pack(pady=(0, 2), padx=8, fill="x")
        ctk.CTkButton(row_dns, text="开启网络超时", height=sim_btn_h, command=self.action_enable_fake_dns).pack(side="left", expand=True, fill="x", padx=(0, 2))
        ctk.CTkButton(row_dns, text="恢复正常DNS", height=sim_btn_h, fg_color="#c42b1c", hover_color="#8a1f15", command=self.action_disable_fake_dns).pack(side="right", expand=True, fill="x", padx=(2, 0))

        # 首次加载时检测一次当前代理 / DNS 状态
        self.after(500, self.refresh_proxy_status)

        # 1.6 精确弱网模拟（本机限速代理，可设具体延迟/限速/丢包）
        self._init_shaper_ui(sim_btn_h)

        # 2. 电池模拟
        frame_bat = ctk.CTkFrame(self.container_simulation)
        frame_bat.pack(pady=2, padx=10, fill="x")

        ctk.CTkLabel(frame_bat, text="电池状态模拟", font=ctk.CTkFont(weight="bold")).pack(pady=(2, 1), anchor="w", padx=8)

        row_bat = ctk.CTkFrame(frame_bat, fg_color="transparent")
        row_bat.pack(pady=1, padx=8, fill="x")
        ctk.CTkButton(row_bat, text="模拟低电量 (10%)", height=sim_btn_h, command=self.adb_helper.sim_low_battery).pack(side="left", expand=True, fill="x", padx=(0, 2))
        ctk.CTkButton(row_bat, text="模拟充满电 (100%)", height=sim_btn_h, command=self.adb_helper.sim_full_battery).pack(side="right", expand=True, fill="x", padx=(2, 0))
        ctk.CTkButton(frame_bat, text="恢复真实电量", height=sim_btn_h, fg_color="#c42b1c", hover_color="#8a1f15", command=self.adb_helper.reset_battery).pack(pady=(1, 2), padx=8, fill="x")

        # 2.5 来电模拟
        frame_call = ctk.CTkFrame(self.container_simulation)
        frame_call.pack(pady=2, padx=10, fill="x")

        ctk.CTkLabel(frame_call, text="来电模拟", font=ctk.CTkFont(weight="bold")).pack(pady=(2, 1), anchor="w", padx=8)

        ctk.CTkButton(frame_call, text="模拟来电 (RINGING)", height=sim_btn_h, command=self.adb_helper.sim_incoming_call).pack(pady=(1, 2), padx=8, fill="x")

        # 3. 网络模拟
        frame_net = ctk.CTkFrame(self.container_simulation)
        frame_net.pack(pady=2, padx=10, fill="x")

        ctk.CTkLabel(frame_net, text="Wi-Fi 模拟", font=ctk.CTkFont(weight="bold")).pack(pady=(2, 1), anchor="w", padx=8)

        grid_net = ctk.CTkFrame(frame_net, fg_color="transparent")
        grid_net.pack(pady=(1, 2), padx=8, fill="x")
        ctk.CTkButton(grid_net, text="断开 Wi-Fi", height=sim_btn_h, command=self.adb_helper.wifi_disable).pack(side="left", expand=True, fill="x", padx=(0, 2))
        ctk.CTkButton(grid_net, text="连接 Wi-Fi", height=sim_btn_h, command=self.adb_helper.wifi_enable).pack(side="right", expand=True, fill="x", padx=(2, 0))

        # 4. 铃声试听
        frame_ringtone = ctk.CTkFrame(self.container_simulation)
        frame_ringtone.pack(pady=2, padx=10, fill="x")

        ctk.CTkLabel(frame_ringtone, text="铃声试听", font=ctk.CTkFont(weight="bold")).pack(pady=(2, 1), anchor="w", padx=8)

        row_ring1 = ctk.CTkFrame(frame_ringtone, fg_color="transparent")
        row_ring1.pack(pady=1, padx=8, fill="x")
        ctk.CTkButton(row_ring1, text="试听来电铃声", height=sim_btn_h, command=lambda: self.action_play_ringtone("ringtone")).pack(side="left", expand=True, fill="x", padx=(0, 2))
        ctk.CTkButton(row_ring1, text="试听通知铃声", height=sim_btn_h, command=lambda: self.action_play_ringtone("notification_sound")).pack(side="right", expand=True, fill="x", padx=(2, 0))

        row_ring2 = ctk.CTkFrame(frame_ringtone, fg_color="transparent")
        row_ring2.pack(pady=(1, 2), padx=8, fill="x")
        ctk.CTkButton(row_ring2, text="试听闹钟铃声", height=sim_btn_h, command=lambda: self.action_play_ringtone("alarm_alert")).pack(side="left", expand=True, fill="x", padx=(0, 2))
        self.btn_contact_ringtone = ctk.CTkButton(row_ring2, text="试听联系人铃声", height=sim_btn_h, command=self.action_contact_ringtone)
        self.btn_contact_ringtone.pack(side="right", expand=True, fill="x", padx=(2, 0))

    def action_play_ringtone(self, sound_type):
        def _thread():
            try:
                # 1. 获取路径
                cmd = [self.adb_helper.adb_cmd, "-s", self.adb_helper.active_device_id, "shell", "settings", "get", "system", sound_type]
                
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
                play_cmd = [self.adb_helper.adb_cmd, "-s", self.adb_helper.active_device_id, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", f"'{clean_uri}'", "-t", "audio/*"]
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
                
        self.adb_helper.spawn(_thread)

    def _reset_push_path(self):
        self.entry_remote_path.delete(0, "end")
        self.entry_remote_path.insert(0, self.DEFAULT_PUSH_PATH)
        self.config_manager.set_default_device_push_path(self.DEFAULT_PUSH_PATH)

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

        if remote_path != self.config_manager.get_default_device_push_path():
            self.config_manager.set_default_device_push_path(remote_path)

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
                
        self.adb_helper.spawn(_push_thread)

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

        self.adb_helper.spawn(_thread)

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
        self.adb_helper.spawn(_thread)

    def action_get_input_text(self):
        def _thread():
            try:
                success, result = self.adb_helper.get_focused_input_text()
            except Exception as e:
                success, result = False, str(e)

            def _finish():
                if success:
                    self.clipboard_clear()
                    self.clipboard_append(result)
                    self.update()  # 确保剪贴板内容驻留
                    if result:
                        self.log(f"已获取并复制输入框内容: {result}", "SUCCESS")
                    else:
                        self.log("输入框内容为空，已复制空字符串到剪贴板", "SUCCESS")
                else:
                    self.log(f"获取输入框内容失败: {result}", "ERROR")
            self.after(0, _finish)

        self.adb_helper.spawn(_thread)

    def action_start_wireless_debug(self):
        """为当前选中的设备开启无线调试。

        不再检查/劝退"已有其它无线设备"——多台设备各自 IP 共用 5555 端口互不冲突，
        并存是正常状态。要断开某几台请用「无线设备管理」。
        """
        device_id = self.adb_helper.current_device_id
        if not device_id:
            messagebox.showerror("错误", "请先在顶部选择要开启无线调试的设备", parent=self)
            return

        if self.adb_helper.is_wireless_device_id(device_id):
            messagebox.showinfo(
                "提示",
                f"当前选中的 {device_id} 本身就是无线连接。\n"
                "请先在顶部切换到该设备的 USB 条目，或用「无线设备管理」手动连接。",
                parent=self,
            )
            return

        def on_ip_found(addr, dev):
            self.after(0, lambda: self._connect_wireless(addr, dev))

        def on_failure(reason):
            if reason == "IP_NOT_FOUND":
                self.after(0, lambda: self._ask_manual_ip(device_id))
            else:
                self.after(0, lambda: messagebox.showerror("错误", f"无线调试启动失败: {reason}", parent=self))

        try:
            self.adb_helper.start_wireless_debug_flow(on_ip_found, on_failure, device_id=device_id)
        except Exception as e:
            self.log(f"开启无线调试异常: {e}", "ERROR")

    def _ask_manual_ip(self, device_id=None):
        dialog = ctk.CTkInputDialog(
            text="无法自动获取 IP 地址。\n请手动输入设备 IP (例如 192.168.x.x):",
            title="手动输入 IP",
        )
        ip = dialog.get_input()
        if not ip:
            self.log("用户取消了手动 IP 输入", "WARNING")
            return
        addr = self.adb_helper.normalize_wireless_addr(ip)
        if not addr:
            messagebox.showerror("错误", "IP 格式非法，应形如 192.168.1.5 或 192.168.1.5:5555", parent=self)
            return
        self._connect_wireless(addr, device_id)

    def _connect_wireless(self, addr, device_id=None):
        """直接连接，不再要求先拔 USB。

        adb 允许同一台机器 USB 与 WiFi 两条 entry 并存，多设备下强制拔线既没必要
        又会打断流程；连上之后再提示用户"可以拔线了"。
        """
        try:
            self.adb_helper.connect_wireless(
                addr,
                lambda ok, a, msg: self._on_connect_result(ok, a, msg, device_id),
                device_id=device_id,
            )
        except Exception as e:
            self.log(f"连接无线调试异常: {e}", "ERROR")

    def _on_connect_result(self, success, addr, message="", device_id=None):
        def _finish():
            if not success:
                messagebox.showerror("失败", f"无线调试连接失败：{addr}\n{message}", parent=self)
                return
            # 记下地址，之后可在「无线设备管理」里一键重连，不用再插 USB
            try:
                self.config_manager.add_wireless_device(
                    addr, alias=self.main_window.resolve_device_alias(device_id or "")
                )
            except Exception:
                pass
            self.main_window.refresh_device_list()
            messagebox.showinfo(
                "成功",
                f"无线调试连接成功！\n地址: {addr}\n\n现在可以拔掉这台设备的 USB 数据线了。",
                parent=self,
            )

        self.after(0, _finish)

    def action_manage_wireless(self):
        from ui.components.wireless_manager_window import WirelessManagerWindow

        win = getattr(self, "wireless_manager_window", None)
        if win and win.winfo_exists():
            win.lift()
            win.focus_force()
            win.refresh()
            return

        self.wireless_manager_window = WirelessManagerWindow(
            self,
            self.adb_helper,
            self.config_manager,
            log_func=self.log,
            on_changed=self.main_window.refresh_device_list,
            alias_resolver=self.main_window.resolve_device_alias,
        )

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

        self.adb_helper.spawn(_thread)

    def action_enable_gesture_nav(self):
        def _thread():
            try:
                success, output = self.adb_helper.enable_gesture_nav()
                if success:
                    self.log("已切换为全面屏手势导航", "SUCCESS")
                else:
                    self.log(f"切换全面屏手势失败: {output}", "ERROR")
            except Exception as e:
                self.log(f"切换全面屏手势异常: {e}", "ERROR")
        self.adb_helper.spawn(_thread)

    def action_enable_threebutton_nav(self):
        def _thread():
            try:
                success, output = self.adb_helper.enable_threebutton_nav()
                if success:
                    self.log("已切换为三键导航", "SUCCESS")
                else:
                    self.log(f"切换三键导航失败: {output}", "ERROR")
            except Exception as e:
                self.log(f"切换三键导航异常: {e}", "ERROR")
        self.adb_helper.spawn(_thread)

    FAKE_DNS_HOST = "fake.domain.test"

    def _run_adb_settings_cmd(self, args, action_label):
        """执行一条 adb settings 命令，打印命令与结果日志。返回 (ok, stdout)。"""
        device_id = self.adb_helper.active_device_id
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
        self.adb_helper.spawn(_thread)

    def action_disable_fake_proxy(self):
        """清除 HTTP 代理"""
        def _thread():
            self._run_adb_settings_cmd(
                ["put", "global", "http_proxy", ":0"],
                "清除假代理",
            )
            self.refresh_proxy_status(verbose=True)
        self.adb_helper.spawn(_thread)

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
        self.adb_helper.spawn(_thread)

    def action_disable_fake_dns(self):
        """恢复 Private DNS 为自动模式"""
        def _thread():
            self._run_adb_settings_cmd(
                ["put", "global", "private_dns_mode", "opportunistic"],
                "恢复正常DNS",
            )
            self.refresh_proxy_status(verbose=True)
        self.adb_helper.spawn(_thread)

    def refresh_proxy_status(self, verbose=False):
        """后台执行 adb shell settings get 读取真实值，综合更新状态标签。

        verbose=True 时，会把 3 条查询的返回值合并成一行写入 Global Log，
        方便用户在日志面板直接看到状态标签是由哪些返回值推算出来的。
        """
        def _thread():
            try:
                device_id = self.adb_helper.active_device_id
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
        self.adb_helper.spawn(_thread)

    # ==================== 精确弱网模拟（限速代理） ====================

    def _init_shaper_ui(self, sim_btn_h):
        frame = ctk.CTkFrame(self.container_simulation)
        frame.pack(pady=2, padx=10, fill="x")

        # 标题行 + 状态
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(pady=(2, 1), padx=8, fill="x")
        ctk.CTkLabel(header, text="精确弱网模拟", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.lbl_shaper_status = ctk.CTkLabel(header, text="未开启", font=ctk.CTkFont(size=11), text_color="gray")
        self.lbl_shaper_status.pack(side="left", padx=(8, 0))

        # 参数输入行：延迟 / 限速 / 丢包
        row_params = ctk.CTkFrame(frame, fg_color="transparent")
        row_params.pack(pady=(0, 2), padx=8, fill="x")
        self.var_delay = ctk.StringVar(value="500")
        self.var_rate = ctk.StringVar(value="32")
        self.var_loss = ctk.StringVar(value="5")
        for label, var in (("延迟ms", self.var_delay), ("限速KB/s", self.var_rate), ("丢包%", self.var_loss)):
            cell = ctk.CTkFrame(row_params, fg_color="transparent")
            cell.pack(side="left", expand=True, fill="x", padx=1)
            ctk.CTkLabel(cell, text=label, font=ctk.CTkFont(size=10), text_color="gray").pack(anchor="w")
            entry = ctk.CTkEntry(cell, textvariable=var, height=26)
            entry.pack(fill="x")
            # 代理运行中时，改完参数（失焦或回车）即自动生效，无需再点按钮
            entry.bind("<FocusOut>", self._on_shaper_param_change)
            entry.bind("<Return>", self._on_shaper_param_change)

        # 操作按钮行
        row_btns = ctk.CTkFrame(frame, fg_color="transparent")
        row_btns.pack(pady=(0, 2), padx=8, fill="x")
        ctk.CTkButton(row_btns, text="开启限速代理", height=sim_btn_h, command=self.action_start_shaper).pack(side="left", expand=True, fill="x", padx=(0, 2))
        ctk.CTkButton(row_btns, text="关闭限速代理", height=sim_btn_h, fg_color="#c42b1c", hover_color="#8a1f15", command=self.action_stop_shaper).pack(side="right", expand=True, fill="x", padx=(2, 0))

    def _read_shaper_params(self, silent=False):
        """读取并校验三个输入框，返回 (delay, rate, loss) 或 None。

        silent=True 时校验失败不弹窗（用于失焦/回车自动生效，避免频繁打扰）。
        """
        try:
            delay = int(float(self.var_delay.get()))
            rate = int(float(self.var_rate.get()))
            loss = float(self.var_loss.get())
            if delay < 0 or rate < 0 or not (0 <= loss <= 100):
                raise ValueError
            return delay, rate, loss
        except (ValueError, TypeError):
            if not silent:
                messagebox.showwarning("参数无效", "延迟/限速需为 ≥0 的数字，丢包为 0~100 的数字")
            return None

    def _on_shaper_param_change(self, event=None):
        """代理运行中时，输入框失焦/回车即把最新参数推给代理。

        非法值静默忽略；与上次已应用值相同则不重复推送/刷日志。
        """
        if not self.shaper.is_running():
            return
        params = self._read_shaper_params(silent=True)
        if params is None or params == self._shaper_applied:
            return
        delay, rate, loss = params
        self.shaper.update(delay_ms=delay, rate_kbytes=rate, loss_pct=loss)
        self._shaper_applied = params
        self.log(f"弱网参数已更新: 延迟{delay}ms / 限速{rate}KB/s / 丢包{loss}%", "SUCCESS")

    def action_start_shaper(self):
        params = self._read_shaper_params()
        if params is None:
            return
        delay, rate, loss = params

        if not self.adb_helper.current_device_id:
            self.log("未选择设备，无法开启限速代理", "ERROR")
            messagebox.showwarning("无设备", "请先连接并选择设备")
            return

        def _thread():
            try:
                self.shaper.update(delay_ms=delay, rate_kbytes=rate, loss_pct=loss)
                self._shaper_applied = (delay, rate, loss)
                host, port = self.shaper.start()  # 幂等：已运行则只更新参数
                self.log(f"限速代理监听 {host}:{port}", "INFO")

                ok, _ = self._run_adb_settings_cmd(
                    ["put", "global", "http_proxy", f"{host}:{port}"],
                    "开启限速代理",
                )
                if ok:
                    self._shaper_device_id = self.adb_helper.active_device_id
                    self.log(f"弱网参数: 延迟{delay}ms / 限速{rate}KB/s / 丢包{loss}%", "SUCCESS")
                    self.after(0, lambda: self.lbl_shaper_status.configure(
                        text="生效中", text_color="#2e7d32"))
                self.refresh_proxy_status()
            except Exception as e:
                self.log(f"开启限速代理失败: {e}", "ERROR")
                self.after(0, lambda: self.lbl_shaper_status.configure(text="启动失败", text_color="#c42b1c"))
        self.adb_helper.spawn(_thread)

    def action_stop_shaper(self):
        def _thread():
            # 先清设备代理，再关本机服务，避免设备短暂指向已关闭端口
            self._run_adb_settings_cmd(["put", "global", "http_proxy", ":0"], "关闭限速代理")
            try:
                self.shaper.stop()
            except Exception as e:
                self.log(f"停止限速代理异常: {e}", "WARNING")
            self._shaper_device_id = None
            self.after(0, lambda: self.lbl_shaper_status.configure(text="未开启", text_color="gray"))
            self.refresh_proxy_status()
        # 绑回代理实际生效的那台设备，不能跟着当前选中走
        self.adb_helper.spawn(_thread, device_id=self._shaper_device_id)

    def cleanup_shaper(self):
        """主窗口关闭时调用：若代理在跑，清掉设备 http_proxy 并停服务。"""
        if not self.shaper.is_running():
            return
        try:
            # 清代理必须打回开启时那台设备，退出前用户很可能已经切走了
            device_id = self._shaper_device_id or self.adb_helper.current_device_id
            if device_id:
                subprocess.run(
                    [self.adb_helper.adb_cmd, "-s", device_id, "shell", "settings",
                     "put", "global", "http_proxy", ":0"],
                    **self.adb_helper._get_subprocess_kwargs(),
                )
        except Exception:
            pass
        try:
            self.shaper.stop()
        except Exception:
            pass

    def action_open_date_settings(self):
        def _thread():
            try:
                self.adb_helper.open_date_settings()
                self.log("已唤起设备系统时间设置页", "SUCCESS")
            except Exception as e:
                self.log(f"唤起时间设置失败: {e}", "ERROR")
        self.adb_helper.spawn(_thread)

    def action_open_language_settings(self):
        def _thread():
            try:
                self.adb_helper.open_language_settings()
                self.log("已唤起设备系统语言设置页", "SUCCESS")
            except Exception as e:
                self.log(f"唤起语言设置失败: {e}", "ERROR")
        self.adb_helper.spawn(_thread)

    def action_query_device_info(self):
        def _thread():
            try:
                info = self.adb_helper.get_device_info()
                self.log(f"查询成功 -> {info}", "SUCCESS")
            except Exception as e:
                self.log(f"查询设备信息失败: {e}", "ERROR")

        self.adb_helper.spawn(_thread)

    def action_show_screen_info(self):
        """查询设备屏幕信息（分辨率/密度/状态栏/导航栏/刘海/Configuration），弹窗展示。"""
        if not self.adb_helper.current_device_id:
            messagebox.showwarning("提示", "请先选择一个设备", parent=self)
            return

        self.btn_screen_info.configure(state="disabled", text="查询中...")
        # 弹窗可能停留很久，期间用户会切设备。刷新按钮必须打回弹窗归属的那台，
        # 否则会把别的设备的分辨率刷进这个窗口里
        dev = self.adb_helper.current_device_id

        def _refresh_bound():
            with self.adb_helper.bind_device(dev):
                return self.adb_helper.get_screen_info(force_refresh=True)

        def _thread():
            err = None
            info = None
            try:
                info = self.adb_helper.get_screen_info()
            except Exception as e:
                err = str(e)

            def _on_done():
                self.btn_screen_info.configure(state="normal", text="屏幕信息")
                if err:
                    self.log(f"查询屏幕信息失败: {err}", "ERROR")
                    messagebox.showerror("失败", f"查询屏幕信息失败:\n{err}", parent=self)
                    return
                from ui.components.screen_info_dialog import ScreenInfoDialog
                ScreenInfoDialog(
                    self, info, log_func=self.log,
                    refresh_fn=_refresh_bound,
                )
                self.log("已查询屏幕信息", "SUCCESS")

            self.after(0, _on_done)

        self.adb_helper.spawn(_thread)

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

        self.adb_helper.spawn(_thread)

    def open_device_file_manager(self):
        from ui.components.file_manager_window import DeviceFileManagerWindow
        file_manager_window = DeviceFileManagerWindow(self, self.adb_helper, self.config_manager)
        file_manager_window.grab_set()
