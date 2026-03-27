import customtkinter as ctk
import threading
import re

class FirebaseWindow(ctk.CTkToplevel):
    def __init__(self, parent, adb_helper, package_name):
        super().__init__(parent)
        self.title(f"Firebase 实时监控 - {package_name}")
        self.geometry("900x500")
        
        self.adb_helper = adb_helper
        self.package_name = package_name
        self.is_running = True
        self.log_queue = None
        
        # 居中并保持在主窗口之上，同时绑定主从关系 (随主窗口最小化/恢复，隐藏独立任务栏图标)
        self.transient(parent.winfo_toplevel())
        
        self.setup_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # 启动日志抓取并轮询
        try:
            self.log_queue = self.adb_helper.start_firebase_logcat()
        except Exception as e:
            self.log_queue = None
            self.after(10, self.destroy)
            raise e
            
        self.update_logs()

    def setup_ui(self):
        # 1. 顶部过滤工具栏
        frame_toolbar = ctk.CTkFrame(self)
        frame_toolbar.pack(fill="x", padx=10, pady=5)
        
        # 置于最前按钮
        self.is_topmost = False
        self.btn_topmost = ctk.CTkButton(frame_toolbar, text="置于最前", width=80, command=self.toggle_topmost)
        self.btn_topmost.pack(side="left", padx=5)

        # 关键字过滤 (只显示包含该关键字的行)
        ctk.CTkLabel(frame_toolbar, text="过滤:").pack(side="left", padx=5)
        self.entry_filter = ctk.CTkEntry(frame_toolbar, width=250)
        self.entry_filter.insert(0, "Logging event: origin=app,name=")
        self.entry_filter.pack(side="left", padx=5)
        
        # 搜索高亮 (在显示的行中高亮特定字符)
        ctk.CTkLabel(frame_toolbar, text="搜索高亮:").pack(side="left", padx=5)
        self.entry_search = ctk.CTkEntry(frame_toolbar, width=150)
        self.entry_search.pack(side="left", padx=5, fill="x", expand=True)
        # 绑定搜索框改变事件以实时更新高亮
        self.entry_search.bind("<KeyRelease>", self._on_search_change)
        
        # 脱水模式 Checkbox
        self.var_dehydrate = ctk.BooleanVar(value=True)
        self.chk_dehydrate = ctk.CTkCheckBox(frame_toolbar, text="脱水模式 (精简)", variable=self.var_dehydrate, width=80)
        self.chk_dehydrate.pack(side="left", padx=10)
        
        # 清除面板按钮
        ctk.CTkButton(frame_toolbar, text="清除面板", width=80, command=self.clear_logs, fg_color="#c42b1c", hover_color="#8a1f15").pack(side="right", padx=5)
        
        # 2. 日志显示区
        self.textbox = ctk.CTkTextbox(self, wrap="word", font=ctk.CTkFont(family="Consolas", size=12))
        self.textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.textbox.configure(state="disabled")
        
        # 配置高亮标签
        self.textbox.tag_config("highlight", background="yellow", foreground="black")

    def clear_logs(self):
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")

    def _on_search_change(self, event=None):
        """当搜索高亮输入框内容改变时，重新应用高亮"""
        self.textbox.tag_remove("highlight", "1.0", "end")
        search_kw = self.entry_search.get()
        if not search_kw:
            return
            
        # 在整个文本框中查找并高亮
        start_pos = "1.0"
        while True:
            # 忽略大小写查找
            start_pos = self.textbox.search(search_kw, start_pos, stopindex="end", nocase=True)
            if not start_pos:
                break
            
            # 计算结束位置
            end_pos = f"{start_pos}+{len(search_kw)}c"
            self.textbox.tag_add("highlight", start_pos, end_pos)
            start_pos = end_pos

    def update_logs(self):
        if not self.is_running:
            return
            
        if self.log_queue:
            has_new_logs = False
            filter_kw = self.entry_filter.get().lower()
            search_kw = self.entry_search.get()
            is_dehydrate = self.var_dehydrate.get()
            
            # 尝试获取日志并更新 UI
            self.textbox.configure(state="normal")
            while not self.log_queue.empty():
                try:
                    line = self.log_queue.get_nowait()
                    # 过滤逻辑 (决定是否显示)
                    if not filter_kw or filter_kw in line.lower():
                        
                        # 脱水模式处理
                        display_line = line
                        if is_dehydrate and "Logging event:" in line:
                            # 尝试提取时间戳部分 (假设以类似 "03-17 17:35:31.573" 开头)
                            time_match = re.match(r'^(\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{3})', line)
                            time_str = time_match.group(1) if time_match else ""
                            
                            # 提取 name 和 content_type
                            name_match = re.search(r'name=([^,\s]+)', line)
                            content_type_match = re.search(r'content_type=([^,\s\}]+)', line)
                            
                            if name_match:
                                dehydrated_parts = []
                                if time_str:
                                    dehydrated_parts.append(f"[{time_str}]")
                                
                                params = []
                                params.append(f"{name_match.group(1)}")
                                if content_type_match:
                                    params.append(f"{content_type_match.group(1)}")
                                
                                if params:
                                    dehydrated_parts.append(" >> ".join(params))
                                
                                display_line = " ".join(dehydrated_parts) + "\n"

                        # 记录插入前的行号
                        start_index = self.textbox.index("end-1c")
                        self.textbox.insert("end", display_line)
                        has_new_logs = True
                        
                        # 搜索高亮逻辑 (决定是否高亮显示的部分)
                        if search_kw:
                            line_lower = display_line.lower()
                            search_kw_lower = search_kw.lower()
                            kw_len = len(search_kw)
                            start_idx = 0
                            while True:
                                start_idx = line_lower.find(search_kw_lower, start_idx)
                                if start_idx == -1:
                                    break
                                
                                # 计算在 Textbox 中的绝对位置
                                line_num, col_num = map(int, start_index.split('.'))
                                
                                hl_start = f"{line_num}.{col_num + start_idx}"
                                hl_end = f"{line_num}.{col_num + start_idx + kw_len}"
                                
                                self.textbox.tag_add("highlight", hl_start, hl_end)
                                
                                start_idx += kw_len

                except Exception:
                    break
                    
            if has_new_logs:
                self.textbox.see("end")
            self.textbox.configure(state="disabled")
            
        # 每 100ms 轮询一次
        self.after(100, self.update_logs)

    def toggle_topmost(self):
        self.is_topmost = not self.is_topmost
        self.attributes("-topmost", self.is_topmost)
        if self.is_topmost:
            self.btn_topmost.configure(fg_color="#2d7d46", hover_color="#1e5c32")
        else:
            self.btn_topmost.configure(fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"], hover_color=ctk.ThemeManager.theme["CTkButton"]["hover_color"])

    def reset_for_new_device(self):
        """设备切换时重置，重新获取新设备的 firebase 日志"""
        self.adb_helper.stop_firebase_logcat()
        self.clear_logs()
        try:
            self.adb_helper.enable_firebase_debug(self.package_name)
            self.log_queue = self.adb_helper.start_firebase_logcat()
        except Exception:
            self.log_queue = None

    def on_close(self):
        self.is_running = False
        
        # 终止 Popen 进程
        self.adb_helper.stop_firebase_logcat()
        
        # 顺手关闭该 App 的 Firebase 调试模式 (后台执行，不阻塞 UI)
        def _disable_debug():
            self.adb_helper.execute_adb_command(["adb", "shell", "setprop", "debug.firebase.analytics.app", ".none."])
            
        threading.Thread(target=_disable_debug, daemon=True).start()
        
        self.destroy()
