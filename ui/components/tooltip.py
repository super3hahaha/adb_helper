import tkinter as tk


class ModernTooltip:
    """
    现代化悬浮提示框，支持结构化内容（标题+描述）。

    用法:
        ModernTooltip(widget, sections=[
            ("标题1", "描述文本1"),
            ("标题2", "描述文本2"),
        ])
    """

    DELAY_MS = 400          # 鼠标悬停延迟显示时间
    OFFSET_X = 20           # 鼠标右下方偏移
    OFFSET_Y = 20
    MAX_WIDTH = 380         # 最大宽度（默认）

    # 浅色主题配色
    BG_COLOR = "#F8F9FA"
    BORDER_COLOR = "#D1D5DB"
    TITLE_COLOR = "#1F2937"
    TEXT_COLOR = "#4B5563"
    FONT_FAMILY = "Microsoft YaHei"
    FONT_SIZE = 9

    def __init__(self, widget, sections, max_width=None):
        """
        :param widget: 要绑定的控件
        :param sections: 结构化数据 [(标题, 描述), ...]
        :param max_width: 可选，覆盖默认 MAX_WIDTH（例如快捷键列表需要更宽以避免换行）
        """
        self.widget = widget
        self.sections = sections
        self.max_width = max_width if max_width is not None else self.MAX_WIDTH
        self._tooltip_window = None
        self._after_id = None

        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")

    def _on_enter(self, event=None):
        self._cancel_pending()
        # 记录鼠标位置用于定位
        self._mouse_x = event.x_root if event else 0
        self._mouse_y = event.y_root if event else 0
        self._after_id = self.widget.after(self.DELAY_MS, self._show)

    def _on_leave(self, event=None):
        self._cancel_pending()
        self._hide()

    def _cancel_pending(self):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        if self._tooltip_window:
            return

        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.attributes("-topmost", True)
        self._tooltip_window = tw

        # 用外层 Frame 模拟 1px 边框（避免原生 bd 的 3D 效果）
        border_frame = tk.Frame(tw, bg=self.BORDER_COLOR)
        border_frame.pack(fill="both", expand=True)

        inner_frame = tk.Frame(border_frame, bg=self.BG_COLOR)
        inner_frame.pack(padx=1, pady=1, fill="both", expand=True)

        # 内容区，留出呼吸空间
        content = tk.Frame(inner_frame, bg=self.BG_COLOR)
        content.pack(padx=12, pady=10)

        for i, (title, desc) in enumerate(self.sections):
            # 段落间距
            if i > 0:
                tk.Frame(content, height=8, bg=self.BG_COLOR).pack()

            # 标题 - 加粗
            lbl_title = tk.Label(
                content, text=title,
                font=(self.FONT_FAMILY, self.FONT_SIZE, "bold"),
                fg=self.TITLE_COLOR, bg=self.BG_COLOR,
                anchor="w", justify="left",
                wraplength=self.max_width,
            )
            lbl_title.pack(anchor="w")

            # 描述 - 常规
            lbl_desc = tk.Label(
                content, text=desc,
                font=(self.FONT_FAMILY, self.FONT_SIZE),
                fg=self.TEXT_COLOR, bg=self.BG_COLOR,
                anchor="w", justify="left",
                wraplength=self.max_width,
            )
            lbl_desc.pack(anchor="w", pady=(1, 0))

        # 定位到鼠标右下方
        tw.update_idletasks()
        tip_w = tw.winfo_reqwidth()
        tip_h = tw.winfo_reqheight()
        screen_w = tw.winfo_screenwidth()
        screen_h = tw.winfo_screenheight()

        x = self._mouse_x + self.OFFSET_X
        y = self._mouse_y + self.OFFSET_Y

        # 防止超出屏幕右侧/底部
        if x + tip_w > screen_w:
            x = self._mouse_x - tip_w - 5
        if y + tip_h > screen_h:
            y = self._mouse_y - tip_h - 5

        tw.geometry(f"+{x}+{y}")

    def _hide(self):
        if self._tooltip_window:
            self._tooltip_window.destroy()
            self._tooltip_window = None

    def destroy(self):
        """手动解绑并清理"""
        self._cancel_pending()
        self._hide()
        self.widget.unbind("<Enter>")
        self.widget.unbind("<Leave>")
