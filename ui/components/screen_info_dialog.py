import threading
import customtkinter as ctk


class ScreenInfoDialog(ctk.CTkToplevel):
    """屏幕信息弹窗：以分组卡片形式展示设备/屏幕/系统占用/可用区域，右上角支持复制/刷新。

    refresh_fn (可选): 无参函数，返回新的 info dict。点"刷新"时在后台线程调用、
    回到主线程重建卡片。通常传 lambda: adb_helper.get_screen_info(force_refresh=True)。
    """

    def __init__(self, parent, info, log_func=None, refresh_fn=None):
        super().__init__(parent)
        self.info = info or {}
        self.log = log_func
        self.refresh_fn = refresh_fn

        self.title("屏幕信息")
        self.geometry("500x580")
        self.minsize(420, 480)
        self.transient(parent.winfo_toplevel())

        # 居中
        self.after(10, self._center_window)
        self.after(20, lambda: (self.lift(), self.focus_force()))

        # 顶部标题栏
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(12, 6))
        ctk.CTkLabel(
            header, text="屏幕信息",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")
        self.btn_copy = ctk.CTkButton(
            header, text="复制", width=56, height=28,
            fg_color="transparent", text_color="#3B8ED0",
            hover_color=("gray85", "gray25"),
            command=self.copy_info,
        )
        self.btn_copy.pack(side="right")
        if self.refresh_fn:
            self.btn_refresh = ctk.CTkButton(
                header, text="刷新", width=56, height=28,
                fg_color="transparent", text_color="#3B8ED0",
                hover_color=("gray85", "gray25"),
                command=self._on_refresh,
            )
            self.btn_refresh.pack(side="right", padx=(0, 4))

        # 卡片容器（刷新时清空重建）
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._render_cards()

    def _render_cards(self):
        # 清空旧卡片
        for w in self.scroll.winfo_children():
            w.destroy()

        info = self.info
        self._make_card(self.scroll, "屏幕尺寸", [
            ("屏幕宽度", f"{info.get('dp_w', '?')} dp · {info.get('px_w', '?')} px"),
            ("屏幕高度", f"{info.get('dp_h', '?')} dp · {info.get('px_h', '?')} px"),
            ("屏幕方向", info.get("orientation", "未知")),
        ])
        self._make_card(self.scroll, "系统占用", [
            ("顶部状态栏", info.get("status_bar", "未知")),
            ("刘海 / 挖孔", info.get("cutout", "无")),
            ("底部导航 / 手势条", info.get("nav_bar", "未知")),
            ("侧边手势区", info.get("side_gesture", "无")),
        ])
        self._make_card(self.scroll, "可用区域", [
            ("可用宽度", info.get("avail_w", "未知")),
            ("可用高度", info.get("avail_h", "未知")),
        ])

    def _on_refresh(self):
        if not self.refresh_fn:
            return
        self.btn_refresh.configure(state="disabled", text="刷新中")

        def _thread():
            err = None
            new_info = None
            try:
                new_info = self.refresh_fn()
            except Exception as e:
                err = str(e)

            def _on_done():
                if not self.winfo_exists():
                    return
                self.btn_refresh.configure(state="normal", text="刷新")
                if err:
                    if self.log:
                        self.log(f"刷新屏幕信息失败: {err}", "ERROR")
                    return
                self.info = new_info or {}
                self._render_cards()
                if self.log:
                    self.log("已刷新屏幕信息", "SUCCESS")

            self.after(0, _on_done)

        threading.Thread(target=_thread, daemon=True).start()

    def _center_window(self):
        try:
            self.update_idletasks()
            parent = self.master
            pw = parent.winfo_rootx()
            ph = parent.winfo_rooty()
            pwidth = parent.winfo_width()
            pheight = parent.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            x = pw + (pwidth - w) // 2
            y = ph + (pheight - h) // 2
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    def _make_card(self, parent, title, rows):
        card = ctk.CTkFrame(parent, fg_color=("gray92", "gray20"))
        card.pack(fill="x", pady=6, padx=2)

        ctk.CTkLabel(
            card, text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#3B8ED0",
        ).pack(anchor="w", padx=14, pady=(10, 4))

        for key, val in rows:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=2)
            ctk.CTkLabel(row, text=key, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=str(val), anchor="e").pack(side="right")

        # 底部留白
        ctk.CTkLabel(card, text="", height=4).pack()

    def copy_info(self):
        info = self.info
        lines = [
            "[屏幕信息]",
            "",
            "# 屏幕尺寸",
            f"屏幕宽度: {info.get('dp_w', '?')} dp · {info.get('px_w', '?')} px",
            f"屏幕高度: {info.get('dp_h', '?')} dp · {info.get('px_h', '?')} px",
            f"屏幕方向: {info.get('orientation', '未知')}",
            "",
            "# 系统占用",
            f"顶部状态栏: {info.get('status_bar', '未知')}",
            f"刘海 / 挖孔: {info.get('cutout', '无')}",
            f"底部导航 / 手势条: {info.get('nav_bar', '未知')}",
            f"侧边手势区: {info.get('side_gesture', '无')}",
            "",
            "# 可用区域",
            f"可用宽度: {info.get('avail_w', '未知')}",
            f"可用高度: {info.get('avail_h', '未知')}",
        ]
        text = "\n".join(lines)
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()  # 确保剪贴板内容驻留
            self.btn_copy.configure(text="已复制")
            self.after(1200, lambda: self.btn_copy.configure(text="复制"))
            if self.log:
                self.log("已复制屏幕信息到剪贴板", "SUCCESS")
        except Exception as e:
            if self.log:
                self.log(f"复制屏幕信息失败: {e}", "ERROR")
