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

        ctk.CTkButton(frame_bottom, text="全选 / 取消全选", command=self.toggle_select_all_apks, width=120, fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE")).pack(side="left", padx=(0, 10))
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

        # Scan APKs
        self.clear_apk_tree()
        self.tree_item_map = {}
        
        try:
            files = os.listdir(apk_dir)
            files.sort(key=lambda x: os.path.getmtime(os.path.join(apk_dir, x)), reverse=True)
            
            count = 0
            for f in files:
                if f.lower().endswith(".apk"):
                    if keyword and keyword.lower() not in f.lower():
                        continue
                        
                    full_path = os.path.join(apk_dir, f)
                    size_mb = os.path.getsize(full_path) / (1024 * 1024)
                    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(full_path)).strftime('%Y-%m-%d %H:%M')
                    
                    item_id = self.apk_tree.insert("", "end", values=(f, f"{size_mb:.2f}", mtime))
                    self.tree_item_map[item_id] = full_path
                    count += 1
            
            if count == 0:
                pass # Tree is empty
                
        except Exception as e:
            self.log(f"读取 APK 列表失败: {e}", "ERROR")

    def clear_apk_tree(self):
        for item in self.apk_tree.get_children():
            self.apk_tree.delete(item)
        self.tree_item_map = {}

    def toggle_select_all_apks(self):
        items = self.apk_tree.get_children()
        if not items: return
        
        # Check if all selected
        selection = self.apk_tree.selection()
        if len(selection) == len(items):
            self.apk_tree.selection_remove(*items)
        else:
            self.apk_tree.selection_set(*items)

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
