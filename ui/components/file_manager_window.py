import os
import threading
import customtkinter as ctk
from tkinter import ttk, filedialog, messagebox
try:
    from CTkMessagebox import CTkMessagebox
except ImportError:
    CTkMessagebox = None

class DeviceFileManagerWindow(ctk.CTkToplevel):
    def __init__(self, parent, adb_helper, config_manager):
        super().__init__(parent)
        self.title("设备文件管理器")
        self.geometry("800x600")
        
        # 绑定主从关系，隐藏独立任务栏图标，并始终保持在主窗口上方
        self.transient(parent.winfo_toplevel())
        
        self.adb_helper = adb_helper
        self.config_manager = config_manager
        
        # Get default path from config
        self.current_path = self.config_manager.get_default_device_pull_path()
        if not self.current_path.endswith("/"):
            self.current_path += "/"
            
        self.setup_ui()
        
        # Load data initially
        self.after(100, self.load_file_list)

    def setup_ui(self):
        # Top Address Bar
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=10, pady=10)
        
        self.btn_back = ctk.CTkButton(top_frame, text="上一级", width=80, command=self.go_back)
        self.btn_back.pack(side="left", padx=(0, 5))
        
        self.entry_path = ctk.CTkEntry(top_frame)
        self.entry_path.insert(0, self.current_path)
        self.entry_path.pack(side="left", fill="x", expand=True, padx=5)
        
        self.btn_jump = ctk.CTkButton(top_frame, text="跳转", width=60, command=self.jump_to_path)
        self.btn_jump.pack(side="left", padx=5)
        
        self.btn_refresh = ctk.CTkButton(top_frame, text="刷新", width=60, command=self.load_file_list)
        self.btn_refresh.pack(side="left", padx=(5, 0))
        
        # Middle File List
        list_frame = ctk.CTkFrame(self)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # Configure Treeview Style
        style = ttk.Style(self)
        style.theme_use("default")
        bg_color = self._apply_appearance_mode(ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
        text_color = self._apply_appearance_mode(ctk.ThemeManager.theme["CTkLabel"]["text_color"])
        selected_color = self._apply_appearance_mode(ctk.ThemeManager.theme["CTkButton"]["fg_color"])
        
        style.configure("DeviceFiles.Treeview",
                        background=bg_color,
                        foreground=text_color,
                        fieldbackground=bg_color,
                        borderwidth=0,
                        rowheight=25)
        style.map("DeviceFiles.Treeview",
                  background=[("selected", selected_color)])
        style.configure("DeviceFiles.Treeview.Heading",
                        background=bg_color,
                        foreground=text_color,
                        relief="flat")
        style.map("DeviceFiles.Treeview.Heading",
                  background=[("active", selected_color)])

        columns = ("name", "type", "size", "time")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", style="DeviceFiles.Treeview")
        self.tree.heading("name", text="名称", anchor="w")
        self.tree.heading("type", text="类型", anchor="center")
        self.tree.heading("size", text="大小", anchor="e")
        self.tree.heading("time", text="修改时间", anchor="center")
        
        self.tree.column("name", width=300, anchor="w")
        self.tree.column("type", width=80, anchor="center")
        self.tree.column("size", width=100, anchor="e")
        self.tree.column("time", width=150, anchor="center")
        
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.tree.bind("<Double-1>", self.on_double_click)
        
        # Bottom Operation Bar
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        self.btn_pull = ctk.CTkButton(bottom_frame, text="导出选中项 (Pull)", fg_color="#2FA572", hover_color="#10893E", command=self.pull_selected)
        self.btn_pull.pack(side="left", padx=(0, 10))
        
        self.btn_delete = ctk.CTkButton(bottom_frame, text="删除选中项", fg_color="#E74C3C", hover_color="#C0392B", command=self.delete_selected)
        self.btn_delete.pack(side="left")
        
        self.status_label = ctk.CTkLabel(bottom_frame, text="", text_color="gray")
        self.status_label.pack(side="right")

    def update_status(self, text):
        self.status_label.configure(text=text)

    def go_back(self):
        if self.current_path == "/" or self.current_path == "":
            return
        parts = [p for p in self.current_path.split("/") if p]
        if len(parts) > 0:
            parts.pop()
        new_path = "/" + "/".join(parts)
        if not new_path.endswith("/"):
            new_path += "/"
        self.entry_path.delete(0, "end")
        self.entry_path.insert(0, new_path)
        self.jump_to_path()

    def jump_to_path(self):
        path = self.entry_path.get().strip()
        if not path.endswith("/"):
            path += "/"
            self.entry_path.delete(0, "end")
            self.entry_path.insert(0, path)
        self.current_path = path
        self.load_file_list()

    def on_double_click(self, event):
        item_id = self.tree.focus()
        if not item_id:
            return
        values = self.tree.item(item_id, "values")
        if values and values[1] == "文件夹":
            folder_name = values[0]
            new_path = self.current_path + folder_name + "/"
            self.entry_path.delete(0, "end")
            self.entry_path.insert(0, new_path)
            self.jump_to_path()

    def load_file_list(self):
        self.update_status("正在加载...")
        # Clear current list
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        def _load():
            try:
                success, result = self.adb_helper.list_device_files(self.current_path)
                self.after(0, self._on_load_complete, success, result)
            except Exception as e:
                self.after(0, self._on_load_complete, False, str(e))
                
        threading.Thread(target=_load, daemon=True).start()

    def _on_load_complete(self, success, result):
        if not success:
            error_msg = str(result)
            if "No such file or directory" in error_msg:
                self.tree.insert("", "end", values=(f"目录 {self.current_path} 不存在或为空", "-", "-", "-"))
                msg = f"目录 {self.current_path} 不存在或为空"
                self.update_status(msg)
                self.adb_helper.log(msg, "WARNING")
            else:
                self.tree.insert("", "end", values=(f"加载失败: {error_msg}", "-", "-", "-"))
                self.update_status("加载失败")
            return
            
        files = result
        if not files:
            self.tree.insert("", "end", values=("(空文件夹)", "-", "-", "-"))
        else:
            # Sort: directories first, then files, both alphabetically
            dirs = sorted([f for f in files if f['is_dir']], key=lambda x: x['name'].lower())
            regular_files = sorted([f for f in files if not f['is_dir']], key=lambda x: x['name'].lower())
            
            for f in dirs:
                self.tree.insert("", "end", values=(f['name'], "文件夹", "-", f['date']))
            for f in regular_files:
                self.tree.insert("", "end", values=(f['name'], "文件", f['size'], f['date']))
                
        self.update_status(f"加载完成: {len(files)} 个项目")

    def pull_selected(self):
        selected_items = self.tree.selection()
        if not selected_items:
            return
            
        # Get actual paths
        remote_paths = []
        for item in selected_items:
            values = self.tree.item(item, "values")
            name = values[0]
            if name.startswith("(空文件夹)") or name.startswith("目录 ") or name.startswith("加载失败:"):
                continue
            remote_paths.append(self.current_path + name)
            
        if not remote_paths:
            return
            
        local_dir = filedialog.askdirectory(title="选择保存位置")
        if not local_dir:
            return
            
        self.update_status("正在导出...")
        self.adb_helper.log(f"开始导出文件: {len(remote_paths)} 个项目...", "INFO")
        
        def _pull():
            success, msg = self.adb_helper.pull_files(remote_paths, local_dir)
            self.after(0, self._on_pull_complete, success, msg)
            
        threading.Thread(target=_pull, daemon=True).start()

    def _on_pull_complete(self, success, msg):
        self.update_status("导出成功" if success else "导出部分失败")
        self.adb_helper.log(f"导出结果: {msg}", "SUCCESS" if success else "WARNING")
        if not success:
            if CTkMessagebox:
                CTkMessagebox(title="导出结果", message=msg, icon="warning", parent=self)
            else:
                messagebox.showwarning("导出结果", msg, parent=self)

    def delete_selected(self):
        selected_items = self.tree.selection()
        if not selected_items:
            return
            
        remote_paths = []
        for item in selected_items:
            values = self.tree.item(item, "values")
            name = values[0]
            if name.startswith("(空文件夹)") or name.startswith("目录 ") or name.startswith("加载失败:"):
                continue
            remote_paths.append(self.current_path + name)
            
        if not remote_paths:
            return
            
        if CTkMessagebox:
            msg = CTkMessagebox(title="危险操作确认", message=f"确定要删除选中的 {len(remote_paths)} 个项目吗？\n此操作不可恢复！",
                                icon="warning", option_1="取消", option_2="删除", parent=self)
            response = msg.get()
            if response != "删除":
                return
        else:
            response = messagebox.askyesno("危险操作确认", f"确定要删除选中的 {len(remote_paths)} 个项目吗？\n此操作不可恢复！", parent=self)
            if not response:
                return
            
        self.update_status("正在删除...")
        
        def _delete():
            success_count = 0
            for path in remote_paths:
                success, _ = self.adb_helper.delete_device_file(path)
                if success:
                    success_count += 1
            self.after(0, self._on_delete_complete, success_count, len(remote_paths))
            
        threading.Thread(target=_delete, daemon=True).start()

    def _on_delete_complete(self, success_count, total_count):
        self.update_status(f"删除完成: {success_count}/{total_count}")
        self.load_file_list()
