import os
import json
import customtkinter as ctk
import tkinter.messagebox as messagebox
import tkinter.filedialog as filedialog

from ui.utils import optimize_combobox_width, attach_scrollable
from core.file_helper import FileHelper

class SettingsTab(ctk.CTkFrame):
    def __init__(self, parent, adb_helper, config_manager, log_func,
                 on_config_changed=None, on_device_aliases_changed=None):
        super().__init__(parent, corner_radius=10)
        self.adb_helper = adb_helper
        self.config_manager = config_manager
        self.log = log_func
        self.on_config_changed = on_config_changed
        self.on_device_aliases_changed = on_device_aliases_changed
        self.file_helper = FileHelper(config_manager)

        self.setup_ui()

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 滚动容器：窗口高度不足以容纳所有内容时自动显示滚动条
        self.scroll_container = attach_scrollable(self)
        self.scroll_container.grid(row=0, column=0, sticky="nsew")
        outer = self.scroll_container

        # 0. 分类下拉选择
        self.category_var = ctk.StringVar(value="通用")
        self.category_selector = ctk.CTkOptionMenu(
            outer,
            values=["通用", "设备管理"],
            command=self.on_category_change,
            variable=self.category_var,
            corner_radius=8,
            height=32,
        )
        self.category_selector.pack(pady=(10, 16), padx=10, fill="x")
        optimize_combobox_width(self.category_selector, offset=200)

        # 分类容器
        self.container_general = ctk.CTkFrame(outer, fg_color="transparent")
        self.container_devices = ctk.CTkFrame(outer, fg_color="transparent")

        self._build_general_section(self.container_general)
        self._build_device_alias_section(self.container_devices)

        self.on_category_change(self.category_var.get())

    def on_category_change(self, value):
        if value == "通用":
            self.container_devices.pack_forget()
            self.container_general.pack(fill="both", expand=True)
        elif value == "设备管理":
            self.container_general.pack_forget()
            self.container_devices.pack(fill="both", expand=True)

    def _build_general_section(self, container):
        # 1. 全局路径设置
        frame_path = ctk.CTkFrame(container)
        frame_path.pack(pady=2, padx=10, fill="x")

        ctk.CTkLabel(frame_path, text="APK 默认目录:", font=ctk.CTkFont(weight="bold")).pack(pady=(3, 1), anchor="w", padx=10)

        self.entry_apk_dir = ctk.CTkEntry(frame_path, height=26)
        self.entry_apk_dir.pack(pady=1, padx=10, fill="x")
        self.entry_apk_dir.insert(0, self.config_manager.get_apk_dir())

        ctk.CTkButton(frame_path, text="选择文件夹...", command=self.browse_apk_dir, height=26).pack(pady=(0, 3), padx=10, anchor="e")

        # 1.5 临时文件目录
        ctk.CTkLabel(frame_path, text="临时文件目录 (Temp):", font=ctk.CTkFont(weight="bold")).pack(pady=(3, 1), anchor="w", padx=10)

        self.entry_temp_dir = ctk.CTkEntry(frame_path, state="readonly", height=26)
        self.entry_temp_dir.pack(pady=1, padx=10, fill="x")
        self.entry_temp_dir.configure(state="normal")
        self.entry_temp_dir.insert(0, self.config_manager.get_temp_dir())
        self.entry_temp_dir.configure(state="readonly")

        frame_temp_btns = ctk.CTkFrame(frame_path, fg_color="transparent")
        frame_temp_btns.pack(pady=(0, 3), padx=10, fill="x")

        ctk.CTkButton(frame_temp_btns, text="设置路径", command=self.action_set_temp_path, width=100, height=26).pack(side="right", padx=(10, 0))
        ctk.CTkButton(frame_temp_btns, text="打开目录", command=self.action_open_temp, width=100, height=26).pack(side="right")

        # 2. 自动化行为设置
        frame_automation = ctk.CTkFrame(container)
        frame_automation.pack(pady=2, padx=10, fill="x")

        ctk.CTkLabel(frame_automation, text="个性化设置:", font=ctk.CTkFont(weight="bold")).pack(pady=(3, 1), anchor="w", padx=10)

        self.check_auto_launch = ctk.CTkCheckBox(
            frame_automation,
            text="成功清除数据或安装 APK 后，自动打开 App",
            command=self.toggle_auto_launch
        )
        self.check_auto_launch.pack(pady=1, padx=10, anchor="w")

        self.check_hide_global_log = ctk.CTkCheckBox(
            frame_automation,
            text="隐藏右侧全局日志",
            command=self.toggle_hide_global_log
        )
        self.check_hide_global_log.pack(pady=(1, 3), padx=10, anchor="w")
        
        # Initialize state
        if self.config_manager.get_auto_launch_enabled():
            self.check_auto_launch.select()
        else:
            self.check_auto_launch.deselect()
            
        if self.config_manager.get_hide_global_log():
            self.check_hide_global_log.select()
        else:
            self.check_hide_global_log.deselect()

        # 3. App 录入管理
        frame_add = ctk.CTkFrame(container)
        frame_add.pack(pady=2, padx=10, fill="x")

        ctk.CTkLabel(frame_add, text="新增/修改 App 配置:", font=ctk.CTkFont(weight="bold")).pack(pady=(3, 1), anchor="w", padx=10)

        self.combo_app_name = ctk.CTkComboBox(frame_add, command=self.on_app_name_select, height=26)
        self.combo_app_name.pack(pady=1, padx=10, fill="x")
        self.combo_app_name.set("")

        self.entry_app_keyword = ctk.CTkEntry(frame_add, placeholder_text="APK 文件名关键字 (如: wechat)", height=26)
        self.entry_app_keyword.pack(pady=1, padx=10, fill="x")

        self.entry_app_pkg = ctk.CTkEntry(frame_add, placeholder_text="App 包名 (如: com.tencent.mm)", height=26)
        self.entry_app_pkg.pack(pady=1, padx=10, fill="x")

        frame_action = ctk.CTkFrame(frame_add, fg_color="transparent")
        frame_action.pack(pady=(3, 3), padx=10, fill="x")
        frame_action.grid_columnconfigure(0, weight=7)
        frame_action.grid_columnconfigure(1, weight=3)

        ctk.CTkButton(frame_action, text="保存 / 更新", command=self.save_app_config, height=26, fg_color="#2d7d46", hover_color="#1e5c32").grid(row=0, column=0, padx=(0, 5), sticky="ew")
        ctk.CTkButton(frame_action, text="删除", command=self.delete_app_config, height=26, fg_color="#c42b1c", hover_color="#8a1f15").grid(row=0, column=1, padx=(5, 0), sticky="ew")

        # 初始化 App 下拉列表
        self.refresh_app_name_combo()

        # 4. Logcat 自定义过滤词管理
        frame_filter = ctk.CTkFrame(container)
        frame_filter.pack(pady=2, padx=10, fill="x")

        ctk.CTkLabel(frame_filter, text="Logcat 自定义过滤词:", font=ctk.CTkFont(weight="bold")).pack(pady=(3, 1), anchor="w", padx=10)

        self.combo_filter_word = ctk.CTkComboBox(frame_filter, command=self.on_filter_word_select, height=26)
        self.combo_filter_word.pack(pady=1, padx=10, fill="x")
        self.combo_filter_word.set("")

        self.entry_filter_word = ctk.CTkEntry(frame_filter, placeholder_text="过滤词 (包名 / 关键字，如: com.xxx 或 Exception)", height=26)
        self.entry_filter_word.pack(pady=1, padx=10, fill="x")

        frame_filter_action = ctk.CTkFrame(frame_filter, fg_color="transparent")
        frame_filter_action.pack(pady=(3, 3), padx=10, fill="x")
        frame_filter_action.grid_columnconfigure(0, weight=7)
        frame_filter_action.grid_columnconfigure(1, weight=3)

        ctk.CTkButton(frame_filter_action, text="保存 / 更新", command=self.save_filter_word, height=26,
                      fg_color="#2d7d46", hover_color="#1e5c32").grid(row=0, column=0, padx=(0, 5), sticky="ew")
        ctk.CTkButton(frame_filter_action, text="删除", command=self.delete_filter_word, height=26,
                      fg_color="#c42b1c", hover_color="#8a1f15").grid(row=0, column=1, padx=(5, 0), sticky="ew")

        self.refresh_filter_word_combo()

    def browse_apk_dir(self):
        path = filedialog.askdirectory(parent=self)
        if path:
            self.entry_apk_dir.delete(0, "end")
            self.entry_apk_dir.insert(0, path)
            self.config_manager.set_apk_dir(path)
            self.log(f"已更新 APK 目录: {path}", "SUCCESS")
            if self.on_config_changed:
                self.on_config_changed()

    def action_open_temp(self):
        temp_path = self.config_manager.get_temp_dir()
        if not os.path.exists(temp_path):
            os.makedirs(temp_path)
        success = self.file_helper.open_temp_directory()
        if not success:
            self.log("打开临时目录失败", "ERROR")

    def action_set_temp_path(self):
        path = filedialog.askdirectory(title="选择临时文件存储目录", parent=self)
        if path:
            self.config_manager.set_temp_dir(path)
            self.entry_temp_dir.configure(state="normal")
            self.entry_temp_dir.delete(0, "end")
            self.entry_temp_dir.insert(0, path)
            self.entry_temp_dir.configure(state="readonly")
            self.log(f"临时文件目录已更改为: {path}", "INFO")

    def refresh_app_name_combo(self):
        apps = self.config_manager.get_apps()
        app_names = [app['name'] for app in apps]
        if app_names:
            self.combo_app_name.configure(values=app_names)
        else:
            self.combo_app_name.configure(values=[])

    def on_app_name_select(self, choice):
        apps = self.config_manager.get_apps()
        for app in apps:
            if app['name'] == choice:
                self.entry_app_keyword.delete(0, "end")
                self.entry_app_keyword.insert(0, app.get('keyword', ''))
                self.entry_app_pkg.delete(0, "end")
                self.entry_app_pkg.insert(0, app.get('pkg', ''))
                break

    def save_app_config(self):
        name = self.combo_app_name.get().strip()
        keyword = self.entry_app_keyword.get().strip()
        pkg = self.entry_app_pkg.get().strip()
        
        if not name or not pkg:
            messagebox.showwarning("提示", "名称和包名不能为空", parent=self)
            return
            
        self.config_manager.add_app(name, pkg, keyword)
        self.log(f"已保存 App 配置: {name}", "SUCCESS")
        
        # Clear inputs
        self.combo_app_name.set("")
        self.entry_app_keyword.delete(0, "end")
        self.entry_app_pkg.delete(0, "end")
        
        self.refresh_app_name_combo()
        
        if self.on_config_changed:
            self.on_config_changed()

    def delete_app_config(self):
        name = self.combo_app_name.get().strip()
        if not name:
            messagebox.showwarning("提示", "请选择要删除的 App", parent=self)
            return
            
        apps = self.config_manager.get_apps()
        if not any(app['name'] == name for app in apps):
            messagebox.showwarning("提示", f"App [{name}] 不存在", parent=self)
            return
            
        confirm = messagebox.askyesno("删除确认", f"确定要删除 App [{name}] 的配置吗？", parent=self)
        if confirm:
            success = self.config_manager.delete_app(name)
            if success:
                self.log(f"已删除 App 配置: {name}", "SUCCESS")
                self.combo_app_name.set("")
                self.entry_app_keyword.delete(0, "end")
                self.entry_app_pkg.delete(0, "end")
                
                self.refresh_app_name_combo()
                
                if self.on_config_changed:
                    self.on_config_changed()
            else:
                self.log(f"删除 App 配置失败: {name}", "ERROR")

    def toggle_auto_launch(self):
        state = self.check_auto_launch.get() == 1
        self.config_manager.set_auto_launch_enabled(state)
        status = "开启" if state else "关闭"
        self.log(f"自动化行为已更新: {status}自动打开 App", "INFO")
        if self.on_config_changed:
            self.on_config_changed()

    def toggle_hide_global_log(self):
        state = self.check_hide_global_log.get() == 1
        self.config_manager.set_hide_global_log(state)
        status = "隐藏右侧日志" if state else "显示右侧日志"
        self.log(f"布局模式已更新: {status}", "INFO")
        # Trigger main window to adjust layout
        # self.winfo_toplevel() or custom callback
        # Actually, maybe MainWindow handles it if we pass a specific callback or rely on master.
        # But we can also call a method on toplevel directly:
        toplevel = self.winfo_toplevel()
        if hasattr(toplevel, 'toggle_global_log'):
            toplevel.toggle_global_log(state)

    # ========== Logcat 自定义过滤词 ==========
    def refresh_filter_word_combo(self):
        words = self.config_manager.get_filter_words()
        self.combo_filter_word.configure(values=words if words else [])

    def on_filter_word_select(self, choice):
        self.entry_filter_word.delete(0, "end")
        self.entry_filter_word.insert(0, choice)

    def save_filter_word(self):
        """下拉框值为空 => 新增；下拉框已选中某词 => 改名为 Entry 的新值"""
        old = self.combo_filter_word.get().strip()
        new = self.entry_filter_word.get().strip()
        if not new:
            messagebox.showwarning("提示", "过滤词不能为空", parent=self)
            return

        if old and old in self.config_manager.get_filter_words():
            # 更新
            if old == new:
                return
            if not self.config_manager.update_filter_word(old, new):
                messagebox.showwarning("提示", f"过滤词 [{new}] 已存在或无效", parent=self)
                return
            self.log(f"已更新过滤词: {old} -> {new}", "SUCCESS")
        else:
            # 新增
            if not self.config_manager.add_filter_word(new):
                messagebox.showwarning("提示", f"过滤词 [{new}] 已存在", parent=self)
                return
            self.log(f"已新增过滤词: {new}", "SUCCESS")

        self.combo_filter_word.set("")
        self.entry_filter_word.delete(0, "end")
        self.refresh_filter_word_combo()

        if self.on_config_changed:
            self.on_config_changed()

    def delete_filter_word(self):
        word = self.combo_filter_word.get().strip()
        if not word:
            messagebox.showwarning("提示", "请先选择要删除的过滤词", parent=self)
            return
        if word not in self.config_manager.get_filter_words():
            messagebox.showwarning("提示", f"过滤词 [{word}] 不存在", parent=self)
            return
        if messagebox.askyesno("删除确认", f"确定要删除过滤词 [{word}] 吗？", parent=self):
            if self.config_manager.delete_filter_word(word):
                self.log(f"已删除过滤词: {word}", "SUCCESS")
                self.combo_filter_word.set("")
                self.entry_filter_word.delete(0, "end")
                self.refresh_filter_word_combo()
                if self.on_config_changed:
                    self.on_config_changed()
            else:
                self.log(f"删除过滤词失败: {word}", "ERROR")

    # ========== 设备别名管理 ==========
    def _build_device_alias_section(self, container):
        # 标题区
        header_frame = ctk.CTkFrame(container, fg_color="transparent")
        header_frame.pack(pady=(4, 0), padx=10, fill="x")
        ctk.CTkLabel(header_frame, text="设备别名管理",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header_frame,
                     text="为设备序列号设置易识别的名称，将在顶部设备下拉框中显示",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(2, 0))

        # 顶部操作按钮条
        action_bar = ctk.CTkFrame(container, fg_color="transparent")
        action_bar.pack(pady=(8, 6), padx=10, fill="x")

        ctk.CTkButton(action_bar, text="+ 添加设备",
                      command=self.action_add_device_alias,
                      height=30, width=110).pack(side="left", padx=(0, 6))
        ctk.CTkButton(action_bar, text="刷新", command=self.refresh_device_alias_tree,
                      height=30, width=70, fg_color="transparent", border_width=1,
                      text_color=("gray10", "#DCE4EE")).pack(side="left", padx=(0, 6))

        ctk.CTkButton(action_bar, text="导出", command=self.action_export_device_aliases,
                      height=30, width=70, fg_color="transparent", border_width=1,
                      text_color=("gray10", "#DCE4EE")).pack(side="right", padx=(6, 0))
        ctk.CTkButton(action_bar, text="导入", command=self.action_import_device_aliases,
                      height=30, width=70, fg_color="transparent", border_width=1,
                      text_color=("gray10", "#DCE4EE")).pack(side="right")

        # 卡片列表容器（不再单独滚动，跟随外层 scroll_container）
        self.alias_list_frame = ctk.CTkFrame(
            container, fg_color=("gray92", "gray16"), corner_radius=8,
        )
        self.alias_list_frame.pack(padx=10, pady=(0, 8), fill="both", expand=True)

        self.refresh_device_alias_tree()

    def refresh_device_alias_tree(self):
        """重建卡片列表。"""
        if not hasattr(self, "alias_list_frame"):
            return

        # 清空旧卡片
        for child in self.alias_list_frame.winfo_children():
            child.destroy()

        aliases = self.config_manager.get_device_aliases()
        connected = set(self.adb_helper.get_connected_devices())

        # 排序：在线 + 已命名优先，其次离线已命名，最后在线未命名
        listed_ids = set(aliases.keys()) | connected
        def sort_key(did):
            is_connected = did in connected
            has_alias = did in aliases
            # (优先组, 名称)
            group = 0 if (is_connected and has_alias) else (1 if has_alias else 2)
            name = aliases.get(did, "").lower() if has_alias else did
            return (group, name)

        sorted_ids = sorted(listed_ids, key=sort_key)

        if not sorted_ids:
            empty = ctk.CTkLabel(
                self.alias_list_frame,
                text="暂无设备\n连接设备或点击"+'"+ 添加设备"' + "新增映射",
                text_color="gray",
                font=ctk.CTkFont(size=12),
                justify="center",
            )
            empty.pack(pady=40)
            return

        for device_id in sorted_ids:
            alias = aliases.get(device_id, "")
            is_connected = device_id in connected
            self._build_alias_card(self.alias_list_frame, device_id, alias, is_connected)

    def _build_alias_card(self, parent, device_id, alias, is_connected):
        """单个设备卡片。"""
        card = ctk.CTkFrame(parent, fg_color=("white", "gray22"), corner_radius=6)
        card.pack(fill="x", padx=4, pady=3)

        # 主行：状态点 + 文本区 + 操作按钮
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=8)
        row.grid_columnconfigure(1, weight=1)

        # 状态圆点（用 Label 字符 ● 着色实现）
        dot_color = "#2cc985" if is_connected else "#888888"
        dot = ctk.CTkLabel(row, text="●", text_color=dot_color,
                           font=ctk.CTkFont(size=14), width=16)
        dot.grid(row=0, column=0, rowspan=2, padx=(0, 8), sticky="n", pady=(2, 0))

        # 别名（大字）
        alias_text = alias if alias else "(未命名)"
        alias_color = None if alias else "gray"
        lbl_alias = ctk.CTkLabel(
            row, text=alias_text,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=alias_color or ("gray10", "#DCE4EE"),
            anchor="w",
        )
        lbl_alias.grid(row=0, column=1, sticky="ew")

        # 设备号（小字、灰色、等宽）
        lbl_id = ctk.CTkLabel(
            row, text=device_id,
            font=ctk.CTkFont(size=11, family="Consolas"),
            text_color="gray", anchor="w",
        )
        lbl_id.grid(row=1, column=1, sticky="ew", pady=(1, 0))

        # 状态文字（小字）
        status_text = "已连接" if is_connected else "离线"
        status_color = "#2cc985" if is_connected else "#888888"
        lbl_status = ctk.CTkLabel(
            row, text=status_text,
            font=ctk.CTkFont(size=11),
            text_color=status_color, anchor="e", width=50,
        )
        lbl_status.grid(row=0, column=2, padx=(8, 8), sticky="e")

        # 操作按钮（编辑 / 删除）
        btn_edit_text = "编辑" if alias else "命名"
        ctk.CTkButton(
            row, text=btn_edit_text,
            command=lambda did=device_id: self._edit_device_alias(did),
            width=56, height=26,
        ).grid(row=0, column=3, padx=(0, 4), rowspan=2)

        del_btn = ctk.CTkButton(
            row, text="删除",
            command=lambda did=device_id: self._delete_device_alias_by_id(did),
            width=56, height=26,
            fg_color="#c42b1c", hover_color="#8a1f15",
            state="normal" if alias else "disabled",
        )
        del_btn.grid(row=0, column=4, rowspan=2)

    def _prompt_alias_dialog(self, device_id_default="", alias_default="", lock_device_id=False):
        """弹出输入对话框，返回 (device_id, alias) 或 None。lock_device_id=True 时设备号只读。"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("设备别名")
        dialog.geometry("420x200")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="设备序列号:", font=ctk.CTkFont(weight="bold")).pack(pady=(15, 2), padx=20, anchor="w")
        entry_id = ctk.CTkEntry(dialog, width=380, font=ctk.CTkFont(family="Consolas"))
        entry_id.pack(padx=20, fill="x")
        entry_id.insert(0, device_id_default)
        if lock_device_id:
            entry_id.configure(state="disabled")

        ctk.CTkLabel(dialog, text="别名:", font=ctk.CTkFont(weight="bold")).pack(pady=(10, 2), padx=20, anchor="w")
        entry_alias = ctk.CTkEntry(dialog, width=380, placeholder_text="例如：测试机 A、Pixel 6 Pro")
        entry_alias.pack(padx=20, fill="x")
        entry_alias.insert(0, alias_default)
        entry_alias.focus_set()
        entry_alias.icursor("end")

        result = {"value": None}

        def on_ok():
            did = entry_id.get().strip()
            al = entry_alias.get().strip()
            if not did or not al:
                messagebox.showwarning("提示", "设备号和别名都不能为空", parent=dialog)
                return
            result["value"] = (did, al)
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=10, padx=20, fill="x")
        ctk.CTkButton(btn_frame, text="确定", command=on_ok, width=80, height=26).pack(side="right", padx=(5, 0))
        ctk.CTkButton(btn_frame, text="取消", command=on_cancel, width=80, height=26,
                      fg_color="transparent", border_width=1,
                      text_color=("gray10", "#DCE4EE")).pack(side="right")

        dialog.bind("<Return>", lambda e: on_ok())
        dialog.bind("<Escape>", lambda e: on_cancel())
        self.wait_window(dialog)
        return result["value"]

    def action_add_device_alias(self):
        """新增：从空白开始（如果有当前设备号则预填）。"""
        device_id_default = self.adb_helper.current_device_id or ""
        alias_default = self.config_manager.get_device_alias(device_id_default) if device_id_default else ""

        result = self._prompt_alias_dialog(device_id_default, alias_default, lock_device_id=False)
        if not result:
            return
        device_id, alias = result
        self.config_manager.set_device_alias(device_id, alias)
        self.log(f"已保存设备别名: {device_id} -> {alias}", "SUCCESS")
        self.refresh_device_alias_tree()
        if self.on_device_aliases_changed:
            self.on_device_aliases_changed()

    def _edit_device_alias(self, device_id):
        """点击单个卡片的"编辑/命名"按钮。设备号锁定。"""
        alias_default = self.config_manager.get_device_alias(device_id)
        result = self._prompt_alias_dialog(device_id, alias_default, lock_device_id=True)
        if not result:
            return
        _, alias = result
        self.config_manager.set_device_alias(device_id, alias)
        self.log(f"已保存设备别名: {device_id} -> {alias}", "SUCCESS")
        self.refresh_device_alias_tree()
        if self.on_device_aliases_changed:
            self.on_device_aliases_changed()

    def _delete_device_alias_by_id(self, device_id):
        alias = self.config_manager.get_device_alias(device_id)
        if not alias:
            return
        if messagebox.askyesno("删除确认", f"确定要删除别名 [{alias}] (设备 {device_id}) 吗？", parent=self):
            self.config_manager.delete_device_alias(device_id)
            self.log(f"已删除设备别名: {device_id}", "SUCCESS")
            self.refresh_device_alias_tree()
            if self.on_device_aliases_changed:
                self.on_device_aliases_changed()

    def action_export_device_aliases(self):
        aliases = self.config_manager.get_device_aliases()
        if not aliases:
            messagebox.showinfo("提示", "暂无别名可导出", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出设备别名",
            defaultextension=".json",
            initialfile="device_aliases.json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(aliases, f, indent=4, ensure_ascii=False)
            self.log(f"已导出 {len(aliases)} 条设备别名到: {path}", "SUCCESS")
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self)
            self.log(f"导出设备别名失败: {e}", "ERROR")

    def action_import_device_aliases(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="导入设备别名",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("导入失败", f"无法解析 JSON 文件: {e}", parent=self)
            return
        if not isinstance(data, dict) or not data:
            messagebox.showwarning("提示", "JSON 文件格式应为 {设备号: 别名} 的对象", parent=self)
            return

        choice = messagebox.askyesnocancel(
            "导入方式",
            "是：合并到现有列表（同设备号会被覆盖）\n否：替换全部现有别名\n取消：放弃导入",
            parent=self,
        )
        if choice is None:
            return
        if choice:
            count = self.config_manager.merge_device_aliases(data)
            self.log(f"已合并设备别名，新增/更新 {count} 条", "SUCCESS")
        else:
            self.config_manager.replace_device_aliases(data)
            self.log(f"已替换设备别名（共 {len(self.config_manager.get_device_aliases())} 条）", "SUCCESS")

        self.refresh_device_alias_tree()
        if self.on_device_aliases_changed:
            self.on_device_aliases_changed()

