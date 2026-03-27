import customtkinter as ctk
import tkinter as tk
from queue import Empty
import re
import datetime

class LogcatWindow(ctk.CTkToplevel):
    def __init__(self, parent, adb_helper, default_pkg="", log_func=None):
        super().__init__(parent)
        self.adb_helper = adb_helper
        self.default_pkg = default_pkg
        self.log_func = log_func
        
        self.title("Real-time Logcat Monitor")
        self.geometry("1100x600")
        
        # 绑定主从关系，隐藏独立任务栏图标，并始终保持在主窗口上方
        self.transient(parent.winfo_toplevel())
        
        # State
        self.is_paused = False
        self.log_queue = None
        self.after_id = None
        self.search_matches = []  # List of index strings where search term was found
        self.current_match_index = -1 # Index in search_matches
        
        # PID filtering
        self.observed_pids = set()
        self.last_pkg_filter = ""
        self.pid_pattern = re.compile(r'\(\s*(\d+)\s*\):')
        # 优化正则：分别捕获 (1)时间戳 (2)级别 (3)TAG (4)PID
        # 原始格式: 03-17 11:44:24.715 E/AndroidRuntime( 9734):
        self.header_pattern = re.compile(r'^(\d{2}-\d{2}\s+[\d:\.]+)\s+([A-Z])/([^\(]+)\(\s*(\d+)\s*\):')
        self.last_tag_pid = None
        self.last_timestamp = None
        self.current_year = datetime.datetime.now().year
        
        self.setup_ui()
        
        # Override close protocol
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # Start logcat immediately
        self.start_logcat()

    def setup_ui(self):
        # 1. Top Toolbar
        frame_toolbar = ctk.CTkFrame(self)
        frame_toolbar.pack(fill="x", padx=10, pady=5)
        
        # Log Level
        ctk.CTkLabel(frame_toolbar, text="Level:").pack(side="left", padx=5)
        self.combo_level = ctk.CTkComboBox(frame_toolbar, values=["Verbose", "Debug", "Info", "Warn", "Error"], 
                                         width=80, command=self.on_level_change)
        self.combo_level.set("Error")
        self.combo_level.pack(side="left", padx=5)
        
        # Package Filter
        ctk.CTkLabel(frame_toolbar, text="过滤:").pack(side="left", padx=5)
        
        # Package Entry Frame with Clear Button
        pkg_frame = ctk.CTkFrame(frame_toolbar, fg_color="transparent")
        pkg_frame.pack(side="left", padx=5, fill="x", expand=True)
        
        self.entry_pkg = ctk.CTkEntry(pkg_frame)
        self.entry_pkg.insert(0, self.default_pkg or "")
        self.entry_pkg.pack(side="left", fill="x", expand=True)
        
        btn_clear_pkg = ctk.CTkButton(pkg_frame, text="x", width=20, height=20, 
                                      fg_color="transparent", text_color="gray", hover_color="#e0e0e0",
                                      command=lambda: [self.entry_pkg.delete(0, "end"), self.entry_pkg.focus()])
        btn_clear_pkg.pack(side="left", padx=(2, 0))
        
        # Keyword Search
        ctk.CTkLabel(frame_toolbar, text="Search:").pack(side="left", padx=5)
        
        # Search Entry Frame with Clear Button
        search_frame = ctk.CTkFrame(frame_toolbar, fg_color="transparent")
        search_frame.pack(side="left", padx=5, fill="x", expand=True)
        
        self.entry_search = ctk.CTkEntry(search_frame, placeholder_text="Keyword (PID, Exception...)")
        self.entry_search.insert(0, "PID")
        self.entry_search.pack(side="left", fill="x", expand=True)
        
        btn_clear_search = ctk.CTkButton(search_frame, text="x", width=20, height=20, 
                                         fg_color="transparent", text_color="gray", hover_color="#e0e0e0",
                                         command=lambda: [self.entry_search.delete(0, "end"), self.on_search_changed(None), self.entry_search.focus()])
        btn_clear_search.pack(side="left", padx=(2, 0))
        
        # Search Navigation (Matches counter and Next/Prev buttons)
        self.label_match_count = ctk.CTkLabel(frame_toolbar, text="0/0", width=40)
        self.label_match_count.pack(side="left", padx=(2, 5))
        
        self.btn_prev_match = ctk.CTkButton(frame_toolbar, text="↑", width=30, command=self.prev_match)
        self.btn_prev_match.pack(side="left", padx=2)
        
        self.btn_next_match = ctk.CTkButton(frame_toolbar, text="↓", width=30, command=self.next_match)
        self.btn_next_match.pack(side="left", padx=(2, 10))
        
        # Controls
        self.btn_pause = ctk.CTkButton(frame_toolbar, text="⏸️ Pause", width=80, command=self.toggle_pause)
        self.btn_pause.pack(side="right", padx=5)
        
        ctk.CTkButton(frame_toolbar, text="🗑️ Clear", width=80, command=self.clear_logs, 
                      fg_color="gray", hover_color="gray30").pack(side="right", padx=5)

        # 2. Log Display Area
        self.textbox = ctk.CTkTextbox(self, font=("Consolas", 12))
        self.textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # Configure highlight tag (Yellow background, Black text)
        try:
            # Try to access underlying tk widget for tag configuration
            self.textbox._textbox.tag_config("search_highlight", background="#FFFF00", foreground="#000000")
            self.textbox._textbox.tag_config("search_current", background="#FF9900", foreground="#000000") # Darker orange for current
        except Exception:
            pass
            
        # Bind search entry changes to refresh highlights
        self.entry_search.bind("<KeyRelease>", self.on_search_changed)
        
        # Enable selection and copy (standard behavior for Text widget, but good to ensure)
        # CustomTkinter's CTkTextbox wraps a tk.Text, bindings should work on the internal widget if needed
        # But default CTkTextbox already supports selection and Ctrl+C.

    def start_logcat(self):
        level_map = {"Verbose": "V", "Debug": "D", "Info": "I", "Warn": "W", "Error": "E"}
        selected_level = self.combo_level.get()
        level_char = level_map.get(selected_level, "E")
        
        try:
            self.log_queue = self.adb_helper.start_logcat(level_char)
        except Exception as e:
            if self.log_func:
                self.log_func(f"Logcat 启动失败: {e}", "ERROR")
            self.log_queue = None
            return
            
        if self.log_func:
            self.log_func(f"Logcat started with level: {selected_level}", "INFO")
            
        # Start polling
        self.update_logs()

    def stop_logcat(self):
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
            
        self.adb_helper.stop_logcat()
        
        if self.log_func:
            self.log_func("Logcat stopped", "INFO")

    def reset_for_new_device(self):
        """设备切换时重置logcat，清空日志并重新获取新设备的日志"""
        self.stop_logcat()
        self.clear_logs()
        self.observed_pids.clear()
        self.last_pkg_filter = ""
        self.last_tag_pid = None
        self.last_timestamp = None
        if self.log_func:
            self.log_func(f"Logcat 切换到设备: {self.adb_helper.current_device_id}", "INFO")
        self.start_logcat()

    def on_level_change(self, choice):
        self.stop_logcat()
        self.start_logcat()

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        self.btn_pause.configure(text="▶️ Resume" if self.is_paused else "⏸️ Pause")

    def clear_logs(self):
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
        # Reset search state since all text is gone
        self.search_matches.clear()
        self.current_match_index = -1
        self.update_search_ui()

    def update_logs(self):
        if not self.log_queue:
            return

        if not self.is_paused:
            # Process up to N lines to avoid freezing UI
            try:
                # Read all available lines
                lines_to_add = []
                while True:
                    try:
                        line = self.log_queue.get_nowait()
                        if self.should_show_line(line):
                            formatted_line = self.format_log_line(line)
                            lines_to_add.append(formatted_line)
                    except Empty:
                        break
                
                if lines_to_add:
                    self.textbox.configure(state="normal")
                    
                    # Remember start position before insertion for highlighting
                    start_pos = self.textbox.index("end-1c")
                    
                    # Join lines for better performance than inserting one by one
                    self.textbox.insert("end", "".join(lines_to_add))
                    
                    # Apply search highlighting to new content
                    self.apply_highlight(start_pos, "end")
                    
                    # Only auto-scroll to end if we are not actively searching/navigating
                    # or if no search matches have been found yet
                    search_term = self.entry_search.get().strip()
                    if not search_term or not self.search_matches:
                        self.textbox.see("end")
                    elif len(self.search_matches) > 0 and self.search_matches[-1] >= start_pos:
                        # If we just found a new match, scroll to the latest one
                        self.scroll_to_current_match()
                        
                    self.textbox.configure(state="disabled")
                    
            except Exception as e:
                print(f"Error updating logs: {e}")

        # Schedule next update
        self.after_id = self.after(100, self.update_logs)

    def format_log_line(self, line):
        # 尝试匹配并重组日志头
        # 原始格式: "03-17 11:44:24.715 E/AndroidRuntime( 9734): "
        # 目标格式: "2026-03-17 11:44:24.715 9734-9734/? E/AndroidRuntime: "
        match = self.header_pattern.match(line)
        if match:
            timestamp = match.group(1)
            level = match.group(2)
            tag = match.group(3).strip()
            pid = match.group(4).strip()
            
            # 构建用于比较的组合 Key (Tag + PID)
            current_tag_pid = f"{tag}({pid})"
            
            # match.end() 是匹配到的结尾索引 (包含冒号)
            content_start_idx = match.end()
            
            # 手动跳过后续空格 (例如 ": " 或 ":  ")
            while content_start_idx < len(line) and line[content_start_idx] == ' ':
                content_start_idx += 1
            
            content = line[content_start_idx:]
            
            # 分析内容是否为堆栈跟踪的一部分
            clean_content = content.lstrip()
            is_stack_trace = (
                clean_content.startswith("at ") or 
                clean_content.startswith("Caused by:") or 
                clean_content.startswith("Process:") or 
                clean_content.startswith("java.lang.")
            )
            # 特别注意：包含 Exception 的可能是第一行（如 FATAL EXCEPTION: main），不能被合并隐藏头
            is_first_exception_line = "EXCEPTION:" in clean_content

            # 决定是否隐藏日志头
            should_hide_header = False
            
            # 只有当 TAG/PID 完全一致时，才考虑合并
            if current_tag_pid == self.last_tag_pid and not is_first_exception_line:
                # 情况1: 时间戳完全一致 -> 肯定是同一条日志
                # 但是为了防止普通的连续日志也被错误合并（比如连续打印的普通日志刚好在同一毫秒），
                # 我们只合并看起来像堆栈跟踪或明显延续的日志。普通的短日志不合并。
                # 或者，我们可以放宽一点，如果内容以某些特征开头才合并。
                # 实际上，原生的 Android Studio Logcat 对于同一时间、同一 PID 的多条独立 log 是分别显示的，
                # 只是针对异常堆栈才合并。
                # 所以我们这里改为：只有当是堆栈跟踪特征时才合并。
                if is_stack_trace:
                    should_hide_header = True

            # 更新状态
            self.last_timestamp = timestamp
            self.last_tag_pid = current_tag_pid

            if should_hide_header:
                # 根据内容类型决定缩进 (参考用户示例)
                # 堆栈跟踪 (at ...) 使用 8 个空格
                # 其他内容 (包括 Caused by, Process, java.lang... 等) 使用 4 个空格
                # 对于普通的合并行（如多行的普通log），如果没有特征前缀，使用4个空格
                if clean_content.startswith("at "):
                    indent = " " * 8
                else:
                    indent = " " * 4
                    
                return f"{indent}{clean_content}"
            else:
                # 重组 Header
                # 格式: YYYY-MM-DD HH:MM:SS.mmm PID-PID/? Level/Tag: 
                # 注意: 这里无法获取 TID，暂时假设 PID=TID (主线程)
                new_header = f"{self.current_year}-{timestamp} {pid}-{pid}/? {level}/{tag}: "
                return f"{new_header}{content}"
        else:
            # 没匹配到标准头，说明这本身就是前一条日志的延续（比如 adb 输出的纯多行文本，或者由于缓冲被截断的行）
            # 不重置状态，直接返回，并且为了美观可以加个缩进，或者保持原样。这里保持原样，因为可能是纯文本。
            return line

    def should_show_line(self, line):
        pkg_filter = self.entry_pkg.get().strip()
        
        # 包名/PID 过滤 (如果没有设置过滤条件，则显示所有)
        if not pkg_filter:
            return True
            
        # 检查过滤条件是否改变
        if pkg_filter != self.last_pkg_filter:
            self.observed_pids.clear()
            self.last_pkg_filter = pkg_filter
            
        # 尝试提取 PID
        # 格式通常为: "03-17 11:44:24.715 E/AndroidRuntime( 9734):" -> PID 9734
        match = self.pid_pattern.search(line)
        pid = match.group(1) if match else None
        
        # 只有当过滤条件看起来像包名（包含点号）时，我们才启用 PID 追踪逻辑
        # 否则（如简单的字符串过滤），我们只做简单的包含匹配
        is_package_name_filter = "." in pkg_filter
        
        # A. 如果行包含过滤关键字
        if pkg_filter in line:
            # 如果是按包名过滤，我们记录它的 PID，以便后续抓取它的其他日志（如崩溃堆栈）
            if is_package_name_filter and pid:
                self.observed_pids.add(pid)
            return True
            
        # B. 如果行不包含关键字，但启用了包名过滤，且 PID 是之前观察到的目标 App 的 PID -> 这是堆栈跟踪或其他相关日志
        if is_package_name_filter and pid and pid in self.observed_pids:
            return True
            
        return False

    def on_close(self):
        self.stop_logcat()
        self.destroy()

    def on_search_changed(self, event=None):
        """Called when search text changes, resets search state and refreshes."""
        self.search_matches = []
        self.current_match_index = -1
        self.refresh_highlights()

    def refresh_highlights(self, event=None):
        """
        Refresh highlights for the entire text buffer.
        """
        try:
            # Remove all existing highlights
            self.textbox._textbox.tag_remove("search_highlight", "1.0", "end")
            self.textbox._textbox.tag_remove("search_current", "1.0", "end")
            self.search_matches.clear()
            self.current_match_index = -1
            
            # Re-apply based on current search term
            self.apply_highlight("1.0", "end")
            
            # If we found matches from a manual search edit, jump to the first one
            if self.search_matches:
                self.current_match_index = 0
                self.update_search_ui()
                self.scroll_to_current_match()
            else:
                self.update_search_ui()
                
        except Exception as e:
            print(f"Error refreshing highlights: {e}")

    def update_search_ui(self):
        """Updates the 1/N label and button states"""
        total = len(self.search_matches)
        if total == 0:
            self.label_match_count.configure(text="0/0")
            self.btn_prev_match.configure(state="disabled")
            self.btn_next_match.configure(state="disabled")
        else:
            current = self.current_match_index + 1
            self.label_match_count.configure(text=f"{current}/{total}")
            self.btn_prev_match.configure(state="normal")
            self.btn_next_match.configure(state="normal")

    def scroll_to_current_match(self):
        if not self.search_matches or self.current_match_index < 0 or self.current_match_index >= len(self.search_matches):
            return
            
        try:
            # Clear old current highlight, keep base highlight
            self.textbox._textbox.tag_remove("search_current", "1.0", "end")
            
            pos = self.search_matches[self.current_match_index]
            search_term = self.entry_search.get().strip()
            end_pos = f"{pos}+{len(search_term)}c"
            
            # Apply distinct current match highlight
            self.textbox._textbox.tag_add("search_current", pos, end_pos)
            # Ensure it overlays the base highlight
            self.textbox._textbox.tag_raise("search_current", "search_highlight")
            
            # Scroll to make it visible
            self.textbox.see(pos)
            
            # 调整滚动位置，使其显示在窗口大约 1/3 处
            # see() 默认只是让内容可见（通常在最底或最顶），我们需要计算行数并手动调整
            line_str = pos.split('.')[0]
            if line_str.isdigit():
                target_line = int(line_str)
                # 获取 Text widget 当前可见的高度（以行数为单位，估算）
                # 这里使用一个固定的估算值或者动态计算
                # 简单的方法：滚动到 target_line，然后再向下滚动一定行数
                # 让 target_line 出现在偏上的位置
                # fraction 为 0.0 代表最顶，1.0 代表最底。但是 yview_moveto 需要的是整个文档的比例，不准
                
                # 更好的方法是使用 yview_pickplace 或类似机制，
                # 但由于 tkinter text 的特性，我们可以先看它，然后向上滚动几行
                # 但是为了精确控制，我们可以通过 yview 将特定行放到顶部，然后再向上滚动视口的 1/3
                
                self.textbox._textbox.yview_pickplace(pos)
                
                # 尝试通过计算可见行数来调整
                # 默认情况下，我们将其放在视口中间偏上
                self.textbox.after(50, lambda: self._adjust_scroll_position(pos))

        except Exception as e:
            print(f"Error scrolling to match: {e}")

    def _adjust_scroll_position(self, pos):
        """Helper to adjust the scroll position so the match is around 1/3 from the top."""
        try:
            # bbox returns (x, y, width, height) of the character if visible, else None
            bbox = self.textbox._textbox.bbox(pos)
            if not bbox:
                self.textbox.see(pos)
                bbox = self.textbox._textbox.bbox(pos)
                
            if bbox:
                # Get the height of the textbox
                widget_height = self.textbox._textbox.winfo_height()
                if widget_height > 1:
                    # Current y position of the character
                    char_y = bbox[1]
                    # Target y position (1/3 of widget height)
                    target_y = widget_height / 3.0
                    
                    # Calculate how many pixels we need to scroll
                    # Positive means we need to scroll up (view down)
                    dy = char_y - target_y
                    
                    # If dy is significant, we adjust the yview
                    if abs(dy) > 10:
                        # yview_scroll takes 'units' (lines) or 'pages'
                        # We approximate lines by character height
                        char_height = bbox[3]
                        lines_to_scroll = int(dy / char_height)
                        if lines_to_scroll != 0:
                            self.textbox._textbox.yview_scroll(lines_to_scroll, "units")
        except Exception as e:
            print(f"Error adjusting scroll: {e}")

    def next_match(self):
        if not self.search_matches:
            return
        self.current_match_index = (self.current_match_index + 1) % len(self.search_matches)
        self.update_search_ui()
        self.scroll_to_current_match()

    def prev_match(self):
        if not self.search_matches:
            return
        self.current_match_index = (self.current_match_index - 1) % len(self.search_matches)
        self.update_search_ui()
        self.scroll_to_current_match()

    def apply_highlight(self, start_index, end_index):
        """
        Apply 'search_highlight' tag to all occurrences of search term in the given range.
        Also appends to search_matches list.
        """
        search_term = self.entry_search.get().strip()
        if not search_term:
            self.update_search_ui()
            return

        try:
            count_var = tk.IntVar()
            current_pos = start_index
            new_matches_added = False
            
            while True:
                # Search for the term (case-sensitive)
                current_pos = self.textbox._textbox.search(
                    search_term, 
                    current_pos, 
                    stopindex=end_index, 
                    nocase=False, 
                    count=count_var
                )
                
                if not current_pos:
                    break
                    
                match_len = count_var.get()
                if match_len == 0:
                    break
                    
                # Calculate end of match
                end_match = f"{current_pos}+{match_len}c"
                
                # Apply tag
                self.textbox._textbox.tag_add("search_highlight", current_pos, end_match)
                self.search_matches.append(str(current_pos))
                new_matches_added = True
                
                # Move to next position
                current_pos = end_match
                
            if new_matches_added:
                # Only set current_match_index if no match is currently selected
                # (avoid overriding user's navigation position)
                if self.current_match_index < 0:
                    self.current_match_index = 0
                self.update_search_ui()
                
        except Exception as e:
            print(f"Error applying highlight: {e}")
