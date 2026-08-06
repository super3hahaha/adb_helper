import threading
import customtkinter as ctk
from tkinter import messagebox


class WirelessManagerWindow(ctk.CTkToplevel):
    """无线设备管理：多台无线设备并存下的连接/断开/重连入口。

    三块内容：
    1. 当前无线连接 —— 勾选后"断开选中"，或"全部断开"
    2. 手动连接 —— 输入 ip 或 ip:port 直接 connect（设备此前配对/开过 tcpip 即可，无需插 USB）
    3. 已保存设备 —— config 里记过的地址，勾选后一键重连

    设计前提：adb 支持多台 ip:5555 同时连接（IP 不同不冲突），所以这里
    从不为了连新设备而先断开旧设备。
    """

    def __init__(self, parent, adb_helper, config_manager, log_func=None, on_changed=None,
                 alias_resolver=None):
        super().__init__(parent)
        self.adb_helper = adb_helper
        self.config_manager = config_manager
        self.log = log_func or (lambda m, l="INFO": None)
        # 连接/断开成功后通知主窗口刷新设备下拉框
        self.on_changed = on_changed
        # 解析设备别名：主窗口的 resolve_device_alias 会把 ip:port 认回 USB
        # 序列号再查别名，比直接查 config 更能认出设备
        self.alias_resolver = alias_resolver or config_manager.get_device_alias

        self._connected_vars = {}   # addr -> BooleanVar
        self._saved_vars = {}       # addr -> BooleanVar
        self._busy = False

        # 统一复选框样式：默认样式方框偏大、边框偏粗，这里改小一号、描边更细、
        # 圆角，勾选色跟"刷新"按钮的蓝色呼应
        self._checkbox_style = dict(
            checkbox_width=18, checkbox_height=18,
            corner_radius=4, border_width=1.5,
            border_color=("gray70", "gray45"),
            fg_color="#3B8ED0", hover_color="#36699e",
            font=ctk.CTkFont(size=13),
        )

        self.title("无线设备管理")
        self.geometry("560x620")
        self.minsize(480, 520)
        self.transient(parent.winfo_toplevel())
        self.after(10, self._center_window)
        self.after(20, lambda: (self.lift(), self.focus_force()))

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(12, 6))
        ctk.CTkLabel(
            header, text="无线设备管理",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")
        self.btn_refresh = ctk.CTkButton(
            header, text="刷新", width=56, height=28,
            fg_color="transparent", text_color="#3B8ED0",
            hover_color=("gray85", "gray25"),
            command=self.refresh,
        )
        self.btn_refresh.pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.refresh()

    def _center_window(self):
        try:
            self.update_idletasks()
            parent = self.master.winfo_toplevel()
            x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
            y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
            self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass

    # ---------- 渲染 ----------

    def refresh(self):
        """后台取当前无线设备列表，回主线程重建界面。"""
        if self._busy:
            return
        self._set_busy(True)

        def _worker():
            try:
                connected = self.adb_helper.get_wireless_devices()
            except Exception:
                connected = []
            try:
                self.after(0, lambda: self._render(connected))
            except Exception:
                self._busy = False

        threading.Thread(target=_worker, daemon=True).start()

    def _set_busy(self, busy):
        self._busy = busy
        try:
            self.btn_refresh.configure(state="disabled" if busy else "normal")
        except Exception:
            pass

    def _render(self, connected):
        self._set_busy(False)
        if not self.winfo_exists():
            return

        for w in self.scroll.winfo_children():
            w.destroy()
        self._connected_vars = {}
        self._saved_vars = {}

        self._render_connected(connected)
        self._render_saved(connected)

    def _card(self, title):
        frame = ctk.CTkFrame(self.scroll)
        frame.pack(fill="x", pady=(0, 10), padx=2)
        ctk.CTkLabel(
            frame, text=title, font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 4))
        return frame

    def _render_connected(self, connected):
        card = self._card(f"当前无线连接（{len(connected)} 台）")

        if not connected:
            ctk.CTkLabel(
                card, text="暂无无线连接的设备", text_color="gray"
            ).pack(anchor="w", padx=12, pady=(0, 10))
            return

        current = self.adb_helper.current_device_id
        for addr in connected:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=1)
            var = ctk.BooleanVar(value=False)
            self._connected_vars[addr] = var
            label = addr
            alias = self._alias_of(addr)
            if alias:
                label = f"{alias} ({addr})"
            if addr == current:
                label += "  ← 当前操作设备"
            ctk.CTkCheckBox(row, text=label, variable=var, **self._checkbox_style).pack(side="left")

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(6, 10))
        ctk.CTkButton(
            btns, text="断开选中", width=100, height=28,
            fg_color="#c42b1c", hover_color="#8a1f15",
            command=self._disconnect_selected,
        ).pack(side="left")
        ctk.CTkButton(
            btns, text="全部断开", width=100, height=28,
            fg_color="#c42b1c", hover_color="#8a1f15",
            command=self._disconnect_all,
        ).pack(side="left", padx=(6, 0))

    def _render_saved(self, connected):
        saved = self.config_manager.get_wireless_devices()
        card = self._card(f"已保存设备（{len(saved)} 条）")

        if not saved:
            ctk.CTkLabel(
                card, text="无线连接成功过的设备会自动记在这里，方便下次一键重连",
                text_color="gray",
            ).pack(anchor="w", padx=12, pady=(0, 10))
            return

        for item in saved:
            addr = item["addr"]
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=1)
            # grid 而非 pack(side=right)：pack 下每行宽度由自身文本长度决定，
            # 各行"删除记录"会横向错位；grid 用弹性列 0 把按钮钉在同一条右边线上
            row.grid_columnconfigure(0, weight=1)
            is_online = addr in connected
            var = ctk.BooleanVar(value=False)
            self._saved_vars[addr] = var
            parts = [item["alias"] or self._alias_of(addr) or addr]
            if parts[0] != addr:
                parts.append(f"({addr})")
            if item["last_seen"]:
                parts.append(f"· {item['last_seen']}")
            if is_online:
                parts.append("· 已连接")
            cb = ctk.CTkCheckBox(row, text="  ".join(parts), variable=var, **self._checkbox_style)
            cb.grid(row=0, column=0, sticky="w")
            if is_online:
                cb.configure(state="disabled")
            ctk.CTkButton(
                row, text="删除记录", width=76, height=24,
                fg_color="transparent", text_color="gray",
                hover_color=("gray85", "gray25"),
                command=lambda a=addr: self._forget(a),
            ).grid(row=0, column=1, sticky="e")

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(6, 10))
        ctk.CTkButton(
            btns, text="重连选中", width=100, height=28,
            command=self._reconnect_selected,
        ).pack(side="left")
        ctk.CTkButton(
            btns, text="重连全部", width=100, height=28,
            command=self._reconnect_all,
        ).pack(side="left", padx=(6, 0))

    def _alias_of(self, addr):
        try:
            return self.alias_resolver(addr) or ""
        except Exception:
            return ""

    # ---------- 动作 ----------

    def _notify_changed(self):
        if self.on_changed:
            try:
                self.on_changed()
            except Exception:
                pass

    def _checked(self, var_map):
        return [addr for addr, var in var_map.items() if var.get()]

    def _disconnect_selected(self):
        targets = self._checked(self._connected_vars)
        if not targets:
            messagebox.showinfo("提示", "请先勾选要断开的无线设备", parent=self)
            return
        self._do_disconnect(targets)

    def _disconnect_all(self):
        if not self._connected_vars:
            messagebox.showinfo("提示", "当前没有已连接的无线调试设备", parent=self)
            return
        if not messagebox.askokcancel(
            "确认", f"将断开全部 {len(self._connected_vars)} 台无线设备，确定？", parent=self
        ):
            return
        self._do_disconnect(None)

    def _do_disconnect(self, targets):
        def on_complete(count, error=None):
            def _finish():
                if error:
                    messagebox.showerror("错误", f"断开失败: {error}", parent=self)
                elif count > 0:
                    self._notify_changed()
                self.refresh()
            try:
                self.after(0, _finish)
            except Exception:
                pass

        self.adb_helper.disconnect_wireless(targets=targets, on_complete=on_complete)

    def _reconnect_selected(self):
        targets = self._checked(self._saved_vars)
        if not targets:
            messagebox.showinfo("提示", "请先勾选要重连的设备", parent=self)
            return
        self._do_connect(targets)

    def _reconnect_all(self):
        # 已在线的地址不用再连
        connected = set(self._connected_vars.keys())
        targets = [a for a in self._saved_vars.keys() if a not in connected]
        if not targets:
            messagebox.showinfo("提示", "已保存的设备都已在线", parent=self)
            return
        self._do_connect(targets)

    def _do_connect(self, addrs):
        def on_complete(results):
            def _finish():
                ok = [a for a, s, _ in results if s]
                failed = [(a, m) for a, s, m in results if not s]
                for a in ok:
                    try:
                        self.config_manager.add_wireless_device(a)
                    except Exception:
                        pass
                if ok:
                    self._notify_changed()
                if failed:
                    detail = "\n".join(f"{a}: {m}" for a, m in failed)
                    messagebox.showerror(
                        "部分连接失败" if ok else "连接失败",
                        f"成功 {len(ok)} 台，失败 {len(failed)} 台：\n{detail}",
                        parent=self,
                    )
                elif ok:
                    messagebox.showinfo("成功", f"已连接 {len(ok)} 台无线设备", parent=self)
                self.refresh()
            try:
                self.after(0, _finish)
            except Exception:
                pass

        self.adb_helper.connect_wireless_devices(addrs, on_complete=on_complete)

    def _forget(self, addr):
        self.config_manager.remove_wireless_device(addr)
        self.log(f"已删除无线设备记录: {addr}", "INFO")
        self.refresh()
