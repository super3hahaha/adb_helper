import customtkinter as ctk
import tkinter.messagebox as messagebox
import threading
import subprocess
import time
import math
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
            values=["设备与系统控制", "环境与状态模拟", "屏幕与显示"],
            command=self.on_category_change,
            variable=self.category_var,
            corner_radius=8,
            height=32
        )
        self.category_selector.pack(pady=(10, 16), padx=10, fill="x")

        # 优化下拉框宽度
        optimize_combobox_width(self.category_selector, offset=200)

        # 每个分类一个容器，切换时 pack / pack_forget
        self.container_system = ctk.CTkFrame(container, fg_color="transparent")
        self.container_simulation = ctk.CTkFrame(container, fg_color="transparent")
        self.container_display = ctk.CTkFrame(container, fg_color="transparent")
        self._category_containers = {
            "设备与系统控制": self.container_system,
            "环境与状态模拟": self.container_simulation,
            "屏幕与显示": self.container_display,
        }

        # 初始化各部分 UI
        self._init_system_ui()
        self._init_simulation_ui()
        self._init_display_ui()

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

        # 注：「屏幕信息」已迁到「屏幕与显示」分类，与分辨率调整放在一起
        frame_sys_query_btns = ctk.CTkFrame(frame_sys, fg_color="transparent")
        frame_sys_query_btns.pack(pady=1, padx=8, fill="x")
        frame_sys_query_btns.grid_columnconfigure(0, weight=1, uniform="sys")
        frame_sys_query_btns.grid_columnconfigure(1, weight=1, uniform="sys")
        ctk.CTkButton(frame_sys_query_btns, text="查询设备系统版本", height=sys_btn_h,
                      command=self.action_query_device_info).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ctk.CTkButton(frame_sys_query_btns, text="切换系统导航方式", height=sys_btn_h,
                      command=self.action_open_navigation_settings).grid(row=0, column=1, sticky="ew", padx=(2, 0))

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

        call_header = ctk.CTkFrame(frame_call, fg_color="transparent")
        call_header.pack(pady=(2, 1), padx=8, fill="x")
        ctk.CTkLabel(call_header, text="来电模拟", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.call_help_btn = ctk.CTkButton(
            call_header, text="?", width=22, height=22, corner_radius=11,
            fg_color="gray50", hover_color="gray40", command=lambda: None,
        )
        self.call_help_btn.pack(side="left", padx=(5, 0))
        ModernTooltip(self.call_help_btn, sections=[
            ("来电模拟原理",
             "通过 ADB 向设备发送测试广播，模拟电话处于 RINGING 状态。\n"
             "• 模拟来电：只发送来电状态。\n"
             "• 联系人来电：同时携带所选联系人的电话号码，由被测 App 读取并显示联系人信息。"),
            ("开发接入",
             "请开发仅在测试包的来电接收器中保留以下模拟来电入口：\n"
             '<action android:name="android.intent.action.TEST" />\n'
             "该广播未受系统权限保护，第三方 App 也可能触发来电页面，因此只能保留在测试包中，正式包必须移除或禁用。"),
            ("与真实来电的区别",
             "该功能只是向被测 App 发送测试广播，并不是真正由运营商或 Android 电话框架产生的来电。"),
            ("已知局限",
             "• 即使没有授予“默认来电显示应用”相关权限，模拟联系人来电仍可能显示联系人姓名和电话号码；真实来电在相同权限条件下可能只显示“未知”。\n"
             "• 设备锁屏时，模拟来电无法正常唤起或显示来电页面。\n"
             "• 不会产生真实通话，也不能完整模拟接听、挂断、通话音频及运营商网络状态。\n"
             "• 不同 Android 版本、厂商系统和被测 App 的响应结果可能不同。"),
            ("使用建议",
             "此功能适合快速验证来电状态下的 UI 和业务逻辑，不能完全替代真实来电测试。"),
        ], max_width=520)

        row_call = ctk.CTkFrame(frame_call, fg_color="transparent")
        row_call.pack(pady=(1, 2), padx=8, fill="x")
        self.btn_sim_incoming_call = ctk.CTkButton(
            row_call, text="模拟来电 (RINGING)", height=sim_btn_h,
            command=self.action_sim_incoming_call,
        )
        self.btn_sim_incoming_call.pack(side="left", expand=True, fill="x", padx=(0, 2))
        self.btn_sim_contact_call = ctk.CTkButton(
            row_call, text="联系人来电", height=sim_btn_h,
            command=self.action_sim_contact_call,
        )
        self.btn_sim_contact_call.pack(side="right", expand=True, fill="x", padx=(2, 0))

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

    # ===== 屏幕与显示 =====
    # 档位定义 (名称, 下界dp, 上界dp 或 None, 一键预设的目标 dp 宽)。
    # 区间照抄适配规则；目标值取区间中段，离边界远一点，免得设备上下取整后擦边掉档。
    DP_TIERS = [
        ("Compact", 0, 600, 411),
        ("Medium", 600, 840, 700),
        ("Expanded", 840, 1000, 900),
        ("Large", 1000, None, 1100),
    ]

    # wm density 的安全区间。低于 ~72 部分 ROM 会渲染异常甚至重启 SystemUI，
    # 高于 1000 没有实际意义（dp 宽会小到没有页面能用）。
    DENSITY_MIN = 72
    DENSITY_MAX = 1000

    @classmethod
    def _tier_of(cls, dp_w):
        """把 dp 宽度归入档位，返回形如 "Expanded (840–999dp)" 的展示串。"""
        for name, lo, hi, _ in cls.DP_TIERS:
            if dp_w >= lo and (hi is None or dp_w < hi):
                if hi is None:
                    return f"{name} (≥{lo}dp)"
                if lo == 0:
                    return f"{name} (<{hi}dp)"
                return f"{name} ({lo}–{hi - 1}dp)"
        return "未知"

    def _init_display_ui(self):
        disp_btn_h = 28
        # 档位名 -> 按钮，用于把设备当前所处的那一档高亮出来
        self._tier_buttons = {}

        # 1. 当前状态
        frame_state = ctk.CTkFrame(self.container_display)
        frame_state.pack(pady=3, padx=10, fill="x")

        state_header = ctk.CTkFrame(frame_state, fg_color="transparent")
        state_header.pack(pady=(4, 1), padx=8, fill="x")
        ctk.CTkLabel(state_header, text="当前屏幕状态", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.state_help_btn = ctk.CTkButton(state_header, text="?", width=22, height=22, corner_radius=11,
                                            fg_color="gray50", hover_color="gray40", command=lambda: None)
        self.state_help_btn.pack(side="left", padx=(5, 0))
        ModernTooltip(self.state_help_btn, sections=[
            ("「当前生效等效 dp」是设备级的",
             "来自 am get-config，反映整块屏幕的 Configuration。\n"
             "App 被拖成自由窗口或进分屏时，这个值纹丝不动。"),
            ("「前台窗口」才是 App 判档依据",
             "来自前台 Activity 自己的 CurrentConfiguration，小窗/分屏下就是窗口自身尺寸。\n"
             "所以下面的「档位」按前台窗口宽判定 —— 这和适配规则第 1 条一致：\n"
             "分屏、自由窗口按 App 自身窗口宽判档，不看设备型号与屏幕物理尺寸。\n"
             "全屏时两者相同；读不到前台窗口（如停在桌面）才回退用设备级的值判档。"),
            ("要测小窗尺寸怎么操作",
             "把 App 拖成自由窗口或拉进分屏，摆到想测的大小，再点「刷新」。\n"
             "窗口每次拖动改变大小后都要重新点一次，面板不会自动跟踪。"),
        ])
        self.btn_display_refresh = ctk.CTkButton(
            state_header, text="刷新", width=48, height=22,
            fg_color="transparent", text_color="#3B8ED0",
            hover_color=("gray85", "gray25"),
            command=self.refresh_display_state,
        )
        self.btn_display_refresh.pack(side="right")

        # 这五行只压行高不改内容：CTkLabel 默认 height=28，叠五行留白过多，
        # 压到 21 视觉上贴紧一档，又不像更小的值那样显得挤。
        lbl_h = 21
        self.lbl_disp_size = ctk.CTkLabel(frame_state, text="分辨率：—", font=ctk.CTkFont(size=11), height=lbl_h, anchor="w")
        self.lbl_disp_size.pack(pady=0, padx=8, fill="x")
        self.lbl_disp_density = ctk.CTkLabel(frame_state, text="密度：—", font=ctk.CTkFont(size=11), height=lbl_h, anchor="w")
        self.lbl_disp_density.pack(pady=0, padx=8, fill="x")
        self.lbl_disp_factory = ctk.CTkLabel(frame_state, text="出厂默认等效 dp：—", font=ctk.CTkFont(size=11), text_color="gray", height=lbl_h, anchor="w")
        self.lbl_disp_factory.pack(pady=0, padx=8, fill="x")
        # 这两行是重点：App 判档只看当前生效的窗口 dp 宽，所以加粗。
        # 档位必须独占一行 —— 并进上面那行后，左栏窄一点就会把档位名截掉。
        self.lbl_disp_dp = ctk.CTkLabel(frame_state, text="当前生效等效 dp：—", font=ctk.CTkFont(size=12, weight="bold"), height=lbl_h, anchor="w")
        self.lbl_disp_dp.pack(pady=(1, 0), padx=8, fill="x")
        # 前台窗口才是 App 判档真正依据的宽度：小窗 / 分屏下它和上面那行会差好几档。
        # 包名单独一行 —— 挤在尺寸后面会把自己截掉，而且它是这行里最不重要的信息。
        self.lbl_disp_window = ctk.CTkLabel(frame_state, text="前台窗口：—", font=ctk.CTkFont(size=11), height=lbl_h, anchor="w")
        self.lbl_disp_window.pack(pady=0, padx=8, fill="x")
        self.lbl_disp_window_pkg = ctk.CTkLabel(frame_state, text="", font=ctk.CTkFont(size=10), text_color="gray", height=14, anchor="w")
        self.lbl_disp_window_pkg.pack(pady=0, padx=(16, 8), fill="x")
        self.lbl_disp_tier = ctk.CTkLabel(frame_state, text="档位：—", font=ctk.CTkFont(size=12, weight="bold"), height=lbl_h, anchor="w")
        self.lbl_disp_tier.pack(pady=(0, 2), padx=8, fill="x")

        state_btns = ctk.CTkFrame(frame_state, fg_color="transparent")
        state_btns.pack(pady=(1, 4), padx=8, fill="x")
        state_btns.grid_columnconfigure(0, weight=1, uniform="disp_state")
        state_btns.grid_columnconfigure(1, weight=1, uniform="disp_state")
        self.btn_screen_info = ctk.CTkButton(state_btns, text="屏幕信息", height=disp_btn_h,
                                             command=self.action_show_screen_info)
        self.btn_screen_info.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ctk.CTkButton(state_btns, text="恢复设备默认", height=disp_btn_h,
                      fg_color="#c42b1c", hover_color="#8a1f15",
                      command=self.action_reset_screen_override).grid(row=0, column=1, sticky="ew", padx=(2, 0))
        ctk.CTkLabel(frame_state, text="恢复 = wm size reset + wm density reset，分辨率与密度一并回出厂值",
                     font=ctk.CTkFont(size=10), text_color="gray", anchor="w").pack(pady=(0, 4), padx=8, fill="x")

        # 2. dp 档位一键切
        frame_tier = ctk.CTkFrame(self.container_display)
        frame_tier.pack(pady=3, padx=10, fill="x")

        tier_header = ctk.CTkFrame(frame_tier, fg_color="transparent")
        tier_header.pack(pady=(4, 1), padx=8, fill="x")
        ctk.CTkLabel(tier_header, text="按 dp 宽度模拟档位", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.tier_help_btn = ctk.CTkButton(tier_header, text="?", width=22, height=22, corner_radius=11,
                                           fg_color="gray50", hover_color="gray40", command=lambda: None)
        self.tier_help_btn.pack(side="left", padx=(5, 0))
        ModernTooltip(self.tier_help_btn, sections=[
            ("判档看的是 dp 宽，不是像素",
             "dp = px × 160 ÷ density。想把窗口 dp 宽推到目标档位，改 px 或改 density 都行，\n"
             "下面的「调整方式」就是在这两条路之间选。两种方式都不会动另一个量。"),
            ("改分辨率 (wm size)：默认，最贴近真实大屏",
             "density 不动，把 wm size 的宽高同时乘以 目标dp ÷ 当前dp。\n"
             "宽高比不变所以画面不变形；因为 dp 与 px 成正比，横屏竖屏下算出来都准。\n"
             "效果是屏幕里装下更多内容、元素物理大小基本不变，和真实平板观感一致，\n"
             "drawable-xxhdpi 这类资源目录的选择也不受影响。\n"
             "代价：渲染像素数按 k² 增长，推到 1000dp 可能明显掉帧，个别 ROM 会花屏。"),
            ("改密度 (wm density)：备选，胜在不掉帧",
             "px 不动，只把 density 调低：新 density = 当前 density × 当前dp ÷ 目标dp。\n"
             "surface 尺寸不变，所以截图尺寸、渲染性能、相机预览都不受影响。\n"
             "代价：屏幕上所有元素会明显变小，而且 density 变了会改变资源目录选择，\n"
             "排查切图资源问题时别用这个方式。"),
            ("横屏下点会按横屏宽算",
             "目标 dp 宽对的是「当前方向的窗口宽」。横屏时窗口宽是长边，\n"
             "此时切到 1000dp，转回竖屏后竖屏宽会远小于 1000dp。\n"
             "要验证竖屏大屏布局，请在竖屏状态下点档位按钮。"),
        ])

        # 调整方式：默认改分辨率——用户要的就是 wm size，改密度只作备选
        self.dp_mode_var = ctk.StringVar(value="改分辨率")
        self.seg_dp_mode = ctk.CTkSegmentedButton(
            frame_tier, values=["改分辨率", "改密度"], variable=self.dp_mode_var, height=26,
            font=ctk.CTkFont(size=11),
        )
        self.seg_dp_mode.pack(pady=(2, 3), padx=8, fill="x")

        tier_grid = ctk.CTkFrame(frame_tier, fg_color="transparent")
        tier_grid.pack(pady=1, padx=8, fill="x")
        tier_grid.grid_columnconfigure(0, weight=1, uniform="tier")
        tier_grid.grid_columnconfigure(1, weight=1, uniform="tier")
        for idx, (name, lo, hi, target) in enumerate(self.DP_TIERS):
            if hi is None:
                rng = f"≥{lo}dp"
            elif lo == 0:
                rng = f"<{hi}dp"
            else:
                rng = f"{lo}–{hi - 1}dp"
            r, c = divmod(idx, 2)
            btn = ctk.CTkButton(
                tier_grid, text=f"{name}  {rng}\n→ {target}dp", height=40,
                font=ctk.CTkFont(size=11),
                command=lambda t=target, n=name: self.action_apply_target_dp(t, n),
            )
            btn.grid(row=r, column=c, sticky="ew", padx=(0, 2) if c == 0 else (2, 0), pady=1)
            self._tier_buttons[name] = btn

        # 自定义 dp：验证 839 / 840 这类边界值时用
        custom_row = ctk.CTkFrame(frame_tier, fg_color="transparent")
        custom_row.pack(pady=(3, 4), padx=8, fill="x")
        ctk.CTkLabel(custom_row, text="自定义 dp 宽:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 5))
        self.entry_target_dp = ctk.CTkEntry(custom_row, height=disp_btn_h, placeholder_text="例如 840")
        self.entry_target_dp.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(custom_row, text="应用", width=56, height=disp_btn_h,
                      command=self.action_apply_custom_dp).pack(side="right")

        # 3. 手动覆写
        frame_manual = ctk.CTkFrame(self.container_display)
        frame_manual.pack(pady=3, padx=10, fill="x")

        manual_header = ctk.CTkFrame(frame_manual, fg_color="transparent")
        manual_header.pack(pady=(4, 0), padx=8, fill="x")
        ctk.CTkLabel(manual_header, text="手动覆写", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.manual_help_btn = ctk.CTkButton(manual_header, text="?", width=22, height=22, corner_radius=11,
                                             fg_color="gray50", hover_color="gray40", command=lambda: None)
        self.manual_help_btn.pack(side="left", padx=(5, 0))
        ModernTooltip(self.manual_help_btn, sections=[
            ("分辨率 (adb shell wm size)",
             "直接指定像素宽高。填的是自然方向（竖屏）的 W×H，横屏时系统自己换算。\n"
             "改成与物理分辨率不同宽高比时，画面会出现黑边或拉伸，属正常现象。\n"
             "填远大于物理分辨率的值会明显掉帧，建议配合 density 一起调而不是一味放大。"),
            ("密度 (adb shell wm density)",
             "直接指定 dpi。两个字段可以只改一个，另一个留空即可。\n"
             "想模拟一台真实平板，可以两个一起设，比如 2048×1280 + 320dpi = 1024dp 宽，\n"
             "这样 density 落在标准 xhdpi 档，资源目录选择也跟真实平板一致。"),
        ])

        ctk.CTkLabel(frame_manual, text="分辨率 (wm size)", font=ctk.CTkFont(size=11), text_color="gray", height=16).pack(pady=0, anchor="w", padx=8)
        size_row = ctk.CTkFrame(frame_manual, fg_color="transparent")
        size_row.pack(pady=(0, 1), padx=8, fill="x")
        self.entry_size_w = ctk.CTkEntry(size_row, height=disp_btn_h, width=70, placeholder_text="宽")
        self.entry_size_w.pack(side="left")
        ctk.CTkLabel(size_row, text="×", font=ctk.CTkFont(size=12)).pack(side="left", padx=4)
        self.entry_size_h = ctk.CTkEntry(size_row, height=disp_btn_h, width=70, placeholder_text="高")
        self.entry_size_h.pack(side="left")
        ctk.CTkLabel(size_row, text="px", font=ctk.CTkFont(size=11), text_color="gray").pack(side="left", padx=(4, 0))
        ctk.CTkButton(size_row, text="应用", width=56, height=disp_btn_h,
                      command=self.action_apply_manual_size).pack(side="right")

        ctk.CTkLabel(frame_manual, text="密度 (wm density)", font=ctk.CTkFont(size=11), text_color="gray", height=16).pack(pady=(2, 0), anchor="w", padx=8)
        dens_row = ctk.CTkFrame(frame_manual, fg_color="transparent")
        dens_row.pack(pady=(0, 4), padx=8, fill="x")
        self.entry_density = ctk.CTkEntry(dens_row, height=disp_btn_h, width=70, placeholder_text="dpi")
        self.entry_density.pack(side="left")
        ctk.CTkLabel(dens_row, text="dpi", font=ctk.CTkFont(size=11), text_color="gray").pack(side="left", padx=(4, 0))
        ctk.CTkButton(dens_row, text="应用", width=56, height=disp_btn_h,
                      command=self.action_apply_manual_density).pack(side="right")

    def _highlight_tier(self, dp_w):
        """把设备当前所处的那一档按钮标绿，其余恢复主题色。dp_w 为 None 时全部恢复。"""
        current = None
        if dp_w is not None:
            for name, lo, hi, _ in self.DP_TIERS:
                if dp_w >= lo and (hi is None or dp_w < hi):
                    current = name
                    break
        default_fg = ctk.ThemeManager.theme["CTkButton"]["fg_color"]
        default_hover = ctk.ThemeManager.theme["CTkButton"]["hover_color"]
        for name, btn in self._tier_buttons.items():
            if name == current:
                btn.configure(fg_color="#2FA572", hover_color="#268A5E")
            else:
                btn.configure(fg_color=default_fg, hover_color=default_hover)

    def refresh_display_state(self):
        """重新读取 size / density / Configuration 并刷新状态卡与手动输入框。"""
        if not self.adb_helper.current_device_id:
            self._clear_display_state("未连接设备")
            return

        self.btn_display_refresh.configure(state="disabled", text="...")

        def _thread():
            err = None
            st = None
            try:
                st = self.adb_helper.get_size_density_state()
                # 读不到前台窗口不算失败（可能停在桌面或 ROM 格式不认识），
                # 档位会自动回退按设备级 dp 判定
                try:
                    st["foreground"] = self.adb_helper.get_foreground_window_state()
                except Exception:
                    st["foreground"] = None
            except Exception as e:
                err = str(e)

            def _on_done():
                self.btn_display_refresh.configure(state="normal", text="刷新")
                if err:
                    self._clear_display_state(f"读取失败（{err}）")
                    return
                self._render_display_state(st)

            self.after(0, _on_done)

        self.adb_helper.spawn(_thread)

    def _clear_display_state(self, reason):
        self.lbl_disp_size.configure(text=f"分辨率：{reason}")
        self.lbl_disp_density.configure(text="密度：—")
        self.lbl_disp_factory.configure(text="出厂默认等效 dp：—")
        self.lbl_disp_dp.configure(text="当前生效等效 dp：—")
        self.lbl_disp_window.configure(text="前台窗口：—")
        self.lbl_disp_window_pkg.configure(text="")
        self.lbl_disp_tier.configure(text="档位：—")
        self._highlight_tier(None)

    def _render_display_state(self, st):
        """把 get_size_density_state 的结果画到状态卡上，并回填手动输入框。"""
        if st.get("over_w"):
            size_text = (f"分辨率：{st['over_w']} × {st['over_h']} px"
                         f"　（已覆写，物理 {st['phys_w']} × {st['phys_h']}）")
        else:
            size_text = f"分辨率：{st['phys_w']} × {st['phys_h']} px　（物理）"
        self.lbl_disp_size.configure(text=size_text)

        if st.get("over_density"):
            dens_text = f"密度：{st['over_density']} dpi　（已覆写，物理 {st['phys_density']}）"
        else:
            dens_text = f"密度：{st['phys_density']} dpi　（物理）"
        self.lbl_disp_density.configure(text=dens_text)

        # 出厂等效 dp：按物理分辨率 + 物理密度换算，是覆写前的基准值。
        # 这里给的是自然方向（竖屏）的 W×H，和 wm size 的输出方向一致。
        if st.get("phys_w") and st.get("phys_density"):
            f_w = round(st["phys_w"] * 160 / float(st["phys_density"]))
            f_h = round(st["phys_h"] * 160 / float(st["phys_density"]))
            self.lbl_disp_factory.configure(
                text=f"出厂默认等效 dp：{f_w} × {f_h}（sw{min(f_w, f_h)}dp）"
            )
        else:
            self.lbl_disp_factory.configure(text="出厂默认等效 dp：—")

        # 设备级 Configuration：整块屏幕的当前方向尺寸
        dp_w, dp_h = st.get("dp_w", 0), st.get("dp_h", 0)
        if dp_w and dp_h:
            orient = "横屏" if dp_w > dp_h else "竖屏"
            self.lbl_disp_dp.configure(
                text=f"当前生效等效 dp：{dp_w} × {dp_h}（sw{min(dp_w, dp_h)}dp）· {orient}"
            )
        else:
            self.lbl_disp_dp.configure(text="当前生效等效 dp：未能读取 Configuration")

        # 前台窗口：App 自己拿到的尺寸。关键数据放行首，包名垫后 —— 窗口窄时
        # 截掉的是包名而不是 dp 值。
        fg = st.get("foreground")
        if fg:
            mode_cn = {
                "fullscreen": "全屏",
                "multi-window": "分屏",
                "freeform": "自由窗口",
                "pinned": "画中画",
                "split-screen-primary": "分屏(主)",
                "split-screen-secondary": "分屏(次)",
            }.get(fg["mode"], fg["mode"])
            self.lbl_disp_window.configure(
                text=f"前台窗口：{fg['w_dp']} × {fg['h_dp']} dp（sw{fg['sw_dp']}dp）· {mode_cn}"
            )
            self.lbl_disp_window_pkg.configure(text=fg["package"])
        else:
            self.lbl_disp_window.configure(text="前台窗口：未读到（可能停在桌面）")
            self.lbl_disp_window_pkg.configure(text="")

        # 档位以前台窗口宽为准 —— 适配规则第 1 条就是按 App 自身窗口宽判档。
        # 读不到前台窗口才回退用设备级的值。
        tier_dp = fg["w_dp"] if fg else dp_w
        if tier_dp:
            suffix = "" if fg else "（设备级）"
            self.lbl_disp_tier.configure(text=f"档位：{self._tier_of(tier_dp)}{suffix}")
            self._highlight_tier(tier_dp)
        else:
            self.lbl_disp_tier.configure(text="档位：—")
            self._highlight_tier(None)

        # 回填手动输入框：填当前生效值，用户想微调时不必自己抄一遍
        for entry, val in (
            (self.entry_size_w, st.get("cur_w")),
            (self.entry_size_h, st.get("cur_h")),
            (self.entry_density, st.get("cur_density")),
        ):
            entry.delete(0, "end")
            if val:
                entry.insert(0, str(val))

    # wm size 的安全上限。单边超过这个值，等比放大后的总像素已经到几千万级，
    # 合成器压力过大，实测会掉帧甚至花屏。
    SIZE_MAX_PX = 10000

    def action_apply_target_dp(self, target_dp, label=None):
        """把当前方向的窗口 dp 宽推到 target_dp。

        两种方式互斥，都只动一个量：
        - 改分辨率：density 不动，wm size 宽高同乘 k = target_dp / 当前dp。
          dp 与 px 成正比，所以这个等比缩放在横屏、竖屏下都能精确命中目标，
          不必按方向分情况；宽高比不变，画面也不会变形。
        - 改密度：px 不动，density 与 dp 宽成反比，直接反比换算。
        """
        if not self.adb_helper.current_device_id:
            messagebox.showwarning("提示", "请先选择一个设备", parent=self)
            return

        by_size = (self.dp_mode_var.get() == "改分辨率")

        def _thread():
            try:
                st = self.adb_helper.get_size_density_state()
            except Exception as e:
                self.log(f"读取当前屏幕状态失败: {e}", "ERROR")
                return

            cur_dp = st.get("dp_w", 0)
            cur_density = st.get("cur_density", 0)
            cur_w, cur_h = st.get("cur_w", 0), st.get("cur_h", 0)
            if not cur_dp or not cur_density or not cur_w or not cur_h:
                self.log("未能读到当前分辨率/密度/dp 宽，请改用「手动覆写」直接填值", "ERROR")
                return

            tag = f"{label} " if label else ""

            if by_size:
                k = target_dp / float(cur_dp)
                # 驱动维 = 当前方向的"窗口宽"落在自然方向（wm size 的 W×H）上的那一维。
                # 竖屏时是 W，横屏时窗口宽是长边、对应 H。
                portrait = st.get("dp_w", 0) <= st.get("dp_h", 0)
                drive, other = (cur_w, cur_h) if portrait else (cur_h, cur_w)
                # 向上取偶：取偶是因为部分 ROM 对奇数宽高渲染异常；必须向上而不能四舍五入，
                # 否则目标 840 会算出 2046px → 839dp，正好掉回 Medium 档，
                # 而验证 839/840 边界恰恰是这个功能最主要的用途。
                new_drive = -(-int(math.ceil(drive * k)) // 2) * 2
                new_other = int(round(other * new_drive / float(drive))) & ~1
                new_w, new_h = (new_drive, new_other) if portrait else (new_other, new_drive)
                if new_w > self.SIZE_MAX_PX or new_h > self.SIZE_MAX_PX:
                    self.log(
                        f"目标 {target_dp}dp 需要 {new_w}x{new_h}，单边超过 {self.SIZE_MAX_PX}px 上限。"
                        f"请改用「改密度」方式，或先把密度调低再试",
                        "ERROR",
                    )
                    return
                if new_w * new_h > 20_000_000:
                    self.log(
                        f"{new_w}x{new_h} 约 {new_w * new_h / 1e6:.0f}M 像素，"
                        f"设备可能明显掉帧；只验证布局分档的话可切「改密度」",
                        "WARNING",
                    )
                self.log(
                    f"切换至 {tag}{target_dp}dp：当前 {cur_dp}dp / {cur_w}x{cur_h} @ {cur_density}dpi "
                    f"→ wm size {new_w}x{new_h}（密度不变）",
                    "INFO",
                )
                ok, out = self.adb_helper.set_screen_size(new_w, new_h)
                if not ok:
                    self.log(f"设置分辨率失败: {out}", "ERROR")
                    return
            else:
                # dp 宽与 density 成反比：dp = px × 160 / density
                # 同理向下取整：dp 与 density 成反比，density 取小才能保证 dp 不低于目标。
                # 例：390dpi/852dp 要到 840dp，四舍五入得 396 → 实际 839dp，正好掉档。
                new_density = int(math.floor(cur_density * cur_dp / float(target_dp)))
                clamped = max(self.DENSITY_MIN, min(self.DENSITY_MAX, new_density))
                if clamped != new_density:
                    # 夹取后实际 dp 会偏离目标，说清楚落到哪，别让用户以为设成功了
                    actual_dp = round(cur_dp * cur_density / float(clamped))
                    self.log(
                        f"目标 {target_dp}dp 需要 density={new_density}，超出安全区间 "
                        f"[{self.DENSITY_MIN}, {self.DENSITY_MAX}]，改用 {clamped}（实际约 {actual_dp}dp）",
                        "WARNING",
                    )
                    new_density = clamped
                self.log(
                    f"切换至 {tag}{target_dp}dp：当前 {cur_dp}dp @ {cur_density}dpi "
                    f"→ wm density {new_density}（分辨率不变）",
                    "INFO",
                )
                ok, out = self.adb_helper.set_screen_density(new_density)
                if not ok:
                    self.log(f"设置密度失败: {out}", "ERROR")
                    return

            # Configuration 更新有延迟，立刻读会拿到旧值
            time.sleep(0.8)
            self.after(0, self.refresh_display_state)

        self.adb_helper.spawn(_thread)

    def action_apply_custom_dp(self):
        raw = self.entry_target_dp.get().strip()
        try:
            target = int(raw)
        except ValueError:
            messagebox.showwarning("提示", "请输入一个整数 dp 宽度，例如 840", parent=self)
            return
        if not 200 <= target <= 4000:
            messagebox.showwarning("提示", "dp 宽度请填在 200–4000 之间", parent=self)
            return
        self.action_apply_target_dp(target)

    def action_apply_manual_size(self):
        if not self.adb_helper.current_device_id:
            messagebox.showwarning("提示", "请先选择一个设备", parent=self)
            return
        try:
            w = int(self.entry_size_w.get().strip())
            h = int(self.entry_size_h.get().strip())
        except ValueError:
            messagebox.showwarning("提示", "分辨率的宽和高都要填整数像素", parent=self)
            return
        if not (100 <= w <= 10000 and 100 <= h <= 10000):
            messagebox.showwarning("提示", "分辨率请填在 100–10000 px 之间", parent=self)
            return

        def _thread():
            ok, out = self.adb_helper.set_screen_size(w, h)
            if not ok:
                self.log(f"设置分辨率失败: {out}", "ERROR")
                return
            self.log(f"已将分辨率覆写为 {w}x{h}", "SUCCESS")
            time.sleep(0.8)
            self.after(0, self.refresh_display_state)

        self.adb_helper.spawn(_thread)

    def action_apply_manual_density(self):
        if not self.adb_helper.current_device_id:
            messagebox.showwarning("提示", "请先选择一个设备", parent=self)
            return
        try:
            d = int(self.entry_density.get().strip())
        except ValueError:
            messagebox.showwarning("提示", "密度要填整数 dpi", parent=self)
            return
        if not self.DENSITY_MIN <= d <= self.DENSITY_MAX:
            messagebox.showwarning(
                "提示",
                f"密度请填在 {self.DENSITY_MIN}–{self.DENSITY_MAX} dpi 之间。\n"
                "过低会导致部分 ROM 渲染异常。",
                parent=self,
            )
            return

        def _thread():
            ok, out = self.adb_helper.set_screen_density(d)
            if not ok:
                self.log(f"设置密度失败: {out}", "ERROR")
                return
            self.log(f"已将密度覆写为 {d} dpi", "SUCCESS")
            time.sleep(0.8)
            self.after(0, self.refresh_display_state)

        self.adb_helper.spawn(_thread)

    def action_reset_screen_override(self):
        if not self.adb_helper.current_device_id:
            messagebox.showwarning("提示", "请先选择一个设备", parent=self)
            return

        def _thread():
            ok, out = self.adb_helper.reset_screen_override()
            if ok:
                self.log("已恢复设备默认分辨率与密度", "SUCCESS")
            else:
                # size 从未被覆写时 `wm size reset` 在部分 ROM 上会报错，
                # 但 density 那条已经执行过了，所以只降级为警告
                self.log(f"恢复默认时部分命令未成功（通常无碍）: {out}", "WARNING")
            time.sleep(0.8)
            self.after(0, self.refresh_display_state)

        self.adb_helper.spawn(_thread)

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
        target = self._category_containers.get(value)
        if target is None:
            return
        for name, frame in self._category_containers.items():
            if frame is not target:
                frame.pack_forget()
        target.pack(fill="both", expand=True)
        # 屏幕与显示的状态卡是"拍快照"式的，每次切进来重新拉一次，
        # 免得显示的还是上次离开时的分辨率
        if value == "屏幕与显示":
            self.refresh_display_state()

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

    def action_open_navigation_settings(self):
        def _thread():
            try:
                success, output = self.adb_helper.open_navigation_settings()
                if success:
                    self.log(output or "已打开系统导航方式入口", "SUCCESS")
                else:
                    self.log(f"唤起导航方式设置页失败: {output}", "ERROR")
            except Exception as e:
                self.log(f"唤起导航方式设置页异常: {e}", "ERROR")
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

    def action_sim_incoming_call(self):
        """使用历史兼容命令发送 RINGING 测试广播。"""
        if not self.adb_helper.current_device_id:
            messagebox.showwarning("提示", "请先选择一个设备", parent=self)
            return

        self.btn_sim_incoming_call.configure(state="disabled", text="正在模拟...")
        dev = self.adb_helper.current_device_id

        def _thread():
            try:
                with self.adb_helper.bind_device(dev):
                    success, msg = self.adb_helper.sim_incoming_call()
                self.log(msg, "SUCCESS" if success else "ERROR")
            except Exception as exc:
                self.log(f"模拟来电异常: {exc}", "ERROR")
            finally:
                self.after(0, lambda: self.btn_sim_incoming_call.configure(
                    state="normal", text="模拟来电 (RINGING)"
                ))

        self.adb_helper.spawn(_thread)

    def action_sim_contact_call(self):
        """读取联系人号码，并按设备类型模拟带号码的来电。"""
        if not self.adb_helper.current_device_id:
            messagebox.showwarning("提示", "请先选择一个设备", parent=self)
            return
        dev = self.adb_helper.current_device_id

        self.btn_sim_contact_call.configure(state="disabled", text="正在读取通讯录...")

        def _thread():
            contacts = []
            error = None
            try:
                with self.adb_helper.bind_device(dev):
                    contacts = self.adb_helper.get_phone_contacts()
            except Exception as exc:
                error = str(exc)

            def _show_dialog():
                self.btn_sim_contact_call.configure(state="normal", text="联系人来电")
                if error:
                    self.log(f"读取联系人号码失败，将使用手动号码输入：{error}", "WARNING")
                elif contacts:
                    self.log(f"成功获取 {len(contacts)} 个联系人号码", "SUCCESS")
                else:
                    self.log("未读取到联系人号码，可在弹窗中手动输入", "WARNING")

                from ui.components.contact_selector import IncomingCallDialog
                IncomingCallDialog(self, self.adb_helper, contacts, dev, self.log)

            self.after(0, _show_dialog)

        self.adb_helper.spawn(_thread)

    def open_device_file_manager(self):
        from ui.components.file_manager_window import DeviceFileManagerWindow
        file_manager_window = DeviceFileManagerWindow(self, self.adb_helper, self.config_manager)
        file_manager_window.grab_set()
