# -*- coding: utf-8 -*-
"""
更新流程 UI：检查 → 询问 → 下载进度 → 应用。

所有回调都通过 `self.after(0, ...)` 切回主线程，避免 Tk 非线程安全问题。
"""

import sys
import tkinter.messagebox as messagebox

import customtkinter as ctk

from core.config import APP_VERSION
from core.platform_utils import PlatformUtils
from core.updater import Updater


def _fmt_size(n):
    if not n:
        return "--"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class UpdateFlow:
    """
    发起并管理一次完整的"检查更新 → 下载 → 应用"流程。
    挂在任意 Tk 窗口上即可，不自己创建 Toplevel 作为父窗口。
    """

    def __init__(self, parent, log_func=None):
        self.parent = parent
        self.log = log_func or (lambda *a, **k: None)
        self.updater = Updater()
        self._progress_window = None
        self._cancel_download = None

    # ---------- 入口 ----------
    def start(self):
        """用户点击"检查更新"时调用。"""
        self.log(f"开始检查更新（当前版本 v{APP_VERSION}）", "INFO")
        # 轻量状态窗，防止用户重复点击
        busy = self._make_busy_window("正在检查更新...")

        def on_result(info):
            self.parent.after(0, lambda: self._after_check(busy, info))

        def on_error(msg):
            self.parent.after(0, lambda: self._after_check_error(busy, msg))

        self.updater.check_async(on_result, on_error)

    # ---------- 检查结果 ----------
    def _after_check(self, busy, info):
        self._close_window(busy)
        if info is None:
            self.log("当前已是最新版本", "SUCCESS")
            messagebox.showinfo(
                "检查更新",
                f"当前已是最新版本 (v{APP_VERSION})。",
                parent=self.parent,
            )
            return

        body = (info.get("body") or "").strip() or "（发布说明为空）"
        msg = (
            f"发现新版本：v{info['version']}（当前 v{APP_VERSION}）\n\n"
            f"更新内容：\n{body}\n\n"
            f"下载文件：{info['asset_name']}  {_fmt_size(info['asset_size'])}\n\n"
            "是否立即下载并更新？"
        )
        if messagebox.askyesno("发现新版本", msg, parent=self.parent):
            self._begin_download(info)
        else:
            self.log("用户取消了更新", "INFO")

    def _after_check_error(self, busy, msg):
        self._close_window(busy)
        self.log(f"检查更新失败: {msg}", "ERROR")
        messagebox.showerror("检查更新失败", msg, parent=self.parent)

    # ---------- 下载 ----------
    def _begin_download(self, info):
        win = self._make_progress_window(info["asset_name"], info["asset_size"])
        self._progress_window = win

        def on_progress(done, total):
            self.parent.after(0, lambda: self._update_progress(done, total))

        def on_complete(path):
            self.parent.after(0, lambda: self._after_download(info, path))

        def on_error(msg):
            self.parent.after(0, lambda: self._after_download_error(msg))

        self._cancel_download = self.updater.download_async(
            info["asset_url"], info["asset_name"],
            on_progress, on_complete, on_error,
        )

    def _update_progress(self, done, total):
        if self._progress_window is None or not self._progress_window.winfo_exists():
            return
        if total > 0:
            ratio = min(done / total, 1.0)
            self._progress_bar.set(ratio)
            self._progress_label.configure(
                text=f"{_fmt_size(done)} / {_fmt_size(total)}  ({ratio * 100:.1f}%)"
            )
        else:
            # 未知总大小：进度条来回滚动
            self._progress_bar.configure(mode="indeterminate")
            self._progress_bar.start()
            self._progress_label.configure(text=f"已下载 {_fmt_size(done)}")

    def _after_download(self, info, save_path):
        self._close_progress()
        self.log(f"更新包已下载: {save_path}", "SUCCESS")

        if PlatformUtils.get_os_type() != "win":
            messagebox.showinfo(
                "下载完成",
                f"已下载到：\n{save_path}\n\n"
                "当前平台暂不支持自动替换，请手动解压安装。",
                parent=self.parent,
            )
            return

        if not getattr(sys, "frozen", False):
            messagebox.showinfo(
                "下载完成（开发模式）",
                f"已下载到：\n{save_path}\n\n"
                "当前以源码方式运行，未执行自动替换。",
                parent=self.parent,
            )
            return

        if not messagebox.askyesno(
            "下载完成",
            f"v{info['version']} 已下载完成。\n\n"
            "现在将关闭程序并安装新版本，是否继续？",
            parent=self.parent,
        ):
            return

        try:
            self.updater.apply_update_windows(save_path)
        except Exception as e:
            self.log(f"启动更新脚本失败: {e}", "ERROR")
            messagebox.showerror("更新失败", f"启动更新脚本失败：\n{e}", parent=self.parent)
            return

        # 让 bat 脚本接管后续流程：关闭主程序
        self.parent.after(500, self._quit_app)

    def _after_download_error(self, msg):
        self._close_progress()
        self.log(f"下载失败: {msg}", "ERROR")
        messagebox.showerror("下载失败", msg, parent=self.parent)

    def _quit_app(self):
        try:
            root = self.parent.winfo_toplevel()
            if hasattr(root, "on_closing"):
                root.on_closing()
            else:
                root.destroy()
        except Exception:
            pass
        # 保底
        sys.exit(0)

    # ---------- 小窗口辅助 ----------
    def _make_busy_window(self, text):
        win = ctk.CTkToplevel(self.parent)
        win.title("请稍候")
        win.geometry("300x90")
        win.resizable(False, False)
        win.transient(self.parent)
        ctk.CTkLabel(win, text=text, font=ctk.CTkFont(size=13)).pack(pady=(20, 10))
        bar = ctk.CTkProgressBar(win, mode="indeterminate")
        bar.pack(fill="x", padx=20)
        bar.start()
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        self._center_on_parent(win, 300, 90)
        return win

    def _make_progress_window(self, asset_name, asset_size):
        win = ctk.CTkToplevel(self.parent)
        win.title("下载更新")
        win.geometry("420x160")
        win.resizable(False, False)
        win.transient(self.parent)
        # 禁止通过 X 关闭：强制走"取消"按钮，防止下载线程野着
        win.protocol("WM_DELETE_WINDOW", self._cancel_clicked)

        ctk.CTkLabel(
            win, text=f"正在下载：{asset_name}",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(pady=(15, 5), padx=20, anchor="w")

        self._progress_bar = ctk.CTkProgressBar(win, mode="determinate")
        self._progress_bar.set(0)
        self._progress_bar.pack(fill="x", padx=20, pady=5)

        self._progress_label = ctk.CTkLabel(
            win, text=f"0 / {_fmt_size(asset_size)}  (0%)",
        )
        self._progress_label.pack(pady=5)

        ctk.CTkButton(win, text="取消", width=80, command=self._cancel_clicked).pack(pady=5)

        self._center_on_parent(win, 420, 160)
        return win

    def _cancel_clicked(self):
        if self._cancel_download:
            self._cancel_download()
        self._close_progress()

    def _close_progress(self):
        if self._progress_window is not None:
            try:
                self._progress_bar.stop()
            except Exception:
                pass
            self._close_window(self._progress_window)
            self._progress_window = None

    @staticmethod
    def _close_window(win):
        try:
            if win and win.winfo_exists():
                win.destroy()
        except Exception:
            pass

    def _center_on_parent(self, win, w, h):
        try:
            self.parent.update_idletasks()
            px = self.parent.winfo_rootx()
            py = self.parent.winfo_rooty()
            pw = self.parent.winfo_width()
            ph = self.parent.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
            win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass
