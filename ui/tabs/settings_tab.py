import customtkinter as ctk
import tkinter.messagebox as messagebox
import tkinter.filedialog as filedialog

from ui.utils import optimize_combobox_width
from core.file_helper import FileHelper

class SettingsTab(ctk.CTkFrame):
    def __init__(self, parent, adb_helper, config_manager, log_func, on_config_changed=None):
        super().__init__(parent, corner_radius=10)
        self.adb_helper = adb_helper
        self.config_manager = config_manager
        self.log = log_func
        self.on_config_changed = on_config_changed
        self.file_helper = FileHelper()
        
        self.setup_ui()

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # 1. 全局路径设置
        frame_path = ctk.CTkFrame(self)
        frame_path.pack(pady=5, padx=10, fill="x")
        
        ctk.CTkLabel(frame_path, text="APK 默认目录:", font=ctk.CTkFont(weight="bold")).pack(pady=(5, 2), anchor="w", padx=10)
        
        self.entry_apk_dir = ctk.CTkEntry(frame_path)
        self.entry_apk_dir.pack(pady=2, padx=10, fill="x")
        self.entry_apk_dir.insert(0, self.config_manager.get_apk_dir())
        
        ctk.CTkButton(frame_path, text="选择文件夹...", command=self.browse_apk_dir).pack(pady=(0, 5), padx=10, anchor="e")

        # 1.5 临时文件管理
        frame_temp = ctk.CTkFrame(frame_path, fg_color="transparent")
        frame_temp.pack(pady=(2, 5), padx=10, fill="x")
        
        ctk.CTkLabel(frame_temp, text="临时文件管理 (Temp)：", font=ctk.CTkFont(weight="bold")).pack(side="left")
        
        ctk.CTkButton(frame_temp, text="清空", command=self.action_clear_temp, fg_color="#c42b1c", hover_color="#8a1f15", width=80).pack(side="right", padx=(10, 0))
        ctk.CTkButton(frame_temp, text="打开目录", command=self.action_open_temp, width=100).pack(side="right")

        # 2. 全局默认 (置顶) App 设置
        frame_pinned = ctk.CTkFrame(self)
        frame_pinned.pack(pady=5, padx=10, fill="x")
        
        ctk.CTkLabel(frame_pinned, text="置顶App 设置:", font=ctk.CTkFont(weight="bold")).pack(pady=(5, 2), anchor="w", padx=10)
        
        frame_pinned_content = ctk.CTkFrame(frame_pinned, fg_color="transparent")
        frame_pinned_content.pack(pady=2, padx=10, fill="x")
        
        ctk.CTkLabel(frame_pinned_content, text="当前置顶 App:").pack(side="left", padx=(0, 10))
        
        self.pinned_app_selector = ctk.CTkComboBox(frame_pinned_content, command=self.on_pinned_app_change, width=200)
        self.pinned_app_selector.pack(side="left", fill="x", expand=True, pady=(0, 5))
        optimize_combobox_width(self.pinned_app_selector)
        
        # 初始化置顶列表
        self.refresh_pinned_app_list()

        # 3. 自动化行为设置
        frame_automation = ctk.CTkFrame(self)
        frame_automation.pack(pady=5, padx=10, fill="x")

        ctk.CTkLabel(frame_automation, text="个性化设置:", font=ctk.CTkFont(weight="bold")).pack(pady=(5, 2), anchor="w", padx=10)

        self.check_auto_launch = ctk.CTkCheckBox(
            frame_automation, 
            text="成功清除数据或安装 APK 后，自动打开 App",
            command=self.toggle_auto_launch
        )
        self.check_auto_launch.pack(pady=2, padx=10, anchor="w")
        
        self.check_hide_global_log = ctk.CTkCheckBox(
            frame_automation,
            text="隐藏右侧全局日志",
            command=self.toggle_hide_global_log
        )
        self.check_hide_global_log.pack(pady=(2, 5), padx=10, anchor="w")
        
        # Initialize state
        if self.config_manager.get_auto_launch_enabled():
            self.check_auto_launch.select()
        else:
            self.check_auto_launch.deselect()
            
        if self.config_manager.get_hide_global_log():
            self.check_hide_global_log.select()
        else:
            self.check_hide_global_log.deselect()

        # 4. App 录入管理
        frame_add = ctk.CTkFrame(self)
        frame_add.pack(pady=5, padx=10, fill="x")
        
        ctk.CTkLabel(frame_add, text="新增/修改 App 配置:", font=ctk.CTkFont(weight="bold")).pack(pady=(5, 2), anchor="w", padx=10)
        
        self.combo_app_name = ctk.CTkComboBox(frame_add, command=self.on_app_name_select)
        self.combo_app_name.pack(pady=2, padx=10, fill="x")
        self.combo_app_name.set("")
        
        self.entry_app_keyword = ctk.CTkEntry(frame_add, placeholder_text="APK 文件名关键字 (如: wechat)")
        self.entry_app_keyword.pack(pady=2, padx=10, fill="x")
        
        self.entry_app_pkg = ctk.CTkEntry(frame_add, placeholder_text="App 包名 (如: com.tencent.mm)")
        self.entry_app_pkg.pack(pady=2, padx=10, fill="x")
        
        frame_action = ctk.CTkFrame(frame_add, fg_color="transparent")
        frame_action.pack(pady=5, padx=10, fill="x")
        frame_action.grid_columnconfigure(0, weight=7)
        frame_action.grid_columnconfigure(1, weight=3)
        
        ctk.CTkButton(frame_action, text="保存 / 更新", command=self.save_app_config, fg_color="#2d7d46", hover_color="#1e5c32").grid(row=0, column=0, padx=(0, 5), sticky="ew")
        ctk.CTkButton(frame_action, text="删除", command=self.delete_app_config, fg_color="#c42b1c", hover_color="#8a1f15").grid(row=0, column=1, padx=(5, 0), sticky="ew")

        # 初始化 App 下拉列表
        self.refresh_app_name_combo()

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
        success = self.file_helper.open_temp_directory()
        if not success:
            self.log("打开临时目录失败", "ERROR")

    def action_clear_temp(self):
        confirm = messagebox.askyesno("清空确认", "确定要清空所有临时文件吗？\n此操作不可恢复。", parent=self)
        if confirm:
            success, count = self.file_helper.clear_temp_directory()
            if success:
                self.log(f"成功清理临时目录，共删除 {count} 个文件/文件夹。", "SUCCESS")
            else:
                self.log(f"清理临时目录时发生部分错误，删除了 {count} 个文件/文件夹。", "ERROR")

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
        
        # 刷新相关列表
        self.refresh_app_name_combo()
        self.refresh_pinned_app_list()
        
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
                self.refresh_pinned_app_list()
                
                if self.on_config_changed:
                    self.on_config_changed()
            else:
                self.log(f"删除 App 配置失败: {name}", "ERROR")

    def refresh_pinned_app_list(self):
        apps = self.config_manager.get_apps()
        app_names = [app['name'] for app in apps]
        self.pinned_app_selector.configure(values=app_names)
        
        pinned = self.config_manager.get_pinned_app()
        if pinned and pinned in app_names:
            self.pinned_app_selector.set(pinned)
        elif app_names:
            self.pinned_app_selector.set("请选择置顶 App")
        else:
            self.pinned_app_selector.set("暂无 App")

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

    def on_pinned_app_change(self, choice):
        self.config_manager.set_pinned_app(choice)
        self.log(f"已将 [{choice}] 设为全局默认置顶", "SUCCESS")
        
        if self.on_config_changed:
            self.on_config_changed()
