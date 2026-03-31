import customtkinter as ctk
import tkinter.messagebox as messagebox
import tkinter.ttk as ttk
import os
import datetime
import math

from ui.utils import optimize_combobox_width

class APKManagerTab(ctk.CTkFrame):
    def __init__(self, parent, adb_helper, config_manager, log_func):
        super().__init__(parent, corner_radius=10)
        self.adb_helper = adb_helper
        self.config_manager = config_manager
        self.log = log_func
        
        self.tree_item_map = {}
        self.hidden_apks = set(self.config_manager.get_hidden_apks())

        self.setup_ui()
        # Initial load
        self.refresh_apk_manager_list()

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. 顶部 App 选择区
        frame_top = ctk.CTkFrame(self, fg_color="transparent")
        frame_top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        
        ctk.CTkLabel(frame_top, text="筛选 App:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 10))
        
        self.apk_manager_app_selector = ctk.CTkComboBox(frame_top, command=self.on_apk_manager_app_selected)
        self.apk_manager_app_selector.pack(side="left", fill="x", expand=True)
        optimize_combobox_width(self.apk_manager_app_selector)
        self.apk_manager_app_selector.set("加载中...")

        # 2. 中间 APK 列表区 (Treeview)
        frame_list = ctk.CTkFrame(self)
        frame_list.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        frame_list.grid_columnconfigure(0, weight=1)
        frame_list.grid_rowconfigure(0, weight=1)

        # 定义 Treeview 样式
        style = ttk.Style()
        style.theme_use("default") 
        
        is_light = ctk.get_appearance_mode() == "Light"
        bg_color = "#ffffff" if is_light else "#2b2b2b"
        fg_color = "#000000" if is_light else "#dce4ee"
        field_bg = "#ffffff" if is_light else "#2b2b2b"
        header_bg = "#e5e5e5" if is_light else "#333333"
        header_fg = "#000000" if is_light else "#dce4ee"
        
        style.configure("Treeview", 
                        background=bg_color, 
                        foreground=fg_color, 
                        fieldbackground=field_bg,
                        rowheight=25,
                        font=("Arial", 10))
        style.configure("Treeview.Heading", 
                        background=header_bg, 
                        foreground=header_fg,
                        font=("Arial", 10, "bold"))
        style.map("Treeview", background=[('selected', '#1f6aa5')])

        # 隐藏文件的灰色标签
        self.apk_tree_tag_hidden_fg = "#999999" if is_light else "#666666"

        columns = ("filename", "size", "mtime")
        self.apk_tree = ttk.Treeview(frame_list, columns=columns, show="headings", selectmode="extended")
        
        self.apk_tree.heading("filename", text="APK 文件名", anchor="w")
        self.apk_tree.heading("size", text="大小 (MB)", anchor="center")
        self.apk_tree.heading("mtime", text="修改时间", anchor="center")
        
        self.apk_tree.column("filename", anchor="w", width=300)
        self.apk_tree.column("size", anchor="center", width=80)
        self.apk_tree.column("mtime", anchor="center", width=140)
        
        self.apk_tree.grid(row=0, column=0, sticky="nsew")

        # 滚动条
        scrollbar = ctk.CTkScrollbar(frame_list, command=self.apk_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.apk_tree.configure(yscrollcommand=scrollbar.set)
        
        # 3. 底部操作区
        frame_bottom = ctk.CTkFrame(self, fg_color="transparent")
        frame_bottom.grid(row=2, column=0, sticky="ew", padx=10, pady=(5, 10))

        ctk.CTkButton(frame_bottom, text="隐藏 / 取消隐藏", command=self.toggle_hide_apks, width=120, fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE")).pack(side="left", padx=(0, 10))
        ctk.CTkButton(frame_bottom, text="刷新列表", command=self.refresh_apk_manager_list, width=100, fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE")).pack(side="left", padx=(0, 10))
        
        ctk.CTkButton(frame_bottom, text="删除选中的 APK", command=self.delete_selected_apks, fg_color="#c42b1c", hover_color="#8a1f15").pack(side="right", padx=0)

    def on_apk_manager_app_selected(self, app_name):
        self.refresh_apk_manager_list()

    def refresh_apk_manager_list(self):
        # Update app selector values
        apps = self.config_manager.get_apps()
        app_names = [app["name"] for app in apps]
        
        if not app_names:
            self.apk_manager_app_selector.configure(values=["(无数据)"])
            self.apk_manager_app_selector.set("(无数据)")
            self.clear_apk_tree()
            return

        self.apk_manager_app_selector.configure(values=app_names)
        
        current_selection = self.apk_manager_app_selector.get()
        if current_selection not in app_names and app_names:
             self.apk_manager_app_selector.set(app_names[0])
             current_selection = app_names[0]
        
        # Find keyword for selected app
        keyword = ""
        for app in apps:
            if app['name'] == current_selection:
                keyword = app.get('keyword', "")
                break
        
        apk_dir = self.config_manager.get_apk_dir()
        if not apk_dir or not os.path.exists(apk_dir):
            self.clear_apk_tree()
            return

        # Scan APKs (递归扫描子文件夹，最大深度3层)
        self.clear_apk_tree()
        self.tree_item_map = {}

        try:
            base_path = os.path.normpath(apk_dir)
            max_depth = 3
            apk_items = []  # [(显示名, 绝对路径, size, mtime_ts)]

            for root, dirs, files in os.walk(base_path):
                depth = root.replace(base_path, "").count(os.sep)
                if depth >= max_depth:
                    dirs.clear()
                    continue
                for f in files:
                    if f.lower().endswith(".apk"):
                        if keyword and keyword.lower() not in f.lower():
                            continue
                        full_path = os.path.join(root, f)
                        rel_path = os.path.relpath(full_path, base_path)
                        size = os.path.getsize(full_path)
                        mtime_ts = os.path.getmtime(full_path)
                        apk_items.append((rel_path, full_path, size, mtime_ts))

            # 按修改时间降序排序
            apk_items.sort(key=lambda x: x[3], reverse=True)

            # 配置隐藏标签样式
            self.apk_tree.tag_configure("hidden", foreground=self.apk_tree_tag_hidden_fg)

            for rel_path, full_path, size, mtime_ts in apk_items:
                size_mb = size / (1024 * 1024)
                mtime = datetime.datetime.fromtimestamp(mtime_ts).strftime('%Y-%m-%d %H:%M')
                tags = ("hidden",) if rel_path in self.hidden_apks else ()
                item_id = self.apk_tree.insert("", "end", values=(rel_path, f"{size_mb:.2f}", mtime), tags=tags)
                self.tree_item_map[item_id] = full_path

        except Exception as e:
            self.log(f"读取 APK 列表失败: {e}", "ERROR")

    def clear_apk_tree(self):
        for item in self.apk_tree.get_children():
            self.apk_tree.delete(item)
        self.tree_item_map = {}

    def toggle_hide_apks(self):
        selection = self.apk_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择要隐藏/取消隐藏的 APK", parent=self)
            return

        hidden_count = 0
        shown_count = 0
        for item_id in selection:
            values = self.apk_tree.item(item_id, "values")
            rel_path = values[0]
            if rel_path in self.hidden_apks:
                # 取消隐藏
                self.hidden_apks.discard(rel_path)
                self.apk_tree.item(item_id, tags=())
                shown_count += 1
            else:
                # 隐藏
                self.hidden_apks.add(rel_path)
                self.apk_tree.item(item_id, tags=("hidden",))
                hidden_count += 1

        # 持久化
        self.config_manager.set_hidden_apks(list(self.hidden_apks))

        # 同步刷新智能安装列表
        main_window = self.winfo_toplevel()
        if hasattr(main_window, 'tab_app'):
            main_window.tab_app.refresh_apk_list()

        msg_parts = []
        if hidden_count:
            msg_parts.append(f"隐藏 {hidden_count} 个")
        if shown_count:
            msg_parts.append(f"取消隐藏 {shown_count} 个")
        self.log(f"APK {'，'.join(msg_parts)}", "SUCCESS")

    def delete_selected_apks(self):
        selection = self.apk_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择要删除的 APK", parent=self)
            return
            
        if not messagebox.askyesno("确认", f"确定要删除选中的 {len(selection)} 个 APK 文件吗?", parent=self):
            return
            
        count = 0
        for item_id in selection:
            file_path = self.tree_item_map.get(item_id)
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    count += 1
                except Exception as e:
                    self.log(f"删除失败: {file_path} - {e}", "ERROR")
        
        self.log(f"已删除 {count} 个 APK 文件", "SUCCESS")
        self.refresh_apk_manager_list()
        # 同步刷新智能安装列表
        main_window = self.winfo_toplevel()
        if hasattr(main_window, 'tab_app'):
            main_window.tab_app.refresh_apk_list()
